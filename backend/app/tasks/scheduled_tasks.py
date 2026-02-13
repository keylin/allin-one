"""定时调度任务

对照脑图「任务调度」:
  定时器 → 数据抓取 (智能调度, 退避策略, 信息流抓取)
           周期任务 (内容分析, 批量报告)
  流水线 → 数据处理

核心流程:
  定时器 → CollectionService.collect(source)
         → Collector 抓取原始数据 → 去重 → 创建 ContentItem
         → 对每条新内容, 按绑定的流水线模板创建 PipelineExecution
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def check_and_collect_sources():
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
                            orchestrator.start_execution(execution.id)
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
                        orchestrator.start_execution(execution.id)
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
            for pipeline_id, step_index in steps_to_requeue:
                execute_pipeline_step(pipeline_id, step_index)


async def cleanup_expired_content():
    """定时清理过期内容 — 凌晨 03:00 执行

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
    from app.models.content import SourceConfig, ContentItem
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

            # 级联删除: steps → executions → items（复用 batch_delete 模式）
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


def start_scheduler():
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    from app.tasks.report_tasks import generate_daily_report, generate_weekly_report

    scheduler.add_job(
        check_and_collect_sources,
        IntervalTrigger(minutes=5),
        id="main_collection_loop",
        replace_existing=True,
    )

    # 日报 — 每天 22:00
    scheduler.add_job(
        generate_daily_report,
        CronTrigger(hour=22, minute=0),
        id="daily_report",
        replace_existing=True,
    )

    # 周报 — 每周一 09:00
    scheduler.add_job(
        generate_weekly_report,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_report",
        replace_existing=True,
    )

    # 内容清理 — 每天 03:00
    scheduler.add_job(
        cleanup_expired_content,
        CronTrigger(hour=3, minute=0),
        id="cleanup_expired_content",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: collection loop + daily/weekly reports + content cleanup")


def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler stopped")
