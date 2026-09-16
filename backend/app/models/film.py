"""影视资料库模型 — 用户观影标记

影片本体是 ContentItem（source_type = sync.emby / user.film），元数据与 Emby 观看事实
放在 raw_data；本表只放用户主张（状态 / 评分 / 看过日期 / 标签 / 短评）。
同步永不覆盖 status_source = manual 的行，见 docs/design_film_library.md §2.5。
"""

import uuid

from sqlalchemy import Column, String, DateTime, Date, Text, SmallInteger, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import utcnow


def _uuid():
    return uuid.uuid4().hex


WATCH_STATUSES = ("unmarked", "want", "watching", "watched", "dropped")
STATUS_SOURCES = ("manual", "emby_autofill", "douban_import")


class WatchRecord(Base):
    """观影标记 — 每部影片一条"""
    __tablename__ = "watch_records"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)

    status = Column(String, nullable=False, default="unmarked")   # WATCH_STATUSES
    my_rating = Column(SmallInteger, nullable=True)                # 1~10
    watched_at = Column(Date, nullable=True)                       # 看过日期；NULL = 时间不详
    watched_precision = Column(String, nullable=True)              # day / month / year；watched_at 为空时为 NULL
    tags = Column(ARRAY(String), nullable=False, default=list)
    comment = Column(Text, nullable=True)                          # 短评；长评用 content_items.user_note
    status_source = Column(String, nullable=False, default="manual")  # STATUS_SOURCES

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    content = relationship("ContentItem")

    __table_args__ = (
        Index("uq_watch_records_content", "content_id", unique=True),
        Index("ix_watch_records_status", "status"),
    )
