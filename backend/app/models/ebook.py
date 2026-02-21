"""电子书阅读器模型 — 阅读进度、批注、书签"""

import uuid

from sqlalchemy import Column, String, DateTime, Text, Integer, Float, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import utcnow


def _uuid():
    return uuid.uuid4().hex


class ReadingProgress(Base):
    """阅读进度 — 每本书一条记录"""
    __tablename__ = "reading_progress"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)

    # 定位
    cfi = Column(Text, nullable=True)                  # EPUB CFI 精确位置
    progress = Column(Float, default=0)                # 阅读百分比 0.0~1.0
    section_index = Column(Integer, default=0)         # 当前章节序号
    section_title = Column(String, nullable=True)      # 当前章节标题

    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    created_at = Column(DateTime, default=utcnow)

    content = relationship("ContentItem")

    __table_args__ = (
        Index("uq_reading_progress_content", "content_id", unique=True),
    )


class BookAnnotation(Base):
    """批注/高亮"""
    __tablename__ = "book_annotations"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)

    # 定位
    cfi_range = Column(Text, nullable=False)           # CFI 范围
    section_index = Column(Integer, nullable=True)

    # 内容
    type = Column(String, default="highlight")         # highlight / note
    color = Column(String, default="yellow")           # yellow / green / blue / pink / purple
    selected_text = Column(Text, nullable=True)        # 选中的原文
    note = Column(Text, nullable=True)                 # 用户批注

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    content = relationship("ContentItem")

    __table_args__ = (
        Index("ix_annotation_content", "content_id"),
    )


class BookBookmark(Base):
    """书签"""
    __tablename__ = "book_bookmarks"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)

    cfi = Column(Text, nullable=False)                 # CFI 位置
    title = Column(String, nullable=True)              # 书签标题
    section_title = Column(String, nullable=True)      # 所在章节标题

    created_at = Column(DateTime, default=utcnow)

    content = relationship("ContentItem")

    __table_args__ = (
        Index("ix_bookmark_content", "content_id"),
    )
