"""同步管理 Pydantic Schema — 统一同步状态响应"""

from typing import Optional
from pydantic import BaseModel


class SyncPluginStatus(BaseModel):
    """单个同步插件的状态"""
    source_type: str
    name: str
    category: str
    description: str
    configured: bool = False
    source_id: Optional[str] = None
    last_sync_at: Optional[str] = None
    stats: dict = {}


class SyncStatusResponse(BaseModel):
    """所有同步插件状态"""
    plugins: list[SyncPluginStatus] = []
