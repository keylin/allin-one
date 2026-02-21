"""定时调度任务 — Procrastinate periodic

对照脑图「任务调度」:
  定时器 → 数据抓取 (智能调度, 退避策略, 信息流抓取)
           周期任务 (内容分析, 批量报告)
  流水线 → 数据处理

核心流程:
  定时器 → CollectionService.collect(source)
         → Collector 抓取原始数据 → 去重 → 创建 ContentItem
         → 对每条新内容, 按绑定的流水线模板创建 PipelineExecution

所有定时任务由 Procrastinate worker 的 periodic 功能驱动。
"""

import logging

from app.tasks.procrastinate_app import proc_app

logger = logging.getLogger(__name__)


@proc_app.periodic(cron="*/1 * * * *")  # 每1分钟触发，支持60秒最小间隔
@proc_app.task(queue="scheduled", queueing_lock="collection_loop")
async def check_and_collect_sources(timestamp):
    """主采集循环 — 智能调度 + 退避策略"""
    import time
    start_time = time.time()  # 性能监控：记录开始时间

    from datetime import timedelta
    from app.core.database import SessionLocal
    from app.core.time import utcnow
    from app.models.content import SourceConfig, ContentItem, ContentStatus
    from app.models.pipeline import TriggerSource
    from app.services.pipeline.orchestrator import PipelineOrchestrator
    from app.services.scheduling_service import SchedulingService

    with SessionLocal() as db:
        now = utcnow()
        query_start = time.time()  # 性能监控：记录查询开始时间

        # 使用智能调度：查询 next_collection_at <= now 的源
        # 索引优化：ix_source_next_collection (is_active, schedule_enabled, next_collection_at)
        sources = db.query(SourceConfig).filter(
            SourceConfig.is_active == True,
            SourceConfig.schedule_enabled == True,
            (SourceConfig.next_collection_at.is_(None)) |
            (SourceConfig.next_collection_at <= now)
        ).all()

        query_elapsed = time.time() - query_start
        logger.info(
            f"Collection check: {len(sources)} sources due for collection "
            f"(query took {query_elapsed*1000:.1f}ms)"
        )

        # ---- defer 采集任务到 worker 并发执行 ----
        from app.tasks.collection_tasks import collect_single_source
        from app.tasks.procrastinate_app import async_defer

        sources_deferred = 0
        sources_skipped = 0

        for source in sources:
            # 二次确认（防止并发或时间偏移）
            if not SchedulingService.should_collect_now(source, now):
                sources_skipped += 1
                continue

            try:
                await async_defer(
                    collect_single_source,
                    queueing_lock=f"collect_{source.id}",
                    source_id=source.id,
                    trigger="scheduled",
                    use_retry=True,
                )
                sources_deferred += 1
            except Exception as e:
                logger.debug(f"Collection defer skipped for {source.name} (already queued): {e}")
                sources_skipped += 1

        logger.info(
            f"Collection scheduler: {sources_deferred} deferred, "
            f"{sources_skipped} skipped"
        )

        # ---- 补偿: 对 pending 且无 pipeline 的内容补触发 ----
        from app.models.pipeline import PipelineExecution
        from sqlalchemy import not_, exists

        # 限制每次补偿100条，避免1分钟周期下单次查询过多（频率增加5倍）
        orphaned = db.query(ContentItem).filter(
            ContentItem.status == ContentStatus.PENDING.value,
            ~exists().where(PipelineExecution.content_id == ContentItem.id),
        ).limit(100).all()

        if orphaned:
            logger.info(f"Compensation: {len(orphaned)} pending items without pipeline")
            orchestrator = PipelineOrchestrator(db)
            for item in orphaned:
                try:
                    execution = orchestrator.trigger_for_content(
                        content=item,
                        trigger=TriggerSource.SCHEDULED,
                    )
                    if execution:
                        await orchestrator.async_start_execution(execution.id)
                        logger.info(f"Compensation pipeline: {item.title[:50]} → {execution.template_name}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Compensation trigger failed for {item.title[:50]}: {e}")
            db.commit()

        # ---- 恢复: 卡在 running 超时的步骤重新入队 ----
        from app.models.pipeline import PipelineStep, StepStatus, PipelineStatus

        stale_timeout = timedelta(minutes=30)
        stale_steps = db.query(PipelineStep).filter(
            PipelineStep.status == StepStatus.RUNNING.value,
            PipelineStep.started_at < now - stale_timeout,
        ).all()

        steps_to_requeue = []
        for step in stale_steps:
            step.status = StepStatus.PENDING.value
            step.started_at = None
            step.error_message = None
            execution = db.get(PipelineExecution, step.pipeline_id)
            if execution and execution.status == PipelineStatus.RUNNING.value:
                logger.info(f"Recovering stale step: {step.step_type} (pipeline={step.pipeline_id[:12]})")
                steps_to_requeue.append((step.pipeline_id, step.step_index))

        if stale_steps:
            db.commit()
            # 重新入队（commit 后再入队，确保状态已持久化）
            from app.tasks.pipeline_tasks import execute_pipeline_step
            from app.tasks.procrastinate_app import async_defer
            for pipeline_id, step_index in steps_to_requeue:
                await async_defer(execute_pipeline_step, execution_id=pipeline_id, step_index=step_index)

        # ---- 恢复: execution 卡住 (defer 失败或 worker 崩溃) ----
        # 情况1: PENDING 超过 10 分钟 — sync_defer 可能失败, 重新入队
        # 情况2: RUNNING 但当前步骤仍 pending — worker 崩溃后未推进
        stuck_execs = db.query(PipelineExecution).filter(
            (
                (PipelineExecution.status == PipelineStatus.PENDING.value)
                & (PipelineExecution.created_at < now - timedelta(minutes=10))
            ) | (
                (PipelineExecution.status == PipelineStatus.RUNNING.value)
                & (PipelineExecution.started_at < now - timedelta(minutes=2))
            )
        ).all()

        stuck_to_requeue = []
        for ex in stuck_execs:
            current_step = db.query(PipelineStep).filter(
                PipelineStep.pipeline_id == ex.id,
                PipelineStep.step_index == ex.current_step,
                PipelineStep.status == StepStatus.PENDING.value,
            ).first()
            if current_step:
                stuck_to_requeue.append((ex.id, ex.current_step))

        if stuck_to_requeue:
            logger.info(f"Recovering {len(stuck_to_requeue)} stuck executions (pending step, defer likely failed)")
            from app.tasks.pipeline_tasks import execute_pipeline_step
            from app.tasks.procrastinate_app import async_defer
            for pipeline_id, step_index in stuck_to_requeue:
                try:
                    await async_defer(execute_pipeline_step, execution_id=pipeline_id, step_index=step_index)
                except Exception as e:
                    logger.error(f"Failed to requeue stuck step: pipeline={pipeline_id[:12]}, error={e}")

        # ---- 性能监控: 记录主循环总耗时 ----
        total_elapsed = time.time() - start_time
        logger.info(f"Collection loop completed in {total_elapsed:.2f}s")
        if total_elapsed > 55:  # 接近1分钟超时（留5秒余量）
            logger.warning(
                f"Collection loop near timeout: {total_elapsed:.2f}s "
                f"(processed {len(sources)} sources)"
            )


@proc_app.periodic(cron="0 22 * * *")
@proc_app.task(queue="scheduled", queueing_lock="daily_report")
async def trigger_daily_report(timestamp):
    """日报 — 每天 22:00"""
    from app.tasks.report_tasks import generate_daily_report
    await generate_daily_report()


@proc_app.periodic(cron="0 9 * * 1")
@proc_app.task(queue="scheduled", queueing_lock="weekly_report")
async def trigger_weekly_report(timestamp):
    """周报 — 每周一 09:00"""
    from app.tasks.report_tasks import generate_weekly_report
    await generate_weekly_report()


@proc_app.periodic(cron="0 4 * * *")
@proc_app.task(queue="scheduled", queueing_lock="analyze_periodicity")
async def analyze_source_periodicity(timestamp):
    """周期性分析任务 — 每天凌晨 4 点分析所有活跃源的更新模式"""
    import json
    from app.core.database import SessionLocal
    from app.core.time import utcnow
    from app.models.content import SourceConfig
    from app.services.scheduling_service import SchedulingService

    with SessionLocal() as db:
        sources = db.query(SourceConfig).filter(
            SourceConfig.is_active == True,
            SourceConfig.schedule_mode == "auto",
        ).all()

        analyzed_count = 0
        for source in sources:
            try:
                # 检查是否需要更新（至少24小时一次）
                if source.periodicity_updated_at:
                    hours_since = (utcnow() - source.periodicity_updated_at).total_seconds() / 3600
                    if hours_since < 24:
                        continue

                # 执行周期性分析
                periodicity = SchedulingService.analyze_periodicity(source, db)

                # 保存结果
                if periodicity["pattern_type"] != "none":
                    source.periodicity_data = json.dumps(periodicity)
                    logger.info(
                        f"Periodicity detected: {source.name} - {periodicity['pattern_type']} "
                        f"(confidence={periodicity['confidence']:.2f})"
                    )
                else:
                    source.periodicity_data = None

                source.periodicity_updated_at = utcnow()
                analyzed_count += 1

            except Exception as e:
                logger.error(f"Periodicity analysis failed for {source.name}: {e}")

        db.commit()
        logger.info(f"Periodicity analysis complete: {analyzed_count}/{len(sources)} sources analyzed")


@proc_app.periodic(cron="0 * * * *")
@proc_app.task(queue="scheduled", queueing_lock="cleanup_scheduler")
async def cleanup_scheduler(timestamp):
    """清理任务调度器 — 每小时检查,根据配置动态执行清理"""
    from app.core.time import utcnow
    from app.core.database import SessionLocal
    from app.models.system_setting import SystemSetting

    with SessionLocal() as db:
        # 读取配置的清理时间（格式：HH:MM）
        content_time_setting = db.get(SystemSetting, "cleanup_content_time")
        records_time_setting = db.get(SystemSetting, "cleanup_records_time")

        content_cleanup_time = content_time_setting.value if content_time_setting else "03:00"
        records_cleanup_time = records_time_setting.value if records_time_setting else "03:30"

        # 获取当前 UTC 时间
        now = utcnow()
        current_time = f"{now.hour:02d}:{now.minute:02d}"

        # 检查是否到达内容清理时间
        if should_run_cleanup(current_time, content_cleanup_time):
            last_run_key = "cleanup_content_last_run"
            last_run = db.get(SystemSetting, last_run_key)
            today = now.strftime("%Y-%m-%d")

            if not last_run or last_run.value != today:
                logger.info(f"Running content cleanup at configured time: {content_cleanup_time} UTC")
                await cleanup_expired_content()

                # 更新最后执行日期
                if last_run:
                    last_run.value = today
                else:
                    db.add(SystemSetting(key=last_run_key, value=today))
                db.commit()

        # 检查是否到达记录清理时间
        if should_run_cleanup(current_time, records_cleanup_time):
            last_run_key = "cleanup_records_last_run"
            last_run = db.get(SystemSetting, last_run_key)
            today = now.strftime("%Y-%m-%d")

            if not last_run or last_run.value != today:
                logger.info(f"Running records cleanup at configured time: {records_cleanup_time} UTC")
                await cleanup_records()

                if last_run:
                    last_run.value = today
                else:
                    db.add(SystemSetting(key=last_run_key, value=today))
                db.commit()


def should_run_cleanup(current_time: str, target_time: str) -> bool:
    """判断当前时间是否匹配目标清理时间（允许±30分钟误差）"""
    try:
        current_h, current_m = map(int, current_time.split(':'))
        target_h, target_m = map(int, target_time.split(':'))

        current_minutes = current_h * 60 + current_m
        target_minutes = target_h * 60 + target_m

        # 允许±30分钟误差（因为调度器每小时运行一次）
        return abs(current_minutes - target_minutes) <= 30
    except Exception:
        logger.warning(f"Failed to parse cleanup time: current='{current_time}', target='{target_time}'")
        return False


async def cleanup_expired_content():
    """定时清理过期内容

    逻辑:
    1. 读取全局默认 default_retention_days
    2. 遍历所有 auto_cleanup_enabled=True 的数据源
    3. 删除超过保留期且未收藏、无笔记的内容（级联删除关联数据+媒体文件）
    """
    import shutil
    from pathlib import Path
    from datetime import timedelta
    from app.core.database import SessionLocal
    from app.core.config import settings
    from app.core.time import utcnow
    from app.models.content import SourceConfig, ContentItem, MediaItem
    from app.models.pipeline import PipelineExecution, PipelineStep
    from app.models.system_setting import SystemSetting

    with SessionLocal() as db:
        # 读取全局默认保留天数
        setting = db.get(SystemSetting, "default_retention_days")
        global_retention = int(setting.value) if setting and setting.value else 30
        if global_retention <= 0:
            logger.info("Cleanup skipped: global retention is 0 (keep forever)")
            return

        sources = db.query(SourceConfig).all()

        if not sources:
            logger.info("Cleanup: no sources found")
            return

        now = utcnow()
        total_deleted = 0

        for source in sources:
            retention = source.retention_days if source.retention_days and source.retention_days > 0 else global_retention
            cutoff = now - timedelta(days=retention)

            # 查找过期且未保护的内容
            expired_items = db.query(ContentItem).filter(
                ContentItem.source_id == source.id,
                ContentItem.collected_at < cutoff,
                ContentItem.is_favorited == False,
                ContentItem.user_note.is_(None),
            ).all()

            if not expired_items:
                continue

            item_ids = [item.id for item in expired_items]

            # 级联删除: steps → executions → media_items → items
            execution_ids = [
                eid for (eid,) in db.query(PipelineExecution.id)
                .filter(PipelineExecution.content_id.in_(item_ids))
                .all()
            ]
            if execution_ids:
                db.query(PipelineStep).filter(
                    PipelineStep.pipeline_id.in_(execution_ids)
                ).delete(synchronize_session=False)
                db.query(PipelineExecution).filter(
                    PipelineExecution.id.in_(execution_ids)
                ).delete(synchronize_session=False)

            db.query(MediaItem).filter(
                MediaItem.content_id.in_(item_ids)
            ).delete(synchronize_session=False)

            deleted = db.query(ContentItem).filter(
                ContentItem.id.in_(item_ids)
            ).delete(synchronize_session=False)

            db.commit()

            # 清理媒体文件
            media_base = Path(settings.MEDIA_DIR)
            audio_base = media_base / "audio"
            for item_id in item_ids:
                for d in [media_base / item_id, audio_base / item_id]:
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)

            total_deleted += deleted
            logger.info(f"Cleanup [{source.name}]: deleted {deleted} expired items (retention={retention}d)")

        logger.info(f"Cleanup complete: {total_deleted} items deleted from {len(sources)} sources")


async def cleanup_records():
    """定时清理执行记录和采集记录

    逻辑:
    1. 读取 4 个 setting key (retention_days + max_count)
    2. 按天数清理: 删除 created_at/started_at 早于 cutoff 的已终态记录
    3. 按数量清理: 按时间倒序保留前 N 条，删除多余的已终态记录
    """
    from datetime import timedelta
    from app.core.database import SessionLocal
    from app.core.time import utcnow
    from app.models.system_setting import SystemSetting
    from app.models.pipeline import PipelineExecution, PipelineStep, PipelineStatus
    from app.models.content import CollectionRecord

    with SessionLocal() as db:
        # 读取设置
        def get_setting(key: str, default: int) -> int:
            row = db.get(SystemSetting, key)
            if row and row.value:
                try:
                    return int(row.value)
                except ValueError:
                    pass
            return default

        exec_retention_days = get_setting("execution_retention_days", 30)
        exec_max_count = get_setting("execution_max_count", 0)
        coll_retention_days = get_setting("collection_retention_days", 30)
        coll_max_count = get_setting("collection_max_count", 0)

        now = utcnow()
        total_exec_deleted = 0
        total_coll_deleted = 0

        # ---- 执行记录清理 ----
        exec_terminal = [
            PipelineStatus.COMPLETED.value,
            PipelineStatus.FAILED.value,
            PipelineStatus.CANCELLED.value,
        ]

        # 按天数清理
        if exec_retention_days > 0:
            cutoff = now - timedelta(days=exec_retention_days)
            exec_ids = [
                eid for (eid,) in db.query(PipelineExecution.id).filter(
                    PipelineExecution.status.in_(exec_terminal),
                    PipelineExecution.created_at < cutoff,
                ).all()
            ]
            if exec_ids:
                db.query(PipelineStep).filter(
                    PipelineStep.pipeline_id.in_(exec_ids)
                ).delete(synchronize_session=False)
                deleted = db.query(PipelineExecution).filter(
                    PipelineExecution.id.in_(exec_ids)
                ).delete(synchronize_session=False)
                total_exec_deleted += deleted

        # 按数量清理
        if exec_max_count > 0:
            # 按创建时间倒序, 跳过前 N 条, 删除剩余的已终态记录
            overflow_ids = [
                eid for (eid,) in db.query(PipelineExecution.id).filter(
                    PipelineExecution.status.in_(exec_terminal),
                ).order_by(PipelineExecution.created_at.desc()).offset(exec_max_count).all()
            ]
            if overflow_ids:
                db.query(PipelineStep).filter(
                    PipelineStep.pipeline_id.in_(overflow_ids)
                ).delete(synchronize_session=False)
                deleted = db.query(PipelineExecution).filter(
                    PipelineExecution.id.in_(overflow_ids)
                ).delete(synchronize_session=False)
                total_exec_deleted += deleted

        # ---- 采集记录清理（带保护机制）----
        coll_terminal = ["completed", "failed"]

        # 🆕 每个数据源至少保留的记录数
        MIN_KEEP_PER_SOURCE = get_setting("collection_min_keep", 10)

        # 按天数清理（保护最新记录）
        if coll_retention_days > 0:
            cutoff = now - timedelta(days=coll_retention_days)

            # 🆕 按数据源分别处理，确保每个源至少保留 MIN_KEEP_PER_SOURCE 条
            from app.models.content import SourceConfig
            sources = db.query(SourceConfig).all()

            for source in sources:
                # 查询该源的所有终态记录，按时间倒序
                all_records = db.query(CollectionRecord).filter(
                    CollectionRecord.source_id == source.id,
                    CollectionRecord.status.in_(coll_terminal),
                ).order_by(CollectionRecord.started_at.desc()).all()

                # 保护最新的 MIN_KEEP_PER_SOURCE 条记录
                if len(all_records) <= MIN_KEEP_PER_SOURCE:
                    continue  # 总数不超过最小保留数，跳过清理

                # 只删除过期且不在保护范围内的记录
                deletable_ids = [
                    r.id for r in all_records[MIN_KEEP_PER_SOURCE:]
                    if r.started_at < cutoff
                ]

                if deletable_ids:
                    deleted = db.query(CollectionRecord).filter(
                        CollectionRecord.id.in_(deletable_ids)
                    ).delete(synchronize_session=False)
                    total_coll_deleted += deleted
                    logger.info(
                        f"Cleanup [{source.name}]: deleted {deleted} collection records "
                        f"(kept {MIN_KEEP_PER_SOURCE} most recent)"
                    )

        db.commit()
        logger.info(
            f"Records cleanup: {total_exec_deleted} executions, "
            f"{total_coll_deleted} collection records deleted. "
            f"Protected records per source: {MIN_KEEP_PER_SOURCE}"
        )

        # 🆕 大量删除警告
        if total_coll_deleted > 100:
            logger.warning(
                f"Large cleanup detected: {total_coll_deleted} collection records deleted. "
                f"Please check retention settings."
            )
