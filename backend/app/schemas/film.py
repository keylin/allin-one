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
    """更新用户标记；未传的字段不改。

    status / tags 是片级；my_rating / watched_at / comment 落到最近一次观看记录（没有则新建一条）；
    rewatch=true 表示先新建一条观看记录再写这三项（重看）。"""
    status: Optional[str] = None          # unmarked / want / watching / watched / dropped
    my_rating: Optional[int] = Field(None, ge=1, le=10)
    watched_at: Optional[str] = None      # YYYY / YYYY-MM / YYYY-MM-DD / release，空串清除
    tags: Optional[list[str]] = None
    comment: Optional[str] = None         # = 最近一次观看的 note
    rewatch: Optional[bool] = None

    model_config = {"extra": "forbid"}


class WatchLogUpdate(BaseModel):
    """新建 / 修改一条观看记录；未传的字段不改"""
    watched_at: Optional[str] = None      # YYYY / YYYY-MM / YYYY-MM-DD / release，空串清除
    my_rating: Optional[int] = Field(None, ge=1, le=10)
    note: Optional[str] = None

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
