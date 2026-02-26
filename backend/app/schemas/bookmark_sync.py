"""书签同步 Schema — Safari / Chrome 书签批量提交"""

from typing import Optional
from pydantic import BaseModel


class SyncBookmark(BaseModel):
    """单条书签"""
    url: str
    title: str
    added_at: Optional[str] = None    # ISO 8601 datetime string
    folder: Optional[str] = None      # 书签文件夹路径（如 "Reading List" / "Work/Dev"）


class BookmarkSyncRequest(BaseModel):
    source_id: str
    bookmarks: list[SyncBookmark]


class BookmarkSyncResponse(BaseModel):
    new_bookmarks: int
    updated_bookmarks: int


class BookmarkSyncStatus(BaseModel):
    source_id: Optional[str] = None
    last_sync_at: Optional[str] = None
    total_bookmarks: int = 0
