"""Content API - 内容管理"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.content import SourceConfig, ContentItem
from app.models.pipeline import PipelineExecution, PipelineStep
from app.schemas import (
    ContentResponse, ContentDetailResponse, ContentNoteUpdate, ContentBatchDelete, error_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _content_to_response(item: ContentItem, db: Session) -> dict:
    """将 ORM 对象转为响应 dict，解析 source_name"""
    data = ContentResponse.model_validate(item).model_dump()
    source = db.get(SourceConfig, item.source_id)
    data["source_name"] = source.name if source else None
    return data


# ---- CRUD ----

@router.get("")
async def list_content(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: str | None = Query(None),
    status: str | None = Query(None),
    media_type: str | None = Query(None),
    q: str | None = Query(None, description="搜索标题"),
    db: Session = Depends(get_db),
):
    """分页查询内容列表"""
    query = db.query(ContentItem)

    if source_id:
        query = query.filter(ContentItem.source_id == source_id)
    if status:
        query = query.filter(ContentItem.status == status)
    if media_type:
        query = query.filter(ContentItem.media_type == media_type)
    if q:
        pattern = f"%{q}%"
        query = query.filter(ContentItem.title.ilike(pattern))

    total = query.count()
    items = (
        query.order_by(ContentItem.collected_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "code": 0,
        "data": [_content_to_response(item, db) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.post("/batch-delete")
async def batch_delete(body: ContentBatchDelete, db: Session = Depends(get_db)):
    """批量删除内容（级联删除关联流水线）"""
    # 找到关联的 pipeline_execution ids
    execution_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.content_id.in_(body.ids))
        .all()
    ]
    if execution_ids:
        # 先删 pipeline_steps，再删 pipeline_executions
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(execution_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(execution_ids)
        ).delete(synchronize_session=False)

    deleted = (
        db.query(ContentItem)
        .filter(ContentItem.id.in_(body.ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    logger.info(f"Batch deleted {deleted} content items ({len(execution_ids)} pipelines)")
    return {"code": 0, "data": {"deleted": deleted}, "message": "ok"}


# ---- 单个内容操作（参数路径必须在字面路径之后） ----

@router.get("/{content_id}")
async def get_content(content_id: str, db: Session = Depends(get_db)):
    """获取内容详情（含三层内容）"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    data = ContentDetailResponse.model_validate(item).model_dump()
    source = db.get(SourceConfig, item.source_id)
    data["source_name"] = source.name if source else None
    return {"code": 0, "data": data, "message": "ok"}


@router.post("/{content_id}/analyze")
async def analyze_content(content_id: str, db: Session = Depends(get_db)):
    """手动触发 LLM 分析"""
    from app.models.content import ContentStatus
    from app.models.pipeline import PipelineTemplate, TriggerSource
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    orchestrator = PipelineOrchestrator(db)

    # 确定模板: 源绑定模板 > "仅分析" 内置模板
    template_id = None
    source = db.get(SourceConfig, item.source_id) if item.source_id else None
    if source and source.pipeline_template_id:
        template_id = source.pipeline_template_id
    else:
        fallback = db.query(PipelineTemplate).filter(PipelineTemplate.name == "仅分析").first()
        if fallback:
            template_id = fallback.id

    try:
        execution = orchestrator.trigger_for_content(
            content=item,
            template_override_id=template_id,
            trigger=TriggerSource.MANUAL,
        )
        if not execution:
            return error_response(400, "无法创建分析任务，请检查数据源是否绑定了流水线模板")

        item.status = ContentStatus.PROCESSING.value
        db.commit()

        orchestrator.start_execution(execution.id)

        return {
            "code": 0,
            "data": {"pipeline_execution_id": execution.id},
            "message": "分析任务已提交",
        }
    except Exception as e:
        logger.exception(f"Analyze failed for content {content_id}")
        return error_response(500, f"分析任务创建失败: {str(e)}")


@router.post("/{content_id}/favorite")
async def toggle_favorite(content_id: str, db: Session = Depends(get_db)):
    """切换收藏状态"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.is_favorited = not item.is_favorited
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)

    return {"code": 0, "data": {"is_favorited": item.is_favorited}, "message": "ok"}


@router.patch("/{content_id}/note")
async def update_note(content_id: str, body: ContentNoteUpdate, db: Session = Depends(get_db)):
    """更新用户笔记"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.user_note = body.user_note
    item.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"code": 0, "data": None, "message": "ok"}
