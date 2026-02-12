"""Content 请求/响应模型"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    source_name: Optional[str] = None
    title: str
    external_id: str
    url: Optional[str] = None
    author: Optional[str] = None
    status: str = "pending"
    media_type: str = "text"
    language: Optional[str] = None
    published_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    is_favorited: bool = False
    user_note: Optional[str] = None
    view_count: int = 0
    last_viewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 列表摘要字段（API 层计算，非 ORM 字段）
    summary_text: Optional[str] = None
    tags: Optional[list[str]] = None
    sentiment: Optional[str] = None
    has_thumbnail: bool = False


class ContentDetailResponse(ContentResponse):
    raw_data: Optional[str] = None
    processed_content: Optional[str] = None
    analysis_result: Optional[str] = None


class ContentNoteUpdate(BaseModel):
    user_note: Optional[str] = None


class ContentBatchDelete(BaseModel):
    ids: list[str]
