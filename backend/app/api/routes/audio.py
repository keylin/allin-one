"""Audio API - 音频流式传输"""

import logging
import mimetypes
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.content import ContentItem, MediaItem

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{content_id}/stream")
async def stream_audio(
    content_id: str,
    db: Session = Depends(get_db),
):
    """音频流式传输（FileResponse 自动处理 Range/ETag/Last-Modified）"""
    audio_path = _get_audio_path(content_id, db)
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音频文件未找到",
        )

    mime_type, _ = mimetypes.guess_type(audio_path)
    return FileResponse(audio_path, media_type=mime_type or "audio/mpeg")


def _get_audio_path(content_id: str, db: Session) -> Optional[str]:
    """获取音频文件路径 — 从 MediaItem 查找"""
    # 1. MediaItem (audio, downloaded)
    media_item = db.query(MediaItem).filter(
        MediaItem.content_id == content_id,
        MediaItem.media_type == "audio",
        MediaItem.status == "downloaded",
    ).first()
    if media_item and media_item.local_path and os.path.exists(media_item.local_path):
        return media_item.local_path

    # 2. Fallback: scan MEDIA_DIR/{content_id}/audio/
    audio_dir = os.path.join(settings.MEDIA_DIR, content_id, "audio")
    if os.path.isdir(audio_dir):
        for file in os.listdir(audio_dir):
            if file.endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac")):
                return os.path.join(audio_dir, file)

    return None
