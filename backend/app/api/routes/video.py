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

from app.core.database import get_db
from app.core.config import settings
from app.models.pipeline import PipelineExecution, PipelineStep, PipelineTemplate, TriggerSource, StepStatus
from app.models.content import ContentItem, ContentStatus, MediaType, SourceConfig
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
                media_type=MediaType.VIDEO.value,
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
        media_type=MediaType.VIDEO.value,
    )
    db.add(content)
    db.flush()

    # 查找"视频下载分析"内置模板
    template = db.query(PipelineTemplate).filter(PipelineTemplate.name == "视频下载分析").first()
    if not template:
        return error_response(500, "未找到视频下载分析模板，请检查内置模板是否已初始化")

    orchestrator = PipelineOrchestrator(db)
    try:
        execution = orchestrator.trigger_for_content(
            content=content,
            template_override_id=template.id,
            trigger=TriggerSource.MANUAL,
        )
        if not execution:
            return error_response(500, "Pipeline 创建失败")

        orchestrator.start_execution(execution.id)

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
    status_filter: Optional[str] = Query("completed", alias="status", description="筛选状态: pending/running/completed/failed，空字符串=全部"),
    platform: Optional[str] = Query(None, description="筛选平台: bilibili/youtube 等"),
    source_id: Optional[str] = Query(None, description="按来源筛选"),
    search: Optional[str] = Query(None, description="搜索标题关键词"),
    sort_by: str = Query("created_at", description="排序字段: created_at/published_at/collected_at/title/duration"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    db: Session = Depends(get_db),
):
    """获取视频下载记录（支持筛选、搜索、排序）"""
    query = db.query(PipelineStep).filter(PipelineStep.step_type == "download_video")

    # 状态筛选（在 DB 层过滤）
    if status_filter:
        query = query.filter(PipelineStep.status == status_filter)

    # 来源筛选（在 DB 层通过 join 过滤）
    if source_id:
        query = (
            query
            .join(PipelineExecution, PipelineStep.pipeline_id == PipelineExecution.id)
            .join(ContentItem, PipelineExecution.content_id == ContentItem.id)
            .filter(ContentItem.source_id == source_id)
        )

    steps = query.all()

    # 构建完整数据列表，解析 output_data 后做进一步筛选
    data = []
    platforms_set = set()
    for step in steps:
        video_info = {}
        if step.output_data:
            try:
                output = json.loads(step.output_data)
                video_info = {
                    "title": output.get("title", ""),
                    "duration": output.get("duration"),
                    "platform": output.get("platform", ""),
                    "file_path": output.get("file_path", ""),
                    "has_thumbnail": bool(output.get("thumbnail_path")),
                    "width": output.get("width"),
                    "height": output.get("height"),
                }
            except (json.JSONDecodeError, TypeError):
                pass

        execution = step.pipeline
        content_id = execution.content_id if execution else None
        content = db.get(ContentItem, content_id) if content_id else None

        item_platform = video_info.get("platform", "")
        if item_platform:
            platforms_set.add(item_platform)

        # 平台筛选
        if platform and item_platform != platform:
            continue

        # 关键词搜索
        if search and search.lower() not in (video_info.get("title") or "").lower():
            continue

        source = content.source if content else None
        data.append({
            "id": step.id,
            "pipeline_id": step.pipeline_id,
            "content_id": content_id,
            "source_id": content.source_id if content else None,
            "source_name": source.name if source else None,
            "status": step.status,
            "step_config": step.step_config,
            "error_message": step.error_message,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            "created_at": step.created_at.isoformat() if step.created_at else None,
            "published_at": content.published_at.isoformat() if content and content.published_at else None,
            "collected_at": content.collected_at.isoformat() if content and content.collected_at else None,
            "video_info": video_info,
            "content_url": content.url if content else None,
            "playback_position": content.playback_position if content else 0,
            "last_played_at": content.last_played_at.isoformat() if content and content.last_played_at else None,
        })

    # 排序
    def sort_key(item):
        if sort_by == "title":
            return (item.get("video_info") or {}).get("title") or ""
        if sort_by == "duration":
            return (item.get("video_info") or {}).get("duration") or 0
        if sort_by == "published_at":
            return item.get("published_at") or ""
        if sort_by == "collected_at":
            return item.get("collected_at") or ""
        return item.get("created_at") or ""

    data.sort(key=sort_key, reverse=(sort_order == "desc"))

    # 分页
    total = len(data)
    start = (page - 1) * page_size
    data = data[start:start + page_size]

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "platforms": sorted(platforms_set),
        "message": "ok",
    }


@router.put("/{content_id}/progress")
async def save_playback_progress(
    content_id: str,
    body: PlaybackProgressBody,
    db: Session = Depends(get_db),
):
    """保存视频播放进度"""
    from datetime import datetime, timezone

    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "Content not found")

    content.playback_position = max(0, body.position)
    content.last_played_at = datetime.now(timezone.utc)
    db.commit()

    return {"code": 0, "data": {"playback_position": content.playback_position}, "message": "ok"}


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
        # 解析 Range 头 (例如: "bytes=0-1023")
        range_match = range_header.replace("bytes=", "").split("-")
        start = int(range_match[0]) if range_match[0] else 0
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
    """获取视频文件路径"""
    # 从 PipelineStep (download_video) 的输出中获取文件路径
    step = (
        db.query(PipelineStep)
        .join(PipelineExecution, PipelineStep.pipeline_id == PipelineExecution.id)
        .filter(
            PipelineExecution.content_id == content_id,
            PipelineStep.step_type == "download_video",
            PipelineStep.status == StepStatus.COMPLETED.value,
        )
        .first()
    )

    if step and step.output_data:
        try:
            output = json.loads(step.output_data)
            file_path = output.get("file_path")
            if file_path:
                return file_path
        except (json.JSONDecodeError, TypeError):
            pass

    # 兜底：尝试在 MEDIA_DIR/content_id/ 目录下查找视频文件
    content_dir = os.path.join(settings.MEDIA_DIR, content_id)
    if os.path.isdir(content_dir):
        for file in os.listdir(content_dir):
            if file.endswith((".mp4", ".webm", ".mkv")):
                return os.path.join(content_dir, file)

    return None


def _get_thumbnail_path(content_id: str, db: Session) -> Optional[str]:
    """获取视频封面路径"""
    step = (
        db.query(PipelineStep)
        .join(PipelineExecution, PipelineStep.pipeline_id == PipelineExecution.id)
        .filter(
            PipelineExecution.content_id == content_id,
            PipelineStep.step_type == "download_video",
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

    # 兜底：在 MEDIA_DIR/content_id/ 目录下查找图片文件
    content_dir = os.path.join(settings.MEDIA_DIR, content_id)
    if os.path.isdir(content_dir):
        for file in os.listdir(content_dir):
            if file.endswith((".jpg", ".jpeg", ".png", ".webp")):
                return os.path.join(content_dir, file)

    return None
