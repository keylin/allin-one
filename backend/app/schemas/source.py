"""Source 请求/响应模型"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class SourceCreate(BaseModel):
    name: str
    source_type: str
    url: Optional[str] = None
    description: Optional[str] = None
    schedule_enabled: Optional[bool] = True
    schedule_interval: Optional[int] = 3600
    pipeline_template_id: Optional[str] = None
    config_json: Optional[str] = None
    credential_id: Optional[str] = None
    auto_cleanup_enabled: Optional[bool] = False
    retention_days: Optional[int] = None


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    schedule_interval: Optional[int] = None
    pipeline_template_id: Optional[str] = None
    config_json: Optional[str] = None
    credential_id: Optional[str] = None
    is_active: Optional[bool] = None
    auto_cleanup_enabled: Optional[bool] = None
    retention_days: Optional[int] = None


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: str
    url: Optional[str] = None
    description: Optional[str] = None
    schedule_enabled: bool = True
    schedule_interval: int = 3600
    pipeline_template_id: Optional[str] = None
    pipeline_template_name: Optional[str] = None
    config_json: Optional[str] = None
    credential_id: Optional[str] = None
    auto_cleanup_enabled: bool = False
    retention_days: Optional[int] = None
    last_collected_at: Optional[datetime] = None
    consecutive_failures: int = 0
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CollectionRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    status: str
    items_found: int = 0
    items_new: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
