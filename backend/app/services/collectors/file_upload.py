"""文件上传采集器 — 扫描上传目录中的新文件"""

import json
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaType
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# 支持的文件类型 → 媒体类型映射
_MEDIA_MAP = {
    ".txt": MediaType.TEXT.value,
    ".md": MediaType.TEXT.value,
    ".csv": MediaType.TEXT.value,
    ".json": MediaType.TEXT.value,
    ".html": MediaType.TEXT.value,
    ".xml": MediaType.TEXT.value,
    ".png": MediaType.IMAGE.value,
    ".jpg": MediaType.IMAGE.value,
    ".jpeg": MediaType.IMAGE.value,
    ".gif": MediaType.IMAGE.value,
    ".webp": MediaType.IMAGE.value,
    ".mp4": MediaType.VIDEO.value,
    ".mkv": MediaType.VIDEO.value,
    ".mp3": MediaType.AUDIO.value,
    ".wav": MediaType.AUDIO.value,
    ".flac": MediaType.AUDIO.value,
    ".pdf": MediaType.TEXT.value,
}


class FileUploadCollector(BaseCollector):
    """扫描上传目录，将新文件注册为 ContentItem

    config_json 格式:
    {
        "upload_dir": "data/uploads/my-source",   # 扫描目录 (可选，默认 data/uploads/<source_id>)
        "extensions": [".txt", ".md", ".pdf"],     # 允许的扩展名 (可选，默认全部)
        "read_text": true                          # 是否读取文本文件内容到 raw_data (可选)
    }
    """

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        config = json.loads(source.config_json) if source.config_json else {}

        upload_dir = config.get("upload_dir") or os.path.join(settings.DATA_DIR, "uploads", source.id)
        extensions = config.get("extensions")
        read_text = config.get("read_text", True)

        upload_path = Path(upload_dir)
        if not upload_path.exists():
            upload_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"[FileUploadCollector] Created upload dir: {upload_dir}")
            return []

        new_items = []
        for file_path in upload_path.iterdir():
            if not file_path.is_file():
                continue

            ext = file_path.suffix.lower()
            if extensions and ext not in extensions:
                continue

            # 生成外部 ID (基于文件路径和大小)
            stat = file_path.stat()
            external_id = hashlib.md5(
                f"{file_path.name}:{stat.st_size}:{stat.st_mtime}".encode()
            ).hexdigest()

            # 媒体类型
            media_type = _MEDIA_MAP.get(ext, MediaType.MIXED.value)

            # 读取文本内容
            raw_data = None
            if read_text and media_type == MediaType.TEXT.value:
                try:
                    text = file_path.read_text(encoding="utf-8", errors="replace")
                    raw_data = json.dumps({
                        "filename": file_path.name,
                        "content": text[:50000],  # 限制 50K 字符
                        "size": stat.st_size,
                    }, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"[FileUploadCollector] Failed to read {file_path}: {e}")
                    raw_data = json.dumps({"filename": file_path.name, "size": stat.st_size})
            else:
                raw_data = json.dumps({
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "path": str(file_path),
                })

            item = ContentItem(
                source_id=source.id,
                title=file_path.name[:500],
                external_id=external_id,
                url=str(file_path),
                raw_data=raw_data,
                status=ContentStatus.PENDING.value,
                media_type=media_type,
                published_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                new_items.append(item)
            except IntegrityError:
                pass  # SAVEPOINT 已自动回滚，外层事务不受影响

        if new_items:
            db.commit()

        logger.info(f"[FileUploadCollector] {source.name}: {len(new_items)} new files")
        return new_items
