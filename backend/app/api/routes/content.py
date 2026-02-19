"""Content API - 内容管理"""

import hashlib
import json
import logging
import mimetypes
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, noload
from sqlalchemy import func, or_, and_

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.core.timezone_utils import get_local_day_boundaries
from app.models.content import SourceConfig, ContentItem, MediaItem, ContentStatus, SourceCategory, get_source_category
from app.models.pipeline import PipelineExecution, PipelineStep, PipelineTemplate, TriggerSource
from app.schemas import (
    ContentResponse, ContentDetailResponse, ContentNoteUpdate, ContentBatchDelete,
    MediaItemSummary, ContentSubmit, ContentSubmitResponse, error_response,
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


def _estimate_reading_time(item: ContentItem) -> int | None:
    """估算阅读时间（分钟），中文 300 字/分，英文 200 词/分"""
    text = item.processed_content or ""
    if not text:
        return None
    # 去除 HTML 标签
    plain = re.sub(r'<[^>]+>', '', text).strip()
    if not plain:
        return None
    # 统计中文字符数
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', plain))
    # 统计英文单词数（非中文部分）
    non_chinese = re.sub(r'[\u4e00-\u9fff]', ' ', plain)
    english_words = len(non_chinese.split())
    # 计算阅读时间
    minutes = chinese_chars / 300 + english_words / 200
    return max(1, round(minutes))


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
            original_url=mi.original_url,
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
    'favorited_at': ContentItem.favorited_at,
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
    tag: str | None = Query(None, description="按标签筛选"),
    sort_by: str | None = Query(None, description="排序字段: collected_at / published_at / updated_at / title"),
    sort_order: str | None = Query(None, description="排序方向: desc / asc"),
    cursor_id: str | None = Query(None, description="游标: 上一页最后一条的 ID，用于游标分页"),
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
    if has_video is not None:
        if has_video:
            query = query.filter(
                ContentItem.media_items.any(MediaItem.media_type == "video")
            )
        else:
            query = query.filter(
                ~ContentItem.media_items.any(MediaItem.media_type == "video")
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

    if tag:
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        # analysis_result 是 Text 列存 JSON，需 CAST 为 JSONB 才能用 JSON 操作符
        query = query.filter(
            cast(ContentItem.analysis_result, JSONB)["tags"].astext.contains(tag)
        )

    # 排序: 白名单校验，非法值 fallback collected_at desc
    col = SORT_COLUMNS.get(sort_by, ContentItem.collected_at)
    if sort_order == 'asc':
        order_expr = col.asc().nulls_last()
    else:
        order_expr = col.desc().nulls_last()

    total = query.count()

    # 游标分页 vs OFFSET 分页
    if cursor_id:
        cursor_item = db.query(col, ContentItem.id).filter(ContentItem.id == cursor_id).first()
        if cursor_item:
            cursor_val, cid = cursor_item
            if cursor_val is not None:
                # 二级排序始终 id DESC，所以同值时取 id < cid
                if sort_order == 'asc':
                    query = query.filter(
                        or_(col > cursor_val, and_(col == cursor_val, ContentItem.id < cid))
                    )
                else:
                    query = query.filter(
                        or_(col < cursor_val, and_(col == cursor_val, ContentItem.id < cid))
                    )
            else:
                # 排序字段为 NULL 的记录放在最后（nulls_last），按 id DESC 继续
                query = query.filter(col.is_(None), ContentItem.id < cid)
        items = (
            query.options(noload(ContentItem.media_items))
            .order_by(order_expr, ContentItem.id.desc())
            .limit(page_size)
            .all()
        )
    else:
        items = (
            query.options(noload(ContentItem.media_items))
            .order_by(order_expr, ContentItem.id.desc())
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
        data["reading_time_min"] = _estimate_reading_time(item)
        # audio_duration: 从 raw_data.itunes.duration 提取（播客卡片显示）
        if any(mi.media_type == "audio" for mi in mi_list) and item.raw_data:
            try:
                raw = json.loads(item.raw_data)
                data["audio_duration"] = raw.get("itunes", {}).get("duration")
            except (json.JSONDecodeError, TypeError):
                pass
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
    now = utcnow()
    updated = db.query(ContentItem).filter(
        ContentItem.id.in_(body.ids)
    ).update({ContentItem.is_favorited: True, ContentItem.favorited_at: now, ContentItem.updated_at: now},
             synchronize_session=False)
    db.commit()
    return {"code": 0, "data": {"updated": updated}, "message": "ok"}


class MarkAllReadRequest(BaseModel):
    source_id: str | None = None
    status: str | None = None
    has_video: bool | None = None
    q: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@router.post("/mark-all-read")
async def mark_all_read(body: MarkAllReadRequest, db: Session = Depends(get_db)):
    """将筛选条件下的所有未读内容标记为已读"""
    query = db.query(ContentItem).filter(
        (ContentItem.view_count == 0) | (ContentItem.view_count.is_(None))
    )

    if body.source_id:
        ids = [s.strip() for s in body.source_id.split(",") if s.strip()]
        if len(ids) == 1:
            query = query.filter(ContentItem.source_id == ids[0])
        elif ids:
            query = query.filter(ContentItem.source_id.in_(ids))
    if body.status:
        query = query.filter(ContentItem.status == body.status)
    if body.has_video is not None:
        if body.has_video:
            query = query.filter(
                ContentItem.media_items.any(MediaItem.media_type == "video")
            )
        else:
            query = query.filter(
                ~ContentItem.media_items.any(MediaItem.media_type == "video")
            )
    if body.q:
        query = query.filter(ContentItem.title.ilike(f"%{body.q}%"))
    if body.date_from:
        try:
            dt = datetime.fromisoformat(body.date_from).replace(tzinfo=None)
            query = query.filter(ContentItem.collected_at >= dt)
        except ValueError:
            pass
    if body.date_to:
        try:
            dt = datetime.fromisoformat(body.date_to).replace(
                hour=23, minute=59, second=59, tzinfo=None)
            query = query.filter(ContentItem.collected_at <= dt)
        except ValueError:
            pass

    updated = query.update(
        {ContentItem.view_count: 1, ContentItem.last_viewed_at: utcnow()},
        synchronize_session=False,
    )
    db.commit()
    return {"code": 0, "data": {"updated": updated}, "message": f"已标记 {updated} 条为已读"}


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

    # 收藏统计
    favorited_count = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.is_favorited == True)
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
            "favorited": favorited_count,
        },
        "message": "ok",
    }


# ---- 用户提交内容 ----

@router.post("/submit")
async def submit_content(body: ContentSubmit, db: Session = Depends(get_db)):
    """用户主动提交文本内容到 USER 分类数据源"""
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    # 校验源存在且为 USER 分类
    source = db.get(SourceConfig, body.source_id)
    if not source:
        return error_response(404, "数据源不存在")
    if get_source_category(source.source_type) != SourceCategory.USER:
        return error_response(400, "只能向用户数据类型的源提交内容")

    # 生成 external_id
    hash_input = f"{body.title}:{body.content or ''}:{utcnow().isoformat()}"
    external_id = hashlib.md5(hash_input.encode()).hexdigest()

    # 构建 raw_data
    raw_data = json.dumps({
        "title": body.title,
        "content": body.content,
        "url": body.url,
        "submitted_at": utcnow().isoformat(),
    }, ensure_ascii=False)

    content = ContentItem(
        source_id=source.id,
        title=body.title,
        external_id=external_id,
        url=body.url,
        raw_data=raw_data,
        processed_content=body.content,
        status=ContentStatus.PENDING.value,
    )
    db.add(content)
    db.flush()

    # 确定模板: 参数指定 > 源绑定
    template_id = body.pipeline_template_id or source.pipeline_template_id
    execution_id = None

    if template_id:
        orchestrator = PipelineOrchestrator(db)
        try:
            execution = orchestrator.trigger_for_content(
                content=content,
                template_override_id=template_id,
                trigger=TriggerSource.MANUAL,
            )
            if execution:
                content.status = ContentStatus.PROCESSING.value
                db.commit()
                await orchestrator.async_start_execution(execution.id)
                execution_id = execution.id
            else:
                db.commit()
        except Exception as e:
            db.commit()
            logger.exception(f"Submit content pipeline trigger failed: {e}")
    else:
        content.status = ContentStatus.READY.value
        db.commit()

    logger.info(f"Content submitted: {content.id} (source={source.name})")
    return {
        "code": 0,
        "data": ContentSubmitResponse(
            content_id=content.id,
            pipeline_execution_id=execution_id,
        ).model_dump(),
        "message": "内容提交成功",
    }


@router.post("/upload")
async def upload_content(
    file: UploadFile = File(...),
    source_id: str = Form(...),
    title: str = Form(None),
    pipeline_template_id: str = Form(None),
    db: Session = Depends(get_db),
):
    """用户上传文件到 file.upload 类型数据源"""
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    # 校验源存在且为 file.upload 类型
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "数据源不存在")
    if source.source_type != "file.upload":
        return error_response(400, "文件上传需要 file.upload 类型的数据源")

    # 生成 content ID 和保存路径
    content_id = uuid.uuid4().hex
    upload_dir = Path(settings.DATA_DIR) / "uploads" / content_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = file.filename or "unnamed"
    file_path = upload_dir / filename

    # 保存文件
    file_content = await file.read()
    file_path.write_bytes(file_content)
    file_size = len(file_content)

    # 确定 MIME 类型
    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"

    # 生成 external_id
    external_id = hashlib.md5(f"{filename}:{file_size}:{utcnow().isoformat()}".encode()).hexdigest()

    # 构建 raw_data
    raw_data = json.dumps({
        "file_path": str(file_path),
        "filename": filename,
        "file_size": file_size,
        "mime_type": mime_type,
    }, ensure_ascii=False)

    content = ContentItem(
        id=content_id,
        source_id=source.id,
        title=title or filename,
        external_id=external_id,
        raw_data=raw_data,
        status=ContentStatus.PENDING.value,
    )
    db.add(content)
    db.flush()

    # 创建 MediaItem (根据 MIME 前缀)
    media_type_map = {"image": "image", "video": "video", "audio": "audio"}
    media_type_prefix = mime_type.split("/")[0]
    media_type = media_type_map.get(media_type_prefix)
    if media_type:
        media_item = MediaItem(
            content_id=content_id,
            media_type=media_type,
            original_url=str(file_path),
            local_path=str(file_path),
            filename=filename,
            status="downloaded",
            metadata_json=json.dumps({
                "file_size": file_size,
                "mime_type": mime_type,
            }),
        )
        db.add(media_item)
        db.flush()

    # Pipeline 触发
    template_id = pipeline_template_id or source.pipeline_template_id
    execution_id = None

    if template_id:
        orchestrator = PipelineOrchestrator(db)
        try:
            execution = orchestrator.trigger_for_content(
                content=content,
                template_override_id=template_id,
                trigger=TriggerSource.MANUAL,
            )
            if execution:
                content.status = ContentStatus.PROCESSING.value
                db.commit()
                await orchestrator.async_start_execution(execution.id)
                execution_id = execution.id
            else:
                db.commit()
        except Exception as e:
            db.commit()
            logger.exception(f"Upload content pipeline trigger failed: {e}")
    else:
        content.status = ContentStatus.READY.value
        db.commit()

    logger.info(f"File uploaded: {content_id} ({filename}, {file_size} bytes)")
    return {
        "code": 0,
        "data": {
            **ContentSubmitResponse(
                content_id=content_id,
                pipeline_execution_id=execution_id,
            ).model_dump(),
            "file_path": str(file_path),
        },
        "message": "文件上传成功",
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
    data["reading_time_min"] = _estimate_reading_time(item)
    return {"code": 0, "data": data, "message": "ok"}


@router.post("/{content_id}/analyze")
async def analyze_content(content_id: str, db: Session = Depends(get_db)):
    """手动触发 LLM 分析"""
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
    """切换收藏状态

    收藏时根据 MediaItem 状态决定是否触发下载流水线：
    - pending: 新内容，触发下载
    - failed: 重置为 pending 后触发下载（重试失败的下载）
    - downloaded: 已成功下载，不触发（幂等）
    - 无 MediaItem: 纯文本内容，不触发
    """
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    # 切换收藏状态
    was_favorited = item.is_favorited
    item.is_favorited = not item.is_favorited
    item.favorited_at = utcnow() if item.is_favorited else None
    item.updated_at = utcnow()
    db.commit()
    db.refresh(item)

    # 收藏时触发媒体下载（通过流水线框架）
    if item.is_favorited and not was_favorited:
        # 检查各状态的 MediaItem
        pending_count = db.query(MediaItem).filter(
            MediaItem.content_id == content_id,
            MediaItem.status == "pending",
        ).count()

        failed_items = db.query(MediaItem).filter(
            MediaItem.content_id == content_id,
            MediaItem.status == "failed",
        ).all()

        downloaded_count = db.query(MediaItem).filter(
            MediaItem.content_id == content_id,
            MediaItem.status == "downloaded",
        ).count()

        # 重置失败项为 pending，准备重试
        if failed_items:
            for mi in failed_items:
                mi.status = "pending"
            db.commit()
            logger.info(f"Reset {len(failed_items)} failed MediaItems to pending for retry: {content_id}")

        # 有 pending 或 failed(已重置) 的媒体，触发流水线
        need_download_count = pending_count + len(failed_items)
        if need_download_count > 0:
            # 查找"媒体下载"内置模板
            template = db.query(PipelineTemplate).filter(
                PipelineTemplate.name == "媒体下载",
                PipelineTemplate.is_active == True,
            ).first()

            if template:
                orchestrator = PipelineOrchestrator(db)
                execution = orchestrator.trigger_for_content(
                    content=item,
                    template_override_id=template.id,
                    trigger=TriggerSource.FAVORITE,
                )
                if execution:
                    await orchestrator.async_start_execution(execution.id)
                    logger.info(f"Favorite triggered pipeline: content={content_id}, execution={execution.id}")
        elif downloaded_count > 0:
            # 已有下载完成的媒体，不触发
            logger.info(f"Content {content_id} already has downloaded media, skip pipeline")

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


# ---- 对话历史持久化 ----

class ChatHistoryUpdate(BaseModel):
    messages: list[dict]  # [{role: "user", content: "..."}, ...]


@router.get("/{content_id}/chat/history")
async def get_chat_history(content_id: str, db: Session = Depends(get_db)):
    """获取内容的对话历史"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    messages = []
    if item.chat_history:
        try:
            messages = json.loads(item.chat_history)
        except (json.JSONDecodeError, TypeError):
            messages = []

    return {"code": 0, "data": {"messages": messages}, "message": "ok"}


@router.put("/{content_id}/chat/history")
async def save_chat_history(content_id: str, body: ChatHistoryUpdate, db: Session = Depends(get_db)):
    """保存完整对话历史（全量覆盖）"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.chat_history = json.dumps(body.messages, ensure_ascii=False)
    item.updated_at = utcnow()
    db.commit()

    return {"code": 0, "data": None, "message": "ok"}


@router.delete("/{content_id}/chat/history")
async def delete_chat_history(content_id: str, db: Session = Depends(get_db)):
    """清除对话历史"""
    item = db.get(ContentItem, content_id)
    if not item:
        return error_response(404, "Content not found")

    item.chat_history = None
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
