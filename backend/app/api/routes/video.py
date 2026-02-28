"""Video API - 视频管理"""

import json
import logging
import os
import mimetypes
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import cast, func, Float
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import get_db
from app.core.config import settings
from app.models.pipeline import PipelineExecution, PipelineStep, PipelineTemplate, TriggerSource, StepStatus
from app.models.content import ContentItem, ContentStatus, MediaItem, SourceConfig
from pydantic import BaseModel
from app.schemas import VideoDownloadRequest, error_response

logger = logging.getLogger(__name__)
router = APIRouter()


class PlaybackProgressBody(BaseModel):
    position: int


@router.post("/download")
async def download_video(body: VideoDownloadRequest, db: Session = Depends(get_db)):
    """提交视频下载任务"""
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    url = body.url.strip()
    if not url:
        return error_response(400, "URL is required")

    # 确定 source_id: 使用指定的或找一个 user.note 类型的 source
    source_id = body.source_id
    if not source_id:
        source = db.query(SourceConfig).filter(SourceConfig.source_type == "user.note").first()
        if not source:
            # 自动创建一个 user.note 数据源
            source = SourceConfig(
                name="视频下载",
                source_type="user.note",
                description="手动提交的视频下载任务",
                schedule_enabled=False,
            )
            db.add(source)
            db.flush()
        source_id = source.id

    # 创建 ContentItem
    import hashlib
    content = ContentItem(
        source_id=source_id,
        title=f"视频下载: {url[:80]}",
        external_id=hashlib.md5(url.encode()).hexdigest(),
        url=url,
        status=ContentStatus.PROCESSING.value,
    )
    db.add(content)
    db.flush()

    # 查找"媒体下载"模板 - 只有 localize_media 步骤，不包含分析
    template = db.query(PipelineTemplate).filter(PipelineTemplate.name == "媒体下载").first()
    if not template:
        return error_response(500, "未找到媒体下载模板，请检查内置模板是否已初始化")

    orchestrator = PipelineOrchestrator(db)
    try:
        execution = orchestrator.trigger_for_content(
            content=content,
            template_override_id=template.id,
            trigger=TriggerSource.MANUAL,
        )
        if not execution:
            return error_response(500, "Pipeline 创建失败")

        await orchestrator.async_start_execution(execution.id)

        logger.info(f"Video download submitted: {url} -> pipeline={execution.id}")
        return {
            "code": 0,
            "data": {
                "content_id": content.id,
                "pipeline_execution_id": execution.id,
            },
            "message": "视频下载任务已提交",
        }
    except Exception as e:
        logger.exception(f"Video download failed for {url}")
        return error_response(500, f"任务创建失败: {str(e)}")


@router.get("/downloads")
async def list_downloads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query("completed", alias="status", description="筛选状态: pending/completed/failed，空字符串=全部"),
    platform: Optional[str] = Query(None, description="筛选平台: bilibili/youtube 等"),
    source_id: Optional[str] = Query(None, description="按来源筛选"),
    search: Optional[str] = Query(None, description="搜索标题关键词"),
    sort_by: str = Query("created_at", description="排序字段: created_at/published_at/collected_at/title/duration"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    db: Session = Depends(get_db),
):
    """获取视频下载记录（支持筛选、搜索、排序）

    基于 MediaItem 表查询（media_type=video），JOIN ContentItem 获取元数据。
    """
    from sqlalchemy import asc, desc

    # MediaItem.metadata_json 是 Text 列存储 JSON，cast 为 JSONB 用于 PG JSONB 操作符
    media_meta = cast(MediaItem.metadata_json, JSONB)

    # 去重：同一 URL 可能被多次采集为不同 ContentItem，只保留最新的一条
    dedup_content = (
        db.query(ContentItem.id)
        .distinct(ContentItem.url)
        .order_by(ContentItem.url, ContentItem.created_at.desc())
        .subquery()
    )

    # 基础查询：MediaItem (video) JOIN ContentItem 和 SourceConfig
    query = (
        db.query(MediaItem, ContentItem, SourceConfig)
        .join(ContentItem, MediaItem.content_id == ContentItem.id)
        .outerjoin(SourceConfig, ContentItem.source_id == SourceConfig.id)
        .filter(MediaItem.media_type == "video")
        .filter(ContentItem.id.in_(db.query(dedup_content.c.id)))
    )

    # 状态筛选：前端 "completed" 映射到 MediaItem.status "downloaded"
    if status_filter:
        status_map = {"completed": "downloaded", "failed": "failed", "pending": "pending"}
        media_status = status_map.get(status_filter, status_filter)
        query = query.filter(MediaItem.status == media_status)

    # 来源筛选
    if source_id:
        query = query.filter(ContentItem.source_id == source_id)

    # 平台筛选
    if platform:
        query = query.filter(media_meta["platform"].astext == platform)

    # 关键词搜索
    if search:
        query = query.filter(ContentItem.title.ilike(f"%{search}%"))

    # 获取平台列表（独立轻量查询）
    platforms_query = (
        db.query(cast(MediaItem.metadata_json, JSONB)["platform"].astext)
        .filter(MediaItem.media_type == "video", MediaItem.metadata_json.isnot(None))
        .distinct()
        .all()
    )
    platforms_set = sorted(p for (p,) in platforms_query if p)

    # 计算总数
    total = query.count()

    # 排序
    sort_map = {
        "published_at": ContentItem.published_at,
        "collected_at": ContentItem.collected_at,
        "title": ContentItem.title,
        "duration": cast(media_meta["duration"].astext, Float),
    }
    sort_column = sort_map.get(sort_by, MediaItem.created_at)
    if sort_order == "desc":
        order_expr = desc(sort_column).nulls_last()
    else:
        order_expr = asc(sort_column).nulls_last()
    query = query.order_by(order_expr)

    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)

    # 构建响应
    data = []
    for media, content, source in query.all():
        meta = {}
        if media.metadata_json:
            try:
                meta = json.loads(media.metadata_json)
            except (json.JSONDecodeError, TypeError):
                pass

        # 映射 MediaItem.status 回前端状态
        display_status = "completed" if media.status == "downloaded" else media.status

        video_info = {
            "title": content.title or "",
            "duration": meta.get("duration"),
            "platform": meta.get("platform", ""),
            "file_path": media.local_path or "",
            "has_thumbnail": bool(meta.get("thumbnail_path")),
            "width": meta.get("width"),
            "height": meta.get("height"),
        }

        data.append({
            "id": media.id,
            "content_id": content.id,
            "source_id": content.source_id,
            "source_name": source.name if source else None,
            "status": display_status,
            "error_message": meta.get("error") if media.status == "failed" else None,
            "created_at": media.created_at.isoformat() if media.created_at else None,
            "published_at": content.published_at.isoformat() if content.published_at else None,
            "collected_at": content.collected_at.isoformat() if content.collected_at else None,
            "video_info": video_info,
            "content_url": content.url,
            "playback_position": media.playback_position or 0,
            "last_played_at": media.last_played_at.isoformat() if media.last_played_at else None,
            "is_favorited": content.is_favorited or False,
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


@router.put("/{content_id}/progress")
async def save_playback_progress(
    content_id: str,
    body: PlaybackProgressBody,
    db: Session = Depends(get_db),
):
    """保存视频播放进度"""
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
async def delete_video(content_id: str, db: Session = Depends(get_db)):
    """删除视频：级联删除 pipeline 记录 + 磁盘文件"""
    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "视频不存在")

    # 级联删除: steps → executions → content
    execution_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
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

    db.query(ContentItem).filter(ContentItem.id == content_id).delete(synchronize_session=False)
    db.commit()

    # 清理磁盘文件
    media_dir = Path(settings.MEDIA_DIR) / content_id
    if media_dir.is_dir():
        shutil.rmtree(media_dir, ignore_errors=True)

    audio_dir = Path(settings.MEDIA_DIR) / "audio" / content_id
    if audio_dir.is_dir():
        shutil.rmtree(audio_dir, ignore_errors=True)

    logger.info(f"Deleted video content_id={content_id} ({len(execution_ids)} executions)")
    return {"code": 0, "data": {"deleted": 1}, "message": "ok"}


@router.get("/{content_id}/thumbnail")
async def get_thumbnail(content_id: str, db: Session = Depends(get_db)):
    """获取视频封面图"""
    from fastapi.responses import FileResponse

    thumbnail_path = _get_thumbnail_path(content_id, db)
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="封面未找到")

    mime_type, _ = mimetypes.guess_type(thumbnail_path)
    return FileResponse(thumbnail_path, media_type=mime_type or "image/jpeg")


@router.get("/{content_id}/stream")
async def stream_video(
    content_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """视频流式传输（支持 Range 请求）"""
    # 查找视频文件路径
    video_path = _get_video_path(content_id, db)
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="视频文件未找到"
        )

    file_size = os.path.getsize(video_path)

    # 获取文件 MIME 类型
    mime_type, _ = mimetypes.guess_type(video_path)
    if not mime_type:
        mime_type = "video/mp4"

    # 处理 Range 请求（用于视频 seek）
    range_header = request.headers.get("range")

    if range_header:
        # 解析 Range 头 (例如: "bytes=0-1023", "bytes=-500")
        range_match = range_header.replace("bytes=", "").split("-")
        if not range_match[0]:
            # 后缀范围: "bytes=-500" 表示最后 500 字节
            suffix_len = int(range_match[1]) if len(range_match) > 1 and range_match[1] else 0
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(range_match[0])
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1

        # 确保范围有效
        start = max(0, start)
        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def iter_file():
            """生成文件块"""
            with open(video_path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    read_size = min(8192, remaining)
                    data = f.read(read_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            "Content-Type": mime_type,
        }

        return StreamingResponse(
            iter_file(),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=headers,
        )

    # 完整文件传输
    def iter_full_file():
        """生成完整文件"""
        with open(video_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": mime_type,
    }

    return StreamingResponse(
        iter_full_file(),
        headers=headers,
    )


def _get_video_path(content_id: str, db: Session) -> Optional[str]:
    """获取视频文件路径 — 从 MediaItem 或 PipelineStep 输出"""
    # 1. 优先从 MediaItem 查找
    media_item = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "video",
        MediaItem.status == "downloaded",
    ).first()
    if media_item and media_item.local_path and os.path.exists(media_item.local_path):
        return media_item.local_path

    # 2. 回退: PipelineStep (localize_media) 输出
    step = (
        db.query(PipelineStep)
        .join(PipelineExecution, PipelineStep.pipeline_id == PipelineExecution.id)
        .filter(
            PipelineExecution.content_id == content_id,
            PipelineStep.step_type == "localize_media",
            PipelineStep.status == StepStatus.COMPLETED.value,
        )
        .first()
    )
    if step and step.output_data:
        try:
            output = json.loads(step.output_data)
            file_path = output.get("file_path")
            if file_path and os.path.exists(file_path):
                return file_path
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. 兜底：尝试在 MEDIA_DIR/content_id/ 目录下查找视频文件
    content_dir = os.path.join(settings.MEDIA_DIR, content_id)
    if os.path.isdir(content_dir):
        for file in os.listdir(content_dir):
            if file.endswith((".mp4", ".webm", ".mkv")):
                return os.path.join(content_dir, file)

    return None


def _get_thumbnail_path(content_id: str, db: Session) -> Optional[str]:
    """获取视频封面路径 — 从 MediaItem metadata 或 PipelineStep 输出"""
    # 1. 优先从 MediaItem metadata 查找
    media_item = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "video",
    ).first()
    if media_item and media_item.metadata_json:
        try:
            meta = json.loads(media_item.metadata_json)
            path = meta.get("thumbnail_path")
            if path and os.path.exists(path):
                return path
        except (json.JSONDecodeError, TypeError):
            pass

    # 2. 回退: PipelineStep 输出
    step = (
        db.query(PipelineStep)
        .join(PipelineExecution, PipelineStep.pipeline_id == PipelineExecution.id)
        .filter(
            PipelineExecution.content_id == content_id,
            PipelineStep.step_type == "localize_media",
            PipelineStep.status == StepStatus.COMPLETED.value,
        )
        .first()
    )
    if step and step.output_data:
        try:
            output = json.loads(step.output_data)
            path = output.get("thumbnail_path")
            if path and os.path.exists(path):
                return path
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. 兜底：在 MEDIA_DIR/content_id/ 目录下查找图片文件
    content_dir = os.path.join(settings.MEDIA_DIR, content_id)
    if os.path.isdir(content_dir):
        for file in os.listdir(content_dir):
            if file.endswith((".jpg", ".jpeg", ".png", ".webp")):
                return os.path.join(content_dir, file)

    return None
