"""金融数据点模型 — 列式存储替代 ContentItem.raw_data JSON"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Float, DateTime, Text, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def _uuid():
    return uuid.uuid4().hex

def _utcnow():
    """返回 naive UTC datetime，避免 PG TIMESTAMP WITHOUT TIME ZONE 的时区转换"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FinanceDataPoint(Base):
    """金融数据点

    专用表存储金融数值数据，替代 ContentItem 的 raw_data JSON 存储。
    按数据类型使用不同列: 宏观用 value, 股票用 OHLCV, 基金用 NAV。
    """
    __tablename__ = "finance_data_points"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, ForeignKey("source_configs.id"), nullable=False)

    category = Column(String, nullable=False, default="unknown")  # macro/stock/fund
    date_key = Column(String, nullable=False)  # 原始格式: "2024-01-15", "2024-01", "2024Q3"
    published_at = Column(DateTime, nullable=True)  # 解析后的标准时间，用于排序和范围查询

    # 宏观指标
    value = Column(Float, nullable=True)
    # OHLCV (股票/ETF)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    # 基金净值
    unit_nav = Column(Float, nullable=True)
    cumulative_nav = Column(Float, nullable=True)

    # 告警 + LLM 分析 (JSON)
    alert_json = Column(Text, nullable=True)
    analysis_result = Column(Text, nullable=True)

    collected_at = Column(DateTime, default=_utcnow)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    source = relationship("SourceConfig", back_populates="finance_data_points")

    __table_args__ = (
        UniqueConstraint("source_id", "date_key", name="uq_finance_source_date"),
        Index("ix_finance_source_date", "source_id", "date_key"),
    )
