"""数据源级联删除服务 — 从 sources route 提取"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.content import (
    SourceConfig, ContentItem, CollectionRecord, MediaItem, SourceCategory, get_source_category,
)
from app.models.finance import FinanceDataPoint
from app.models.pipeline import PipelineExecution, PipelineStep


class SourceDeleteBlocked(Exception):
    """删除被拒绝：该数据源承载用户资料，不能只删源、把内容留成无主数据"""


def _check_user_data_sources(source_ids: list[str], db: Session) -> None:
    """用户数据类数据源 (sync.* / user.* / file.*) 下有内容时，禁止非级联删除。

    这类内容的领域身份依赖所属数据源（影片靠源类型判定），source_id 置空后会从
    影视库等页面消失，观看记录变成无主数据，同一条目还能重复入库。
    见 docs/audit_2026-09_architecture.md §3-B。
    """
    rows = (
        db.query(SourceConfig.name, SourceConfig.source_type, func.count(ContentItem.id))
        .join(ContentItem, ContentItem.source_id == SourceConfig.id)
        .filter(SourceConfig.id.in_(source_ids))
        .group_by(SourceConfig.id, SourceConfig.name, SourceConfig.source_type)
        .all()
    )
    blocked = [
        f"{name}（{count} 条）" for name, source_type, count in rows
        if get_source_category(source_type) == SourceCategory.USER
    ]
    if blocked:
        raise SourceDeleteBlocked(
            "以下数据源承载用户资料，不能只删除数据源而保留内容: " + "、".join(blocked)
            + "。如确需删除，请选择同时删除关联内容"
        )


def cascade_delete_source(source_ids: list[str], db: Session, cascade: bool) -> dict:
    """级联删除数据源及其关联数据

    Args:
        source_ids: 要删除的 source ID 列表
        db: 数据库会话
        cascade: True=删除关联内容, False=保留关联内容（断开关联）

    Returns:
        {"deleted": int, "content_count": int, "content_deleted": bool}

    Raises:
        SourceDeleteBlocked: cascade=False 且目标含有内容的用户数据类数据源
    """
    if not cascade:
        _check_user_data_sources(source_ids, db)

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
    # 注: DB 级 ON DELETE CASCADE 已覆盖，此处显式删除作为额外保护
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
