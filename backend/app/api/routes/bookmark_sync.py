"""书签同步 API — 接收 Fountain 推送的 Safari / Chrome 书签"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import ContentItem, SourceConfig, SourceType
from app.schemas import error_response
from app.schemas.bookmark_sync import (
    BookmarkSyncRequest,
    BookmarkSyncResponse,
    BookmarkSyncStatus,
)
from app.services.sync.upsert import upsert_bookmarks

logger = logging.getLogger(__name__)
router = APIRouter()

_PLATFORM_NAMES = {
    SourceType.SYNC_SAFARI_BOOKMARKS.value: "Safari 书签",
    SourceType.SYNC_CHROME_BOOKMARKS.value: "Chrome 书签",
}

_VALID_BOOKMARK_TYPES = {
    SourceType.SYNC_SAFARI_BOOKMARKS.value,
    SourceType.SYNC_CHROME_BOOKMARKS.value,
}


def _platform_name(source_type: str) -> str:
    return _PLATFORM_NAMES.get(
        source_type,
        source_type.split(".")[-1].replace("_", " ").title(),
    )


# ─── Setup ────────────────────────────────────────────────────────────────────

@router.post("/sync/setup")
async def setup_bookmark_sync(
    source_type: str = Query(SourceType.SYNC_SAFARI_BOOKMARKS.value),
    db: Session = Depends(get_db),
):
    """首次设置 — 自动创建书签同步 SourceConfig"""
    if source_type not in _VALID_BOOKMARK_TYPES:
        return error_response(400, f"不支持的 source_type: {source_type}，仅支持 {sorted(_VALID_BOOKMARK_TYPES)}")

    existing = db.query(SourceConfig).filter(
        SourceConfig.source_type == source_type,
    ).first()
    if existing:
        return {
            "code": 0,
            "data": {"source_id": existing.id},
            "message": f"已存在 {_platform_name(source_type)} 同步源",
        }

    name = _platform_name(source_type)
    source = SourceConfig(
        id=uuid.uuid4().hex,
        name=name,
        source_type=source_type,
        schedule_enabled=False,
        schedule_mode="manual",
        is_active=True,
    )
    db.add(source)
    db.commit()

    logger.info(f"Created bookmark sync source: {source.id} ({source_type})")
    return {
        "code": 0,
        "data": {"source_id": source.id},
        "message": f"{name} 同步源创建成功",
    }


# ─── Sync Status ──────────────────────────────────────────────────────────────

@router.get("/sync/status")
async def get_bookmark_sync_status(
    source_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """同步状态 — 返回最后同步时间、书签总数"""
    source = db.get(SourceConfig, source_id)
    if not source or source.source_type not in _VALID_BOOKMARK_TYPES:
        return {"code": 0, "data": BookmarkSyncStatus().model_dump(), "message": "ok"}

    total_bookmarks = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.source_id == source.id)
        .scalar() or 0
    )

    last_sync = source.last_collected_at

    return {
        "code": 0,
        "data": BookmarkSyncStatus(
            source_id=source.id,
            last_sync_at=last_sync.isoformat() if last_sync else None,
            total_bookmarks=total_bookmarks,
        ).model_dump(),
        "message": "ok",
    }


# ─── Full Sync ────────────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_bookmarks(
    body: BookmarkSyncRequest,
    db: Session = Depends(get_db),
):
    """批量同步书签 — 接收 URL 列表，去重后写入"""
    source = db.get(SourceConfig, body.source_id)
    if not source or source.source_type not in _VALID_BOOKMARK_TYPES:
        return error_response(404, "书签同步源不存在")

    bookmarks_dicts = [bm.model_dump() for bm in body.bookmarks]
    stats = upsert_bookmarks(db, source, bookmarks_dicts)

    platform = _platform_name(source.source_type)
    logger.info(
        f"{platform} bookmark sync: "
        f"{stats['new_bookmarks']} new, {stats['updated_bookmarks']} updated"
    )

    return {
        "code": 0,
        "data": stats,
        "message": "同步完成",
    }
