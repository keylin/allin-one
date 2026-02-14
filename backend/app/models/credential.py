"""平台凭证模型 — 集中管理 Cookie/Token 等平台认证信息"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Text, Index
from sqlalchemy.orm import relationship

from app.core.database import Base


def _uuid():
    return uuid.uuid4().hex

def _utcnow():
    """返回 naive UTC datetime，避免 PG TIMESTAMP WITHOUT TIME ZONE 的时区转换"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlatformCredential(Base):
    """平台凭证

    作为凭证 single source of truth，多个数据源引用同一凭证。
    更新凭证时可同步写入 .env 并重启 RSSHub 容器。

    platform 示例: "bilibili", "twitter"
    credential_type: "cookie", "oauth_token", "api_key"
    extra_info: JSON 字符串，如 {"uid": "12345", "username": "xxx"}
    """
    __tablename__ = "platform_credentials"

    id = Column(String, primary_key=True, default=_uuid)
    platform = Column(String, nullable=False)
    credential_type = Column(String, default="cookie")
    credential_data = Column(Text, nullable=False)
    display_name = Column(String, nullable=False)
    status = Column(String, default="active")       # active / expired / error
    expires_at = Column(DateTime, nullable=True)
    extra_info = Column(Text, nullable=True)         # JSON

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    sources = relationship("SourceConfig", back_populates="credential")

    __table_args__ = (
        Index("ix_credential_platform", "platform"),
    )
