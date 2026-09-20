"""内容保留策略 — 「哪些内容可以被自动清理」的唯一判定处

定时清理任务 (cleanup_expired_content) 与清理预览接口共用，避免两边口径漂移。

规则:
  1. 只清理网络采集类数据源 (SourceCategory.NETWORK) 的内容。
     用户数据类数据源 (sync.* / user.* / file.*) 承载的是用户自己的资料
     （影视库、书、书签、笔记、上传文件），永不自动清理。
  2. 采集类内容中，以下任一成立即受保护:
     - 内容已收藏 (content_items.is_favorited)
     - 内容有用户笔记 (content_items.user_note)
     - 其下任一媒体项已收藏 (media_items.is_favorited)

背景: 2026-09-20 审计发现清理任务遍历全部数据源，而影片的评分/感想存在
watch_logs、不被保护条件承认，影视库会在入库 30 天后被整库级联删除。
见 docs/audit_2026-09_architecture.md §4 🔴-1。
"""

from datetime import datetime

from sqlalchemy import exists
from sqlalchemy.orm import Query, Session

from app.models.content import (
    ContentItem, MediaItem, SourceCategory, SourceConfig, get_source_category,
)


def is_auto_cleanup_eligible(source: SourceConfig) -> bool:
    """该数据源的内容是否允许被自动清理"""
    return get_source_category(source.source_type) == SourceCategory.NETWORK


def expired_content_query(db: Session, source: SourceConfig, cutoff: datetime) -> Query:
    """返回该数据源下「已过期且不受保护」的 ContentItem.id 查询

    调用方应先用 is_auto_cleanup_eligible 过滤数据源。
    """
    has_favorited_media = exists().where(
        MediaItem.content_id == ContentItem.id,
        MediaItem.is_favorited.is_(True),
    )
    return db.query(ContentItem.id).filter(
        ContentItem.source_id == source.id,
        ContentItem.collected_at < cutoff,
        ContentItem.is_favorited.isnot(True),
        ContentItem.user_note.is_(None),
        ~has_favorited_media,
    )
