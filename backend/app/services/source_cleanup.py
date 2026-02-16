"""数据源级联删除服务 — 从 sources route 提取"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, CollectionRecord, MediaItem
from app.models.finance import FinanceDataPoint
from app.models.pipeline import PipelineExecution, PipelineStep


def cascade_delete_source(source_ids: list[str], db: Session, cascade: bool) -> dict:
    """级联删除数据源及其关联数据

    Args:
        source_ids: 要删除的 source ID 列表
        db: 数据库会话
        cascade: True=删除关联内容, False=保留关联内容（断开关联）

    Returns:
        {"deleted": int, "content_count": int, "content_deleted": bool}
    """
    content_count = db.query(func.count(ContentItem.id)).filter(
        ContentItem.source_id.in_(source_ids)
    ).scalar()

    if cascade and content_count > 0:
        # 级联删除关联数据
        content_ids = [
            cid for (cid,) in db.query(ContentItem.id)
            .filter(ContentItem.source_id.in_(source_ids)).all()
        ]
        execution_ids = [
            eid for (eid,) in db.query(PipelineExecution.id)
            .filter(PipelineExecution.content_id.in_(content_ids)).all()
        ]
        if execution_ids:
            db.query(PipelineStep).filter(
                PipelineStep.pipeline_id.in_(execution_ids)
            ).delete(synchronize_session=False)
            db.query(PipelineExecution).filter(
                PipelineExecution.id.in_(execution_ids)
            ).delete(synchronize_session=False)
        db.query(MediaItem).filter(
            MediaItem.content_id.in_(content_ids)
        ).delete(synchronize_session=False)
        db.query(ContentItem).filter(
            ContentItem.source_id.in_(source_ids)
        ).delete(synchronize_session=False)
    elif content_count > 0:
        # 保留内容，断开关联
        db.query(ContentItem).filter(
            ContentItem.source_id.in_(source_ids)
        ).update({"source_id": None}, synchronize_session=False)

    # 清理 CollectionRecord 和 FinanceDataPoint
    db.query(CollectionRecord).filter(
        CollectionRecord.source_id.in_(source_ids)
    ).delete(synchronize_session=False)
    db.query(FinanceDataPoint).filter(
        FinanceDataPoint.source_id.in_(source_ids)
    ).delete(synchronize_session=False)

    # 清理以 source_id 关联的 pipeline_executions
    orphan_exec_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.source_id.in_(source_ids)).all()
    ]
    if orphan_exec_ids:
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)

    deleted = db.query(SourceConfig).filter(
        SourceConfig.id.in_(source_ids)
    ).delete(synchronize_session=False)

    return {"deleted": deleted, "content_count": content_count, "content_deleted": cascade}
