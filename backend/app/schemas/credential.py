"""PlatformCredential 请求/响应模型"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class CredentialCreate(BaseModel):
    platform: str
    credential_type: str = "cookie"
    credential_data: str
    display_name: str
    extra_info: Optional[str] = None


class CredentialUpdate(BaseModel):
    credential_data: Optional[str] = None
    display_name: Optional[str] = None
    status: Optional[str] = None
    extra_info: Optional[str] = None


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    platform: str
    credential_type: str
    credential_data: str  # API 层掩码
    display_name: str
    status: str
    expires_at: Optional[datetime] = None
    extra_info: Optional[str] = None
    source_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
