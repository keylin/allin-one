"""电子书相关 Pydantic Schema"""

from typing import Optional
from pydantic import BaseModel


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
