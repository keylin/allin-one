"""视频同步 Pydantic Schema — 支持 B站等外部视频平台"""

from typing import Optional
from pydantic import BaseModel, Field


class SyncVideo(BaseModel):
    """单条视频"""
    external_id: str = Field(..., alias="bvid")  # bvid，兼容旧字段名
    title: str
    author: Optional[str] = None
    url: Optional[str] = None           # 视频页 URL
    duration: Optional[int] = None      # 秒
    cover_url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    published_at: Optional[str] = None  # ISO datetime
    is_favorited: bool = False
    playback_position: int = 0          # 播放进度（秒）
    rating: Optional[float] = None      # 豆瓣评分 0-10
    comment: Optional[str] = None      # 短评
    extra: Optional[dict] = None        # 平台扩展字段（view/like/coin 等）

    model_config = {"populate_by_name": True}


class VideoSyncRequest(BaseModel):
    """同步请求体"""
    source_id: str
    videos: list[SyncVideo]


class VideoSyncResponse(BaseModel):
    """同步结果"""
    new_videos: int = 0
    updated_videos: int = 0


class VideoSyncStatus(BaseModel):
    """同步状态"""
    source_id: Optional[str] = None
    last_sync_at: Optional[str] = None
    total_videos: int = 0
