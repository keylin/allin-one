"""Pipeline 请求/响应模型"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PipelineStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    step_index: int
    step_type: str
    step_config: Optional[str] = None
    is_critical: bool = False
    status: str = "pending"
    output_data: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content_id: str
    source_id: Optional[str] = None
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    status: str = "pending"
    current_step: int = 0
    total_steps: int = 0
    trigger_source: str = "manual"
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PipelineDetailResponse(PipelineResponse):
    steps: list[PipelineStepResponse] = []
    content_title: Optional[str] = None


class PipelineTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    steps_config: str
    is_active: bool = True


class PipelineTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps_config: Optional[str] = None
    is_active: Optional[bool] = None
