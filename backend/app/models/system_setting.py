"""系统设置模型"""

from sqlalchemy import Column, String, Text, DateTime
from app.core.database import Base
from app.core.time import utcnow


class SystemSetting(Base):
    """系统设置 (KV 存储)"""
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True)
    value = Column(Text)
    description = Column(Text)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
