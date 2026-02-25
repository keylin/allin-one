"""同步管理 API — 统一查询所有 sync 插件状态"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import ContentItem, SourceConfig
from app.models.ebook import BookAnnotation
from app.schemas.sync import SyncPluginStatus, SyncStatusResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# 插件注册表
SYNC_PLUGINS = [
    {
        "source_type": "sync.apple_books",
        "name": "Apple Books",
        "category": "ebook",
        "description": "从 macOS Apple Books 同步书籍与标注",
    },
    {
        "source_type": "sync.wechat_read",
        "name": "微信读书",
        "category": "ebook",
        "description": "从微信读书同步书籍与标注",
    },
    {
        "source_type": "sync.bilibili",
        "name": "Bilibili",
        "category": "video",
        "description": "从 B站同步收藏/历史/动态视频",
    },
]


@router.get("/status")
async def get_sync_status(db: Session = Depends(get_db)):
    """返回所有 sync 插件的配置状态与统计"""
    # 一次性查出所有 sync.* 源
    sync_sources = db.query(SourceConfig).filter(
        SourceConfig.source_type.like("sync.%"),
    ).all()
    source_map = {s.source_type: s for s in sync_sources}

    plugins = []
    for plugin in SYNC_PLUGINS:
        source = source_map.get(plugin["source_type"])

        if not source:
            plugins.append(SyncPluginStatus(**plugin))
            continue

        # 统计条目数
        total_items = db.query(func.count(ContentItem.id)).filter(
            ContentItem.source_id == source.id,
        ).scalar() or 0

        stats = {"total_items": total_items}

        # ebook 类额外统计标注数
        if plugin["category"] == "ebook":
            total_annotations = (
                db.query(func.count(BookAnnotation.id))
                .join(ContentItem, ContentItem.id == BookAnnotation.content_id)
                .filter(ContentItem.source_id == source.id)
                .scalar() or 0
            )
            stats["total_annotations"] = total_annotations

        last_sync = source.last_collected_at

        plugins.append(SyncPluginStatus(
            **plugin,
            configured=True,
            source_id=source.id,
            last_sync_at=last_sync.isoformat() if last_sync else None,
            stats=stats,
        ))

    return {
        "code": 0,
        "data": SyncStatusResponse(plugins=plugins).model_dump(),
        "message": "ok",
    }
