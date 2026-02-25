"""电子书同步 Pydantic Schema — 通用化，支持 Apple Books / 微信读书等"""

from typing import Optional
from pydantic import BaseModel, Field


class SyncAnnotation(BaseModel):
    """单条标注"""
    id: str
    selected_text: Optional[str] = None
    note: Optional[str] = None
    color: str = "yellow"                          # yellow / green / blue / pink / purple
    type: str = "highlight"                        # highlight / note
    chapter: Optional[str] = None
    location: Optional[str] = None
    is_deleted: bool = False
    created_at: Optional[str] = None
    modified_at: Optional[str] = None


class SyncBook(BaseModel):
    """单本书"""
    external_id: str = Field(..., alias="asset_id")  # 兼容旧字段名 asset_id
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    page_count: Optional[int] = None
    is_finished: bool = False
    reading_progress: float = 0                    # 0.0 ~ 1.0
    annotations: list[SyncAnnotation] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class EbookSyncRequest(BaseModel):
    """同步请求体"""
    source_id: str
    books: list[SyncBook]


class EbookSyncResponse(BaseModel):
    """同步结果"""
    new_books: int = 0
    updated_books: int = 0
    new_annotations: int = 0
    updated_annotations: int = 0
    deleted_annotations: int = 0


class EbookSyncStatus(BaseModel):
    """同步状态"""
    source_id: Optional[str] = None
    last_sync_at: Optional[str] = None
    total_books: int = 0
    total_annotations: int = 0
