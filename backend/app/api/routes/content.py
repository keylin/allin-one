"""Content API - 内容管理"""

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, noload
from sqlalchemy import func

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.core.timezone_utils import get_local_day_boundaries
from app.models.content import SourceConfig, ContentItem, MediaItem
from app.models.pipeline import PipelineExecution, PipelineStep
from app.schemas import (
    ContentResponse, ContentDetailResponse, ContentNoteUpdate, ContentBatchDelete,
    MediaItemSummary, error_response,
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


def _build_media_summaries(media_items) -> list[dict]:
    """构建媒体项轻量摘要列表"""
    summaries = []
    for mi in media_items:
        thumbnail = None
        if mi.metadata_json:
            try:
                meta = json.loads(mi.metadata_json)
                thumbnail = meta.get("thumbnail_path")
            except (json.JSONDecodeError, TypeError):
                pass
        summaries.append(MediaItemSummary(
            id=mi.id,
            media_type=mi.media_type,
            local_path=mi.local_path,
            thumbnail_path=thumbnail,
            status=mi.status,
        ).model_dump())
    return summaries


def _content_to_response(item: ContentItem, db: Session) -> dict:
    """将 ORM 对象转为响应 dict，解析 source_name 和摘要字段"""
    data = ContentResponse.model_validate(item).model_dump(exclude={"media_items"})
    source = db.get(SourceConfig, item.source_id)
    data["source_name"] = source.name if source else None
    data.update(_extract_summary_fields(item))
    data["media_items"] = _build_media_summaries(item.media_items)
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
    has_video: bool | None = Query(None, description="筛选包含视频的内容"),
    q: str | None = Query(None, description="搜索标题"),
    is_favorited: bool | None = Query(None),
    is_unread: bool | None = Query(None, description="未读过滤: true=未读, false=已读"),
    date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    date_to: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    sort_by: str | None = Query(None, description="排序字段: collected_at / published_at / updated_at / title"),
    sort_order: str | None = Query(None, description="排序方向: desc / asc"),
    db: Session = Depends(get_db),
):
    """分页查询内容列表"""
    query = db.query(ContentItem)

    if source_id:
        ids = [s.strip() for s in source_id.split(",") if s.strip()]
        if len(ids) == 1:
            query = query.filter(ContentItem.source_id == ids[0])
        elif ids:
            query = query.filter(ContentItem.source_id.in_(ids))
    if status:
        query = query.filter(ContentItem.status == status)
    if has_video:
        query = query.filter(
            ContentItem.media_items.any(MediaItem.media_type == "video")
        )
    if q:
        pattern = f"%{q}%"
        query = query.filter(ContentItem.title.ilike(pattern))
    if is_favorited is not None:
        query = query.filter(ContentItem.is_favorited == is_favorited)
    if is_unread is not None:
        if is_unread:
            query = query.filter((ContentItem.view_count == 0) | (ContentItem.view_count.is_(None)))
        else:
            query = query.filter(ContentItem.view_count > 0)

    if date_from:
        try:
            dt = datetime.fromisoformat(date_from).replace(tzinfo=None)
            query = query.filter(ContentItem.collected_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to).replace(
                hour=23, minute=59, second=59, tzinfo=None)
            query = query.filter(ContentItem.collected_at <= dt)
        except ValueError:
            pass

    # 排序: 白名单校验，非法值 fallback collected_at desc
    col = SORT_COLUMNS.get(sort_by, ContentItem.collected_at)
    if sort_order == 'asc':
        order_expr = col.asc().nulls_last()
    else:
        order_expr = col.desc().nulls_last()

    total = query.count()
    items = (
        query.options(noload(ContentItem.media_items))
        .order_by(order_expr)
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

    # 批量查询 media_items
    item_ids = [item.id for item in items]
    media_items_map: dict[str, list] = {iid: [] for iid in item_ids}
    if item_ids:
        all_media = db.query(MediaItem).filter(MediaItem.content_id.in_(item_ids)).all()
        for mi in all_media:
            media_items_map[mi.content_id].append(mi)

    # 组装响应
    result_list = []
    for item in items:
        data = ContentResponse.model_validate(item).model_dump(exclude={"media_items"})
        data["source_name"] = source_map.get(item.source_id)
        data.update(_extract_summary_fields(item))
        mi_list = media_items_map.get(item.id, [])
        data["media_items"] = _build_media_summaries(mi_list)
        # has_thumbnail: 存在已下载的 video MediaItem 且有 thumbnail
        data["has_thumbnail"] = any(
            mi.media_type == "video" and mi.status == "downloaded"
            for mi in mi_list
        )
        result_list.append(data)

    return {
        "code": 0,
        "data": result_list,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.post("/delete-all")
async def delete_all_content(db: Session = Depends(get_db)):
    """删除全部内容（级联删除关联流水线和媒体）"""
    total = db.query(func.count(ContentItem.id)).scalar()
    if total == 0:
        return {"code": 0, "data": {"deleted": 0}, "message": "没有内容可删除"}

    # 级联删除关联 pipeline executions 及其 steps
    execution_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.content_id.isnot(None)).all()
    ]
    if execution_ids:
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(execution_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(execution_ids)
        ).delete(synchronize_session=False)

    # 删除所有媒体和内容
    db.query(MediaItem).delete(synchronize_session=False)
    deleted = db.query(ContentItem).delete(synchronize_session=False)
    db.commit()

    # 清理磁盘文件：删除整个 media 目录后重建
    media_dir = Path(settings.MEDIA_DIR)
    if media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)
        media_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Deleted all content: {deleted} items")
    return {"code": 0, "data": {"deleted": deleted}, "message": f"已删除全部 {deleted} 条内容"}


@router.post("/batch-delete")
async def batch_delete(body: ContentBatchDelete, db: Session = Depends(get_db)):
    """批量删除内容（级联删除关联流水线）"""
    content_ids = body.ids  # 保存，后续用于删除物理文件

    # 找到关联的 pipeline_execution ids
    execution_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.content_id.in_(content_ids))
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

    # 删除关联的 MediaItem（bulk delete 不触发 ORM cascade）
    db.query(MediaItem).filter(
        MediaItem.content_id.in_(content_ids)
    ).delete(synchronize_session=False)

    deleted = (
        db.query(ContentItem)
        .filter(ContentItem.id.in_(content_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    # 清理磁盘文件
    media_base = Path(settings.MEDIA_DIR)
    for content_id in content_ids:
        # 删除 media/{content_id}/ 目录
        media_dir = media_base / content_id
        if media_dir.is_dir():
            shutil.rmtree(media_dir, ignore_errors=True)

        # 删除 media/audio/{content_id}/ 目录
        audio_dir = media_base / "audio" / content_id
        if audio_dir.is_dir():
            shutil.rmtree(audio_dir, ignore_errors=True)

    logger.info(f"Batch deleted {deleted} content items ({len(execution_ids)} pipelines)")
    return {"code": 0, "data": {"deleted": deleted}, "message": "ok"}


@router.post("/batch-read")
async def batch_mark_read(body: ContentBatchDelete, db: Session = Depends(get_db)):
    """批量标记已读"""
    updated = db.query(ContentItem).filter(
        ContentItem.id.in_(body.ids),
        (ContentItem.view_count == 0) | (ContentItem.view_count.is_(None)),
    ).update({ContentItem.view_count: 1, ContentItem.last_viewed_at: utcnow()},
             synchronize_session=False)
    db.commit()
    return {"code": 0, "data": {"updated": updated}, "message": "ok"}


@router.post("/batch-favorite")
async def batch_toggle_favorite(body: ContentBatchDelete, db: Session = Depends(get_db)):
    """批量收藏"""
    updated = db.query(ContentItem).filter(
        ContentItem.id.in_(body.ids)
    ).update({ContentItem.is_favorited: True, ContentItem.updated_at: utcnow()},
             synchronize_session=False)
    db.commit()
    return {"code": 0, "data": {"updated": updated}, "message": "ok"}


@router.get("/stats")
async def content_stats(db: Session = Depends(get_db)):
    """内容库统计：按状态分组 + 今日新增 + 已读/未读"""
    # 计算今日边界（容器时区）
    today_start, today_end = get_local_day_boundaries()

    status_rows = (
        db.query(ContentItem.status, func.count(ContentItem.id))
        .group_by(ContentItem.status).all()
    )
    status_counts = {r[0]: r[1] for r in status_rows}

    # 今日新增计数（使用时区边界）
    today_count = (
        db.query(func.count(ContentItem.id))
        .filter(
            ContentItem.collected_at >= today_start,
            ContentItem.collected_at < today_end
        )
        .scalar()
    )

    # 已读/未读统计
    unread_count = (
        db.query(func.count(ContentItem.id))
        .filter((ContentItem.view_count == 0) | (ContentItem.view_count.is_(None)))
        .scalar()
    )
    read_count = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.view_count > 0)
        .scalar()
    )

    return {
        "code": 0,
        "data": {
            "total": sum(status_counts.values()),
            "today": today_count,
            "pending": status_counts.get("pending", 0),
            "processing": status_counts.get("processing", 0),
            "ready": status_counts.get("ready", 0),
            "analyzed": status_counts.get("analyzed", 0),
            "failed": status_counts.get("failed", 0),
            "unread": unread_count,
            "read": read_count,
        },
        "message": "ok",
    }


# ---- 单个内容操作（参数路径必须在字面路径之后） ----

@router.get("/{content_id}")
async def get_content(content_id: str, db: Session = Depends(get_db)):
    """获取内容详情（含三层内容）"""
    item = db.query(ContentItem).options(
        noload(ContentItem.media_items)
    ).filter(ContentItem.id == content_id).first()

    if not item:
        return error_response(404, "Content not found")

    # 手动查询 media_items，避免 lazy loading
    media_items = db.query(MediaItem).filter(MediaItem.content_id == content_id).all()

    data = ContentDetailResponse.model_validate(item).model_dump(exclude={"media_items"})
    source = db.get(SourceConfig, item.source_id)
    data["source_name"] = source.name if source else None
    data["media_items"] = _build_media_summaries(media_items)
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

        await orchestrator.async_start_execution(execution.id)

        return {
            "code": 0,
            "data": {"pipeline_execution_id": execution.id},
            "message": "分析任务已提交",
        }
    except Exception as e:
        logger.exception(f"Analyze failed for content {content_id}")
        return error_response(500, f"分析任务创建失败: {str(e)}")


class EnrichApplyRequest(BaseModel):
    content: str
    method: str


@router.post("/{content_id}/enrich")
async def enrich_content_compare(content_id: str, db: Session = Depends(get_db)):
    """并行运行三级富化，返回对比结果（不修改内容）"""
    from app.services.enrichment import enrich_compare

    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")
    if not item.url:
        return error_response(400, "该内容没有 URL，无法富化")

    try:
        results = await enrich_compare(item.url)
        return {
            "code": 0,
            "data": {"url": item.url, "results": results},
            "message": "ok",
        }
    except Exception as e:
        logger.exception(f"Enrich compare failed for content {content_id}")
        return error_response(500, f"富化对比失败: {str(e)}")


@router.post("/{content_id}/enrich/apply")
async def apply_enrichment(content_id: str, body: EnrichApplyRequest, db: Session = Depends(get_db)):
    """应用选中的富化结果到 processed_content"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.processed_content = body.content
    item.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": {"method": body.method}, "message": "已应用富化结果"}


@router.post("/{content_id}/favorite")
async def toggle_favorite(content_id: str, db: Session = Depends(get_db)):
    """切换收藏状态"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.is_favorited = not item.is_favorited
    item.updated_at = utcnow()
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
    item.last_viewed_at = utcnow()
    db.commit()

    return {"code": 0, "data": {"view_count": item.view_count}, "message": "ok"}


@router.patch("/{content_id}/note")
async def update_note(content_id: str, body: ContentNoteUpdate, db: Session = Depends(get_db)):
    """更新用户笔记"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.user_note = body.user_note
    item.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": None, "message": "ok"}


# ---- AI 对话 ----

class ChatRequest(BaseModel):
    messages: list[dict]  # [{role: "user", content: "..."}, ...]


@router.post("/{content_id}/chat")
async def chat_with_content(content_id: str, body: ChatRequest, db: Session = Depends(get_db)):
    """与内容进行 AI 对话（SSE 流式返回）"""
    from app.services.chat_service import build_chat_context, stream_chat_response

    item = db.get(ContentItem, content_id)
    if not item:
        async def error_stream():
            yield "data: [ERROR] 内容不存在\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    source = db.get(SourceConfig, item.source_id) if item.source_id else None
    system_message = build_chat_context(item, source)

    try:
        return StreamingResponse(
            stream_chat_response(system_message, body.messages, db=db),
            media_type="text/event-stream",
        )
    except ValueError as e:
        async def config_error():
            yield f"data: [ERROR] {str(e)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(config_error(), media_type="text/event-stream")
    except Exception as e:
        logger.exception("Chat init error")
        async def init_error():
            yield f"data: [ERROR] 初始化失败: {str(e)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(init_error(), media_type="text/event-stream")
