"""Media API - 统一媒体管理（列表/删除/进度/文件服务）"""

import json
import logging
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import cast, Float, asc, desc
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.content import ContentItem, MediaItem, SourceConfig
from app.models.pipeline import PipelineExecution, PipelineStep
from app.schemas import error_response

logger = logging.getLogger(__name__)
router = APIRouter()


class PlaybackProgressBody(BaseModel):
    position: int


def _extract_thumbnail_url(raw_data: Optional[str]) -> Optional[str]:
    """Extract thumbnail URL from content raw_data (RSS summary HTML)."""
    if not raw_data:
        return None
    try:
        raw = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        return None
    # Try summary HTML first — RSSHub embeds cover image as <img>
    summary = raw.get("summary", "")
    if summary:
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
        if match:
            return match.group(1)
    return None


def _media_file_url(content_id: str, local_path: Optional[str]) -> Optional[str]:
    """Compute frontend-accessible URL for a media file under MEDIA_DIR."""
    if not local_path:
        return None
    try:
        media_root = Path(settings.MEDIA_DIR).resolve()
        file_path = Path(local_path).resolve()
        rel = file_path.relative_to(media_root)  # raises ValueError if outside
        parts = rel.parts
        if len(parts) <= 1:
            return None  # file directly under MEDIA_DIR without content_id subdir
        file_part = "/".join(parts[1:])
        return f"/api/media/{content_id}/{file_part}"
    except (ValueError, TypeError):
        return None


# NOTE: /list must be defined before /{content_id}/... routes to take priority
@router.get("/list")
async def list_media(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    media_type: Optional[str] = Query(None, description="video/audio/image，空=全部"),
    status_filter: Optional[str] = Query("completed", alias="status"),
    platform: Optional[str] = Query(None, description="按平台筛选（仅 video 有效）"),
    source_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_favorited: Optional[bool] = Query(None, description="按收藏状态筛选"),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    db: Session = Depends(get_db),
):
    """统一媒体列表，支持 media_type 筛选、搜索、排序、分页。"""
    media_meta = cast(MediaItem.metadata_json, JSONB)

    # 去重：同一 URL 的多次采集只保留最新 ContentItem
    dedup_content = (
        db.query(ContentItem.id)
        .distinct(ContentItem.url)
        .order_by(ContentItem.url, ContentItem.created_at.desc())
        .subquery()
    )

    query = (
        db.query(MediaItem, ContentItem, SourceConfig)
        .join(ContentItem, MediaItem.content_id == ContentItem.id)
        .outerjoin(SourceConfig, ContentItem.source_id == SourceConfig.id)
        .filter(ContentItem.id.in_(db.query(dedup_content.c.id)))
    )

    # 白名单：媒体管理只展示 video/audio/image
    MEDIA_LIST_TYPES = ("video", "audio", "image")
    if media_type:
        query = query.filter(MediaItem.media_type == media_type)
    else:
        query = query.filter(MediaItem.media_type.in_(MEDIA_LIST_TYPES))

    if status_filter:
        status_map = {"completed": "downloaded", "failed": "failed", "pending": "pending"}
        media_status = status_map.get(status_filter, status_filter)
        query = query.filter(MediaItem.status == media_status)

    if source_id:
        query = query.filter(ContentItem.source_id == source_id)

    if platform:
        query = query.filter(media_meta["platform"].astext == platform)

    if search:
        query = query.filter(ContentItem.title.ilike(f"%{search}%"))

    if is_favorited is not None:
        query = query.filter(MediaItem.is_favorited == is_favorited)

    # 视频平台列表（独立查询）
    platforms_q = (
        db.query(cast(MediaItem.metadata_json, JSONB)["platform"].astext)
        .filter(MediaItem.media_type == "video", MediaItem.metadata_json.isnot(None))
        .distinct()
        .all()
    )
    platforms_set = sorted(p for (p,) in platforms_q if p)

    total = query.count()

    sort_map = {
        "published_at": ContentItem.published_at,
        "collected_at": ContentItem.collected_at,
        "title": ContentItem.title,
        "duration": cast(media_meta["duration"].astext, Float),
        "favorited_at": MediaItem.favorited_at,
        "last_played_at": MediaItem.last_played_at,
    }
    sort_column = sort_map.get(sort_by, MediaItem.created_at)
    order_expr = (
        desc(sort_column).nulls_last()
        if sort_order == "desc"
        else asc(sort_column).nulls_last()
    )
    query = query.order_by(order_expr).offset((page - 1) * page_size).limit(page_size)

    data = []
    for media, content, source in query.all():
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        display_status = "completed" if media.status == "downloaded" else media.status
        is_image = media.media_type == "image"

        has_local_thumbnail = bool(meta.get("thumbnail_path")) or is_image
        thumbnail_url = None if has_local_thumbnail else _extract_thumbnail_url(content.raw_data)

        media_info = {
            "title": content.title or "",
            "duration": meta.get("duration"),
            "platform": meta.get("platform", ""),
            "file_path": media.local_path or "",
            "file_url": _media_file_url(content.id, media.local_path),
            "has_thumbnail": has_local_thumbnail or bool(thumbnail_url),
            "thumbnail_url": thumbnail_url,
            "width": meta.get("width"),
            "height": meta.get("height"),
            "file_size": meta.get("file_size"),
            "alt": meta.get("alt", ""),
        }

        data.append({
            "id": media.id,
            "content_id": content.id,
            "media_type": media.media_type,
            "source_id": content.source_id,
            "source_name": source.name if source else None,
            "status": display_status,
            "error_message": meta.get("error") if media.status == "failed" else None,
            "title": content.title or "",
            "content_url": content.url,
            "created_at": media.created_at.isoformat() if media.created_at else None,
            "published_at": content.published_at.isoformat() if content.published_at else None,
            "collected_at": content.collected_at.isoformat() if content.collected_at else None,
            "playback_position": media.playback_position or 0,
            "last_played_at": media.last_played_at.isoformat() if media.last_played_at else None,
            "is_favorited": media.is_favorited or False,
            "favorited_at": media.favorited_at.isoformat() if media.favorited_at else None,
            "media_info": media_info,
        })

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "platforms": platforms_set,
        "message": "ok",
    }


@router.post("/{media_id}/favorite")
async def toggle_media_favorite(media_id: str, db: Session = Depends(get_db)):
    """切换单个 MediaItem 的收藏状态。
    收藏且 pending → 触发媒体下载流水线（只下载该 MediaItem）。
    """
    from app.core.time import utcnow
    from app.models.pipeline import PipelineTemplate, TriggerSource

    media = db.get(MediaItem, media_id)
    if not media:
        return error_response(404, "Media not found")

    was_favorited = media.is_favorited
    media.is_favorited = not media.is_favorited
    media.favorited_at = utcnow() if media.is_favorited else None
    db.commit()
    db.refresh(media)

    # 收藏且处于 pending 状态 → 触发流水线下载该 MediaItem
    if media.is_favorited and not was_favorited and media.status == "pending":
        content = db.get(ContentItem, media.content_id)
        if content:
            from app.services.pipeline.orchestrator import PipelineOrchestrator
            template = db.query(PipelineTemplate).filter(
                PipelineTemplate.name == "媒体下载",
                PipelineTemplate.is_active == True,
            ).first()
            if template:
                orchestrator = PipelineOrchestrator(db)
                execution = orchestrator.trigger_for_content(
                    content=content,
                    template_override_id=template.id,
                    trigger=TriggerSource.FAVORITE,
                )
                if execution:
                    await orchestrator.async_start_execution(execution.id)
                    logger.info(f"MediaItem favorite triggered pipeline: media={media_id}, execution={execution.id}")

    return {
        "code": 0,
        "data": {
            "is_favorited": media.is_favorited,
            "favorited_at": media.favorited_at.isoformat() if media.favorited_at else None,
        },
        "message": "ok",
    }


@router.post("/{media_id}/retry")
async def retry_media_download(media_id: str, db: Session = Depends(get_db)):
    """重试失败的媒体下载：重置状态为 pending → 触发媒体下载流水线。"""
    from app.models.pipeline import PipelineTemplate, TriggerSource
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    media = db.get(MediaItem, media_id)
    if not media:
        return error_response(404, "Media not found")

    if media.status != "failed":
        return error_response(400, "只有失败的媒体项可以重试")

    # 清除错误信息、重置状态
    if media.metadata_json:
        try:
            meta = json.loads(media.metadata_json)
            meta.pop("error", None)
            media.metadata_json = json.dumps(meta, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

    media.status = "pending"
    db.commit()
    db.refresh(media)

    # 触发媒体下载流水线
    content = db.get(ContentItem, media.content_id)
    if content:
        template = db.query(PipelineTemplate).filter(
            PipelineTemplate.name == "媒体下载",
            PipelineTemplate.is_active == True,
        ).first()
        if template:
            orchestrator = PipelineOrchestrator(db)
            execution = orchestrator.trigger_for_content(
                content=content,
                template_override_id=template.id,
                trigger=TriggerSource.MANUAL,
            )
            if execution:
                await orchestrator.async_start_execution(execution.id)
                logger.info(f"MediaItem retry triggered pipeline: media={media_id}, execution={execution.id}")

    return {"code": 0, "data": {"status": "pending"}, "message": "已重新提交下载"}


@router.put("/{content_id}/progress")
async def save_playback_progress(
    content_id: str,
    body: PlaybackProgressBody,
    db: Session = Depends(get_db),
):
    """保存播放进度（视频/音频共用）"""
    from app.core.time import utcnow

    media = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type.in_(["video", "audio"]),
    ).first()
    if not media:
        return error_response(404, "Media not found")

    media.playback_position = max(0, body.position)
    media.last_played_at = utcnow()
    db.commit()

    return {"code": 0, "data": {"playback_position": media.playback_position}, "message": "ok"}


@router.delete("/{content_id}")
async def delete_media(content_id: str, db: Session = Depends(get_db)):
    """删除媒体：级联删除 pipeline 记录 + 磁盘文件"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "媒体不存在")

    execution_ids = [
        eid
        for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.content_id == content_id)
        .all()
    ]
    if execution_ids:
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(execution_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(execution_ids)
        ).delete(synchronize_session=False)

    db.query(MediaItem).filter(MediaItem.content_id == content_id).delete(synchronize_session=False)
    db.query(ContentItem).filter(ContentItem.id == content_id).delete(synchronize_session=False)
    db.commit()

    # 清理磁盘
    media_dir = Path(settings.MEDIA_DIR) / content_id
    if media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)

    logger.info(f"Deleted media content_id={content_id} ({len(execution_ids)} executions removed)")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}


@router.get("/{content_id}/thumbnail")
async def serve_thumbnail(content_id: str, db: Session = Depends(get_db)):
    """通用缩略图：video thumbnail > 第一张 image MediaItem"""
    # 1. Video thumbnail (from metadata_json)
    video_mi = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "video",
        MediaItem.status == "downloaded",
    ).first()
    if video_mi and video_mi.metadata_json:
        try:
            meta = json.loads(video_mi.metadata_json)
            path = meta.get("thumbnail_path")
            if path and os.path.isfile(path):
                mime, _ = mimetypes.guess_type(path)
                return FileResponse(path, media_type=mime or "image/jpeg")
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. First downloaded image MediaItem
    image_mi = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "image",
        MediaItem.status == "downloaded",
    ).first()
    if image_mi and image_mi.local_path and os.path.isfile(image_mi.local_path):
        mime, _ = mimetypes.guess_type(image_mi.local_path)
        return FileResponse(image_mi.local_path, media_type=mime or "image/jpeg")

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail not found")


@router.get("/{content_id}/{file_path:path}")
async def serve_media_file(content_id: str, file_path: str):
    """从 MEDIA_DIR/{content_id}/ 读取媒体文件（路径遍历保护）"""
    media_root = Path(settings.MEDIA_DIR).resolve()
    real_path = (media_root / content_id / file_path).resolve()
    try:
        real_path.relative_to(media_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    if not real_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime_type, _ = mimetypes.guess_type(str(real_path))
    return FileResponse(str(real_path), media_type=mime_type or "application/octet-stream")
