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


@proc_app.periodic(cron="*/5 * * * *")
@proc_app.task(queue="scheduled", queueing_lock="collection_loop")
async def check_and_collect_sources(timestamp):
    """主采集循环 — 智能调度 + 退避策略"""
    from app.core.database import SessionLocal
    from app.models.content import SourceConfig, ContentItem, ContentStatus
    from app.models.pipeline import TriggerSource
    from app.services.pipeline.orchestrator import PipelineOrchestrator
    from datetime import datetime, timezone, timedelta

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        sources = db.query(SourceConfig).filter(
            SourceConfig.is_active == True,
            SourceConfig.schedule_enabled == True,
        ).all()

        logger.info(f"Collection check: {len(sources)} active sources")

        for source in sources:
            # 退避策略: 连续失败次数越多, 间隔越长
            if source.last_collected_at:
                interval = source.schedule_interval
                if source.consecutive_failures > 0:
                    interval = min(interval * (2 ** source.consecutive_failures), 7200)
                last = source.last_collected_at.replace(tzinfo=timezone.utc) if source.last_collected_at.tzinfo is None else source.last_collected_at
                if now < last + timedelta(seconds=interval):
                    continue

            try:
                # ---- 第一阶段: Collector 抓取, 产出 ContentItem ----
                from app.services.collectors import collect_source
                new_items = await collect_source(source, db)

                source.last_collected_at = now
                source.consecutive_failures = 0

                # ---- 第二阶段: 对每条新内容触发流水线 ----
                orchestrator = PipelineOrchestrator(db)
                for item in new_items:
                    try:
                        execution = orchestrator.trigger_for_content(
                            content=item,
                            trigger=TriggerSource.SCHEDULED,
                        )
                        if execution:
                            await orchestrator.async_start_execution(execution.id)
                            logger.info(
                                f"Pipeline triggered: {item.title} → {execution.template_name}"
                            )
                    except Exception as pe:
                        db.rollback()
                        logger.error(f"Pipeline trigger failed for {item.title[:50]}: {pe}")

                db.commit()
                logger.info(f"Collected {source.name}: {len(new_items)} new items")

            except Exception as e:
                db.rollback()
                source.consecutive_failures += 1
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.error(f"Failed to update failure count for {source.name}")

                import httpx
                from sqlalchemy.exc import OperationalError
                if isinstance(e, OperationalError):
                    logger.warning(f"Database contention for {source.name}: {e}")
                elif isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)):
                    logger.warning(f"Collection transient error for {source.name}: {type(e).__name__}: {str(e) or repr(e)}")
                else:
                    logger.error(f"Collection failed for {source.name}: {e}")

        # ---- 补偿: 对 pending 且无 pipeline 的内容补触发 ----
        from app.models.pipeline import PipelineExecution
        from sqlalchemy import not_, exists

        orphaned = db.query(ContentItem).filter(
            ContentItem.status == ContentStatus.PENDING.value,
            ~exists().where(PipelineExecution.content_id == ContentItem.id),
        ).all()

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


@proc_app.periodic(cron="0 3 * * *")
@proc_app.task(queue="scheduled", queueing_lock="cleanup_content")
async def trigger_cleanup_content(timestamp):
    """内容清理 — 每天 03:00"""
    await cleanup_expired_content()


@proc_app.periodic(cron="30 3 * * *")
@proc_app.task(queue="scheduled", queueing_lock="cleanup_records")
async def trigger_cleanup_records(timestamp):
    """记录清理 — 每天 03:30"""
    await cleanup_records()


async def cleanup_expired_content():
    """定时清理过期内容

    逻辑:
    1. 读取全局默认 default_retention_days
    2. 遍历所有 auto_cleanup_enabled=True 的数据源
    3. 删除超过保留期且未收藏、无笔记的内容（级联删除关联数据+媒体文件）
    """
    import shutil
    from pathlib import Path
    from datetime import datetime, timezone, timedelta
    from app.core.database import SessionLocal
    from app.core.config import settings
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

        sources = db.query(SourceConfig).filter(
            SourceConfig.auto_cleanup_enabled == True,
        ).all()

        if not sources:
            logger.info("Cleanup: no sources with auto_cleanup_enabled")
            return

        now = datetime.now(timezone.utc)
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
    from datetime import datetime, timezone, timedelta
    from app.core.database import SessionLocal
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

        now = datetime.now(timezone.utc)
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

        # ---- 采集记录清理 ----
        coll_terminal = ["completed", "failed"]

        # 按天数清理
        if coll_retention_days > 0:
            cutoff = now - timedelta(days=coll_retention_days)
            deleted = db.query(CollectionRecord).filter(
                CollectionRecord.status.in_(coll_terminal),
                CollectionRecord.started_at < cutoff,
            ).delete(synchronize_session=False)
            total_coll_deleted += deleted

        # 按数量清理
        if coll_max_count > 0:
            overflow_ids = [
                cid for (cid,) in db.query(CollectionRecord.id).filter(
                    CollectionRecord.status.in_(coll_terminal),
                ).order_by(CollectionRecord.started_at.desc()).offset(coll_max_count).all()
            ]
            if overflow_ids:
                deleted = db.query(CollectionRecord).filter(
                    CollectionRecord.id.in_(overflow_ids)
                ).delete(synchronize_session=False)
                total_coll_deleted += deleted

        db.commit()
        logger.info(
            f"Records cleanup: {total_exec_deleted} executions, "
            f"{total_coll_deleted} collection records deleted"
        )
