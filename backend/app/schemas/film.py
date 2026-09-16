"""影视资料库 Pydantic Schema"""

from typing import Optional
from pydantic import BaseModel, Field


class FilmCreate(BaseModel):
    """手工添加影片：tmdb_id+kind 优先，否则 title(+year) 建骨架"""
    tmdb_id: Optional[str] = None
    kind: Optional[str] = None            # movie / series
    title: Optional[str] = None
    year: Optional[int] = None
    # 可选：创建时顺带写标记
    status: Optional[str] = None
    my_rating: Optional[int] = None
    watched_at: Optional[str] = None
    comment: Optional[str] = None


class WatchRecordUpdate(BaseModel):
    """更新用户标记；未传的字段不改"""
    status: Optional[str] = None          # unmarked / want / watching / watched / dropped
    my_rating: Optional[int] = Field(None, ge=1, le=10)
    watched_at: Optional[str] = None      # YYYY-MM-DD，空串清除
    tags: Optional[list[str]] = None
    comment: Optional[str] = None

    model_config = {"extra": "forbid"}


class BatchRecordItem(BaseModel):
    """批量标记条目：content_id / tmdb_id(+kind) / title(+year) 三选一定位"""
    content_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    kind: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    status: str = "watched"
    my_rating: Optional[int] = Field(None, ge=1, le=10)
    watched_at: Optional[str] = None
    comment: Optional[str] = None
    tags: Optional[list[str]] = None


class BatchRecordRequest(BaseModel):
    items: list[BatchRecordItem]


class FilmNoteUpdate(BaseModel):
    user_note: Optional[str] = None


class FilmMetaUpdate(BaseModel):
    """手工修正片名/年份/类型（骨架或错配时用）"""
    title: Optional[str] = None
    year: Optional[int] = None
    kind: Optional[str] = None


class FilmRelinkRequest(BaseModel):
    """重新识别：关联到指定 TMDb 条目，元数据整体替换，用户标记保留"""
    tmdb_id: str
    kind: str = "movie"


class DoubanLinkRequest(BaseModel):
    """手动设置豆瓣直达：粘链接或 id；都为空则自动解析"""
    url: Optional[str] = None
    douban_id: Optional[str] = None
