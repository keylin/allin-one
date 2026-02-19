"""Audio API - 音频流式传输"""

import json
import logging
import mimetypes
import os
from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.models.content import ContentItem, MediaItem

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{content_id}/stream")
async def stream_audio(
    content_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """音频流式传输（支持 Range 请求）"""
    audio_path = _get_audio_path(content_id, db)
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="音频文件未找到",
        )

    file_size = os.path.getsize(audio_path)

    mime_type, _ = mimetypes.guess_type(audio_path)
    if not mime_type:
        mime_type = "audio/mpeg"

    range_header = request.headers.get("range")

    if range_header:
        range_match = range_header.replace("bytes=", "").split("-")
        if not range_match[0]:
            suffix_len = int(range_match[1]) if len(range_match) > 1 and range_match[1] else 0
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(range_match[0])
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1

        start = max(0, start)
        end = min(end, file_size - 1)
        chunk_size = end - start + 1

        def iter_file():
            with open(audio_path, "rb") as f:
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

    # Full file
    def iter_full_file():
        with open(audio_path, "rb") as f:
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
