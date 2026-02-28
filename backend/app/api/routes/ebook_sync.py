"""电子书同步 API — 接收本地脚本推送的阅读数据（通用化，支持多平台）"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import ContentItem, SourceConfig, SourceType
from app.models.ebook import BookAnnotation
from app.schemas import error_response
from app.schemas.ebook_sync import (
    EbookSyncRequest,
    EbookSyncResponse,
    EbookSyncStatus,
)
from app.services.sync.upsert import upsert_ebooks

logger = logging.getLogger(__name__)
router = APIRouter()

# 平台名称映射（source_type value → 显示名称）
_PLATFORM_NAMES = {
    SourceType.SYNC_APPLE_BOOKS.value: "Apple Books",
    SourceType.SYNC_WECHAT_READ.value: "微信读书",
}


def _platform_name(source_type: str) -> str:
    return _PLATFORM_NAMES.get(source_type, source_type.split(".")[-1].replace("_", " ").title())


# ─── Setup ────────────────────────────────────────────────────────────────────

@router.post("/sync/setup")
async def setup_ebook_sync(
    source_type: str = Query(SourceType.SYNC_APPLE_BOOKS.value),
    db: Session = Depends(get_db),
):
    """首次设置 — 自动创建 sync.* 类型的 SourceConfig"""
    if not source_type.startswith("sync."):
        return error_response(400, "source_type 必须以 sync. 开头")

    # 校验 source_type 必须在 SourceType 枚举中
    valid_types = {e.value for e in SourceType}
    if source_type not in valid_types:
        return error_response(400, f"不支持的 source_type: {source_type}")

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

    logger.info(f"Created ebook sync source: {source.id} ({source_type})")
    return {
        "code": 0,
        "data": {"source_id": source.id},
        "message": f"{name} 同步源创建成功",
    }


# ─── Sync Status ──────────────────────────────────────────────────────────────

@router.get("/sync/status")
async def get_sync_status(
    source_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """同步状态 — 返回最后同步时间、书籍数、标注数

    - 传 source_id: 返回指定源的状态
    - 不传: 聚合所有 sync.* 源的状态
    """
    if source_id:
        source = db.get(SourceConfig, source_id)
        if not source or not source.source_type.startswith("sync."):
            return {"code": 0, "data": EbookSyncStatus().model_dump(), "message": "ok"}
        sources = [source]
    else:
        ebook_types = [
            SourceType.SYNC_APPLE_BOOKS.value,
            SourceType.SYNC_WECHAT_READ.value,
            SourceType.SYNC_KINDLE.value,
        ]
        sources = db.query(SourceConfig).filter(
            SourceConfig.source_type.in_(ebook_types),
        ).all()

    if not sources:
        return {"code": 0, "data": EbookSyncStatus().model_dump(), "message": "ok"}

    source_ids = [s.id for s in sources]

    total_books = db.query(func.count(ContentItem.id)).filter(
        ContentItem.source_id.in_(source_ids),
    ).scalar() or 0

    total_annotations = (
        db.query(func.count(BookAnnotation.id))
        .join(ContentItem, ContentItem.id == BookAnnotation.content_id)
        .filter(ContentItem.source_id.in_(source_ids))
        .scalar() or 0
    )

    # 最新同步时间 = 所有源中最晚的 last_collected_at
    last_sync = max(
        (s.last_collected_at for s in sources if s.last_collected_at),
        default=None,
    )

    first_source_id = sources[0].id

    return {
        "code": 0,
        "data": EbookSyncStatus(
            source_id=first_source_id,
            last_sync_at=last_sync.isoformat() if last_sync else None,
            total_books=total_books,
            total_annotations=total_annotations,
        ).model_dump(),
        "message": "ok",
    }


# ─── Full Sync ────────────────────────────────────────────────────────────────

@router.post("/sync")
async def sync_ebooks(
    body: EbookSyncRequest,
    db: Session = Depends(get_db),
):
    """全量/增量同步 — 接收书籍元数据、阅读进度、标注"""
    source = db.get(SourceConfig, body.source_id)
    if not source or not source.source_type.startswith("sync."):
        return error_response(404, "同步源不存在")

    # 将 Pydantic 模型转为 dict 列表
    books_dicts = [b.model_dump(by_alias=False) for b in body.books]
    stats = upsert_ebooks(db, source, books_dicts)

    platform = _platform_name(source.source_type)
    logger.info(
        f"{platform} sync completed: "
        f"{stats['new_books']} new, {stats['updated_books']} updated, "
        f"{stats['new_annotations']} new annotations, "
        f"{stats['deleted_annotations']} deleted annotations"
    )

    return {
        "code": 0,
        "data": stats,
        "message": "同步完成",
    }
