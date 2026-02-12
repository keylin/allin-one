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
                if now < source.last_collected_at + timedelta(seconds=interval):
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
                    execution = orchestrator.trigger_for_content(
                        content=item,
                        trigger=TriggerSource.SCHEDULED,
                    )
                    if execution:
                        orchestrator.start_execution(execution.id)
                        logger.info(
                            f"Pipeline triggered: {item.title} → {execution.template_name}"
                        )

                db.commit()
                logger.info(f"Collected {source.name}: {len(new_items)} new items")

            except Exception as e:
                source.consecutive_failures += 1
                db.commit()
                logger.error(f"Collection failed for {source.name}: {e}")


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
