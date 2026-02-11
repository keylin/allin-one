"""PromptTemplate 请求/响应模型"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PromptTemplateCreate(BaseModel):
    name: str
    template_type: str = "news_analysis"
    system_prompt: Optional[str] = None
    user_prompt: str
    output_format: Optional[str] = "markdown"
    is_default: bool = False


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    template_type: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    output_format: Optional[str] = None
    is_default: Optional[bool] = None


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    template_type: str = "news_analysis"
    system_prompt: Optional[str] = None
    user_prompt: str
    output_format: Optional[str] = "markdown"
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
