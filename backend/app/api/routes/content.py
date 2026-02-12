"""Content API - 内容管理"""

import json
import logging
import re
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


def _extract_summary_fields(item: ContentItem) -> dict:
    """从 analysis_result / raw_data 提取摘要、标签、情感"""
    result = {"summary_text": None, "tags": None, "sentiment": None}

    if item.analysis_result:
        try:
            parsed = json.loads(item.analysis_result)
            if isinstance(parsed, dict):
                summary = parsed.get("summary") or parsed.get("content", "")
                result["summary_text"] = summary[:200] if summary else None
                result["tags"] = parsed.get("tags")
                result["sentiment"] = parsed.get("sentiment")
        except (json.JSONDecodeError, TypeError):
            result["summary_text"] = str(item.analysis_result)[:200]

    # Fallback: 从 raw_data 提取（summary → description → content[0].value）
    if not result["summary_text"] and item.raw_data:
        try:
            raw = json.loads(item.raw_data)
            if isinstance(raw, dict):
                fallback = raw.get("summary") or raw.get("description", "")
                # 再回退到 RSS content 数组
                if not fallback:
                    raw_content = raw.get("content")
                    if isinstance(raw_content, list) and raw_content:
                        first = raw_content[0]
                        if isinstance(first, dict):
                            fallback = first.get("value", "")
                        elif isinstance(first, str):
                            fallback = first
                fallback = re.sub(r'<[^>]+>', '', str(fallback)).strip()
                result["summary_text"] = fallback[:200] if fallback else None
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _content_to_response(item: ContentItem, db: Session) -> dict:
    """将 ORM 对象转为响应 dict，解析 source_name 和摘要字段"""
    data = ContentResponse.model_validate(item).model_dump()
    source = db.get(SourceConfig, item.source_id)
    data["source_name"] = source.name if source else None
    data.update(_extract_summary_fields(item))
    return data


# ---- CRUD ----

SORT_COLUMNS = {
    'collected_at': ContentItem.collected_at,
    'published_at': ContentItem.published_at,
    'updated_at': ContentItem.updated_at,
    'title': ContentItem.title,
    'view_count': ContentItem.view_count,
    'last_viewed_at': ContentItem.last_viewed_at,
}


@router.get("")
async def list_content(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: str | None = Query(None),
    status: str | None = Query(None),
    media_type: str | None = Query(None),
    q: str | None = Query(None, description="搜索标题"),
    is_favorited: bool | None = Query(None),
    sort_by: str | None = Query(None, description="排序字段: collected_at / published_at / updated_at / title"),
    sort_order: str | None = Query(None, description="排序方向: desc / asc"),
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
    if is_favorited is not None:
        query = query.filter(ContentItem.is_favorited == is_favorited)

    # 排序: 白名单校验，非法值 fallback collected_at desc
    col = SORT_COLUMNS.get(sort_by, ContentItem.collected_at)
    order_expr = col.asc() if sort_order == 'asc' else col.desc()

    total = query.count()
    items = (
        query.order_by(order_expr)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 批量查询 source_name，消除 N+1
    source_ids = list({item.source_id for item in items if item.source_id})
    source_map = {}
    if source_ids:
        sources = db.query(SourceConfig.id, SourceConfig.name).filter(
            SourceConfig.id.in_(source_ids)
        ).all()
        source_map = {s.id: s.name for s in sources}

    # 批量查询 has_thumbnail：video 类型且有已完成的 download_video 步骤
    video_item_ids = [item.id for item in items if item.media_type == "video"]
    thumbnail_set = set()
    if video_item_ids:
        thumb_rows = (
            db.query(PipelineExecution.content_id)
            .join(PipelineStep, PipelineStep.pipeline_id == PipelineExecution.id)
            .filter(
                PipelineExecution.content_id.in_(video_item_ids),
                PipelineStep.step_type == "download_video",
                PipelineStep.status == "completed",
            )
            .distinct()
            .all()
        )
        thumbnail_set = {row[0] for row in thumb_rows}

    # 组装响应
    result_list = []
    for item in items:
        data = ContentResponse.model_validate(item).model_dump()
        data["source_name"] = source_map.get(item.source_id)
        data.update(_extract_summary_fields(item))
        data["has_thumbnail"] = item.id in thumbnail_set
        result_list.append(data)

    return {
        "code": 0,
        "data": result_list,
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


@router.post("/{content_id}/view")
async def record_view(content_id: str, db: Session = Depends(get_db)):
    """记录查看次数 (view_count += 1)"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.view_count = (item.view_count or 0) + 1
    item.last_viewed_at = datetime.now(timezone.utc)
    db.commit()

    return {"code": 0, "data": {"view_count": item.view_count}, "message": "ok"}


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
