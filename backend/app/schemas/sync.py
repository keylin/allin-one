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
    # 凭证信息
    credential_id: Optional[str] = None
    credential_name: Optional[str] = None
    credential_status: Optional[str] = None      # active / expired / error / None
    # 是否需要凭证
    credential_required: bool = True
    # 同步模式: internal (Worker Fetcher) / script (外部脚本)
    sync_mode: str = "internal"
    # 同步状态
    is_syncing: bool = False
    sync_options: list[dict] = []                 # Fetcher 定义的选项


class SyncStatusResponse(BaseModel):
    """所有同步插件状态"""
    plugins: list[SyncPluginStatus] = []


class SyncRunRequest(BaseModel):
    """触发同步请求"""
    options: dict = {}


class SyncRunResponse(BaseModel):
    """触发同步响应"""
    progress_id: str
    source_id: str


class SyncProgressEvent(BaseModel):
    """SSE 推送的进度事件"""
    status: str                  # pending / running / completed / failed
    phase: Optional[str] = None
    message: Optional[str] = None
    current: int = 0
    total: int = 0
    result_data: Optional[dict] = None
    error_message: Optional[str] = None


class LinkCredentialRequest(BaseModel):
    """绑定凭证请求"""
    source_type: str
    credential_id: str
