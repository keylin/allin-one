"""采集任务 — 单源异步采集

将单个数据源的采集生命周期封装为 Procrastinate 任务，
供三个入口（一键采集、单源手动采集、定时调度）统一 defer 调用。

使用 queueing_lock=f"collect_{source_id}" 防止同源重复入队。
"""

import logging

from app.tasks.procrastinate_app import proc_app

logger = logging.getLogger(__name__)


@proc_app.task(queue="scheduled")
async def collect_single_source(source_id: str, trigger: str = "scheduled", use_retry: bool = True):
    """单源采集任务 — 完整生命周期

    Args:
        source_id: 数据源 ID
        trigger: 触发方式 ("scheduled" | "manual")
        use_retry: 是否使用重试机制（定时采集=True, 手动采集=False）
    """
    from app.core.database import SessionLocal
    from app.core.time import utcnow
    from app.models.content import SourceConfig, CollectionRecord
    from app.models.pipeline import TriggerSource
    from app.services.pipeline.orchestrator import PipelineOrchestrator
    from app.services.scheduling_service import SchedulingService

    with SessionLocal() as db:
        source = db.get(SourceConfig, source_id)
        if not source or not source.is_active:
            logger.info(f"[collect_task] Source {source_id} not found or inactive, skipping")
            return

        try:
            # ---- 第一阶段: Collector 抓取, 产出 ContentItem ----
            if use_retry:
                from app.services.collectors import collect_source_with_retry
                new_items = await collect_source_with_retry(source, db)
            else:
                from app.services.collectors import collect_source
                new_items = await collect_source(source, db)

            source.last_collected_at = utcnow()
            source.consecutive_failures = 0

            # 智能调度: 更新下次采集时间
            SchedulingService.update_next_collection_time(source, db)

            # ---- 第二阶段: 对每条新内容触发流水线 ----
            trigger_source = TriggerSource.MANUAL if trigger == "manual" else TriggerSource.SCHEDULED
            orchestrator = PipelineOrchestrator(db)
            pipelines_started = 0
            for item in new_items:
                try:
                    execution = orchestrator.trigger_for_content(
                        content=item,
                        trigger=trigger_source,
                    )
                    if execution:
                        await orchestrator.async_start_execution(execution.id)
                        pipelines_started += 1
                        logger.info(
                            f"Pipeline triggered: {item.title} -> {execution.template_name}"
                        )
                except Exception as pe:
                    db.rollback()
                    logger.error(f"Pipeline trigger failed for {item.title[:50]}: {pe}")

            db.commit()
            logger.info(
                f"[collect_task] {source.name}: {len(new_items)} new items, "
                f"{pipelines_started} pipelines started (trigger={trigger})"
            )

        except Exception as e:
            db.rollback()

            # 分类错误类型
            from app.services.collectors import classify_error
            error_type = classify_error(e)

            # 生成带错误类型前缀的错误信息
            error_msg = f"[{error_type.upper()}] {str(e)[:480]}"

            # 查询最近的失败记录并更新 error_message
            latest_record = db.query(CollectionRecord).filter(
                CollectionRecord.source_id == source.id,
                CollectionRecord.status == "failed"
            ).order_by(CollectionRecord.started_at.desc()).first()

            if latest_record:
                latest_record.error_message = error_msg

            source.consecutive_failures += 1

            # 失败也更新调度时间（应用退避策略）
            try:
                SchedulingService.update_next_collection_time(source, db)
                db.commit()
            except Exception as update_err:
                db.rollback()
                logger.error(f"Failed to update schedule for {source.name}: {update_err}")

            # 根据错误类型记录日志
            import httpx
            from sqlalchemy.exc import OperationalError
            if isinstance(e, OperationalError):
                logger.warning(f"Database contention for {source.name}: {e}")
            elif isinstance(e, (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)):
                logger.warning(
                    f"Collection {error_type} error for {source.name}: "
                    f"{type(e).__name__}: {str(e) or repr(e)}"
                )
            else:
                logger.error(f"Collection {error_type} error for {source.name}: {e}")
