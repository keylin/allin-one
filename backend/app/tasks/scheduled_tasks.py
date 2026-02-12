"""定时调度任务

对照脑图「任务调度」:
  定时器 → 数据抓取 (智能调度, 退避策略, 信息流抓取)
           周期任务 (内容分析, 批量报告)
  流水线 → 数据处理

核心流程:
  定时器 → CollectionService.collect(source)
         → Collector 抓取原始数据 → 去重 → 创建 ContentItem
         → 对每条新内容, 按绑定的流水线模版创建 PipelineExecution
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
                db.commit()
                import httpx
                if isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)):
                    logger.warning(f"Collection transient error for {source.name}: {e}")
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

        for step in stale_steps:
            step.status = StepStatus.PENDING.value
            step.started_at = None
            step.error_message = None
            execution = db.get(PipelineExecution, step.pipeline_id)
            if execution and execution.status == PipelineStatus.RUNNING.value:
                logger.info(f"Recovering stale step: {step.step_type} (pipeline={step.pipeline_id[:12]})")
                db.commit()
                # 重新入队，yt-dlp 会自动从 .part 文件断点续传
                from app.tasks.pipeline_tasks import execute_pipeline_step
                execute_pipeline_step(step.pipeline_id, step.step_index)

        if stale_steps:
            db.commit()


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

    scheduler.start()
    logger.info("Scheduler started: collection loop + daily/weekly reports")


def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler stopped")
