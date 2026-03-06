"""PipelineTemplate 响应模型"""

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class PipelineTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    steps_config: Any = None  # JSONB: list of step definitions
    is_builtin: bool = False
    is_active: bool = True
