"""影视资料库模型 — 用户观影标记

影片本体是 ContentItem（source_type = sync.emby / user.film），元数据与 Emby 观看事实
放在 raw_data。用户主张分两层：
- watch_records：片级，一部片一行（状态 / 标签 / 来源）+「最近一次观看」的缓存字段（评分 / 日期）
- watch_logs：观看级，一次观看一行（日期+精度 / 评分 / 感想）。同一部片不同阶段看感受不同，各记各的
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
    # 以下三列是「最近一次观看」(watch_logs) 的缓存，由 sync_record_from_logs 维护，列表排序/筛选用
    my_rating = Column(SmallInteger, nullable=True)                # 1~10
    watched_at = Column(Date, nullable=True)                       # 看过日期；NULL = 时间不详
    watched_precision = Column(String, nullable=True)              # day / month / year / release；watched_at 为空时为 NULL
    tags = Column(ARRAY(String), nullable=False, default=list)
    status_source = Column(String, nullable=False, default="manual")  # STATUS_SOURCES

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    content = relationship("ContentItem")
    logs = relationship("WatchLog", cascade="all, delete-orphan", order_by="WatchLog.created_at")

    __table_args__ = (
        Index("uq_watch_records_content", "content_id", unique=True),
        Index("ix_watch_records_status", "status"),
    )


class WatchLog(Base):
    """观看记录 — 一次观看一条；同一部片可以有多条（不同阶段重看）"""
    __tablename__ = "watch_logs"

    id = Column(String, primary_key=True, default=_uuid)
    record_id = Column(String, ForeignKey("watch_records.id", ondelete="CASCADE"), nullable=False)

    watched_at = Column(Date, nullable=True)          # NULL = 时间不详
    watched_precision = Column(String, nullable=True) # day / month / year / release
    my_rating = Column(SmallInteger, nullable=True)   # 这一次看的评分，1~10
    note = Column(Text, nullable=True)                # 这一次的感想，长短不限

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_watch_logs_record", "record_id"),
    )
