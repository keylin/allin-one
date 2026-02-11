"""SystemSetting 请求/响应模型"""

from typing import Optional
from pydantic import BaseModel


class SettingsUpdate(BaseModel):
    settings: dict[str, Optional[str]]


class SettingItem(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None
