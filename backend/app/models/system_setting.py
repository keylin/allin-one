"""系统设置模型"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from app.core.database import Base


class SystemSetting(Base):
    """系统设置 (KV 存储)"""
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
