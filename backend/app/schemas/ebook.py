"""电子书相关 Pydantic Schema"""

from typing import Optional
from pydantic import BaseModel, Field


class ReadingProgressUpdate(BaseModel):
    cfi: Optional[str] = None
    progress: float = 0
    section_index: Optional[int] = None
    section_title: Optional[str] = None


class ReadingProgressResponse(BaseModel):
    cfi: Optional[str] = None
    progress: float = 0
    section_index: int = 0
    section_title: Optional[str] = None
    updated_at: Optional[str] = None


class AnnotationCreate(BaseModel):
    cfi_range: str
    section_index: Optional[int] = None
    type: str = "highlight"
    color: str = "yellow"
    selected_text: Optional[str] = None
    note: Optional[str] = None


class AnnotationUpdate(BaseModel):
    color: Optional[str] = None
    note: Optional[str] = None


class AnnotationResponse(BaseModel):
    id: str
    cfi_range: str
    section_index: Optional[int] = None
    type: str
    color: str
    selected_text: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class BookmarkCreate(BaseModel):
    cfi: str
    title: Optional[str] = None
    section_title: Optional[str] = None


class BookmarkResponse(BaseModel):
    id: str
    cfi: str
    title: Optional[str] = None
    section_title: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# ─── Metadata ──────────────────────────────────────────────────────────────

class EbookMetadataUpdate(BaseModel):
    """手动编辑元数据请求体"""
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    language: Optional[str] = None
    subjects: Optional[list[str]] = None
    publish_date: Optional[str] = None
    series: Optional[str] = None
    page_count: Optional[int] = None


class BookSearchResult(BaseModel):
    """在线搜索结果"""
    title: str = ""
    author: str = ""
    isbn_10: str = ""
    isbn_13: str = ""
    publisher: str = ""
    publish_date: str = ""
    language: str = ""
    page_count: int = 0
    subjects: list[str] = Field(default_factory=list)
    description: str = ""
    cover_url: str = ""


class MetadataApplyRequest(BaseModel):
    """应用在线搜索结果请求体"""
    title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    isbn_10: Optional[str] = None
    isbn_13: Optional[str] = None
    publisher: Optional[str] = None
    language: Optional[str] = None
    subjects: Optional[list[str]] = None
    publish_date: Optional[str] = None
    page_count: Optional[int] = None
