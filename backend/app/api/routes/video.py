"""Video API - 视频管理"""

import json
import logging
import os
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.pipeline import PipelineExecution, PipelineStep, PipelineTemplate, TriggerSource, StepStatus
from app.models.content import ContentItem, ContentStatus, MediaType, SourceConfig
from app.schemas import VideoDownloadRequest, error_response

logger = logging.getLogger(__name__)
router = APIRouter()


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
    db: Session = Depends(get_db),
):
    """获取视频下载记录"""
    query = db.query(PipelineStep).filter(PipelineStep.step_type == "download_video")

    total = query.count()
    steps = (
        query.order_by(PipelineStep.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    data = []
    for step in steps:
        # 从 output_data (JSON 字符串) 中提取视频元信息
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
                }
            except (json.JSONDecodeError, TypeError):
                pass

        # 通过 pipeline 关系获取 content_id
        execution = step.pipeline
        content_id = execution.content_id if execution else None
        content = db.get(ContentItem, content_id) if content_id else None

        data.append({
            "id": step.id,
            "pipeline_id": step.pipeline_id,
            "content_id": content_id,
            "status": step.status,
            "step_config": step.step_config,
            "error_message": step.error_message,
            "started_at": step.started_at.isoformat() if step.started_at else None,
            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
            "created_at": step.created_at.isoformat() if step.created_at else None,
            "video_info": video_info,
            "content_url": content.url if content else None,
        })

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


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
