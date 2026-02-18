"""数据源与内容模型

设计原则 (来自脑图最新设计):
- 数据源 (Source) 只描述「从哪获取信息」，不涉及处理逻辑
- 处理逻辑完全由流水线 (Pipeline) 定义
- 数据源与流水线通过绑定关系组合，而非硬编码映射

示例:
  B站UP主视频分析 = RSSHub数据源(bilibili路由) + 视频分析流水线(fetch→download→transcribe→analyze)
  英文新闻翻译    = RSSStd数据源(CNN RSS) + 翻译分析流水线(fetch→enrich→translate→analyze→publish)
"""

import uuid
from enum import Enum

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.time import utcnow


# ============ 枚举定义 ============

class SourceType(str, Enum):
    """数据源类型 — 纯粹描述信息来源渠道

    对照脑图「数据源」分支:
      文件上传、RSSHub、RSSStd、AkShare、网页抓取(Scraper)、账号授权、用户记录

    采用两段式命名: {Category}.{Specific}
    """
    # RSS 类
    RSS_HUB = "rss.hub"              # RSSHub 生成的订阅源
    RSS_STANDARD = "rss.standard"    # 标准 RSS/Atom 订阅源
    # 数据接口
    API_AKSHARE = "api.akshare"      # AkShare 金融宏观数据
    # 网页抓取
    WEB_SCRAPER = "web.scraper"      # 网页抓取
    # 文件
    FILE_UPLOAD = "file.upload"      # 用户上传文件
    # 账号授权
    ACCOUNT_BILIBILI = "account.bilibili"  # B站账号
    ACCOUNT_GENERIC = "account.generic"    # 其他平台账号
    # 用户记录
    USER_NOTE = "user.note"          # 日常笔记
    SYSTEM_NOTIFICATION = "system.notification"  # 系统消息


class SourceCategory(str, Enum):
    """数据源大类"""
    NETWORK = "network"   # 网络数据 — Collector 自动采集
    USER = "user"         # 用户数据 — 用户/系统主动提交


_SOURCE_CATEGORY_MAP = {
    "rss": SourceCategory.NETWORK,
    "api": SourceCategory.NETWORK,
    "web": SourceCategory.NETWORK,
    "account": SourceCategory.NETWORK,
    "file": SourceCategory.USER,
    "user": SourceCategory.USER,
    "system": SourceCategory.USER,
}


def get_source_category(source_type: str) -> SourceCategory:
    """根据 source_type 前缀推导分类"""
    prefix = source_type.split(".")[0]
    return _SOURCE_CATEGORY_MAP.get(prefix, SourceCategory.NETWORK)


class MediaType(str, Enum):
    """媒体项类型"""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class ContentStatus(str, Enum):
    """内容处理状态"""
    PENDING = "pending"        # 已采集原始数据，尚未处理
    PROCESSING = "processing"  # 流水线处理中
    READY = "ready"            # 预处理完成，无后置流水线
    ANALYZED = "analyzed"      # 分析完成
    FAILED = "failed"          # 处理失败


# ============ 辅助函数 ============

def _uuid():
    return uuid.uuid4().hex

_utcnow = utcnow  # 兼容已有引用


# ============ 模型定义 ============

class SourceConfig(Base):
    """数据源配置

    只关心「从哪获取信息」:
    - source_type: 来源渠道 (rsshub / rss_std / scraper / ...)
    - url: 订阅/采集地址
    - config_json: 渠道特定配置
    - pipeline_template_id: 绑定的处理流水线 (决定"怎么处理")

    config_json 示例:
      RSSHub B站UP主:  {"rsshub_route": "/bilibili/user/video/12345"}
      RSSHub YouTube:   {"rsshub_route": "/youtube/channel/UCxxxx?embed_description=1"}
      标准RSS:          (使用 url 字段，config_json 可留空)
      Scraper:          {"scrape_level": "L2", "selectors": {"title": "h1"}}
      AkShare:          {"indicator": "macro_china_cpi"}
    """
    __tablename__ = "source_configs"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)       # SourceType 枚举
    url = Column(String)                                # 订阅/采集地址
    description = Column(Text)
    # 调度
    schedule_enabled = Column(Boolean, default=True)
    schedule_mode = Column(String, default="auto")      # auto / fixed / manual
    schedule_interval_override = Column(Integer, nullable=True)  # 固定间隔覆盖值（仅 fixed 模式）
    calculated_interval = Column(Integer, nullable=True)         # 系统计算的间隔（仅供展示）
    next_collection_at = Column(DateTime, nullable=True)         # 预计算的下次采集时间

    # 高级调度字段（0007 迁移）
    periodicity_data = Column(Text, nullable=True)               # 周期模式识别结果 JSON
    periodicity_updated_at = Column(DateTime, nullable=True)     # 周期分析更新时间
    hotspot_level = Column(String, nullable=True)                # 热点等级: extreme/high/instant
    hotspot_detected_at = Column(DateTime, nullable=True)        # 热点检测时间

    # 流水线绑定 — 解耦的关键
    pipeline_template_id = Column(String, ForeignKey("pipeline_templates.id"), nullable=True)

    # 渠道特定配置 (JSON)
    config_json = Column(Text)

    # 平台凭证引用（可选，向后兼容）
    credential_id = Column(String, ForeignKey("platform_credentials.id"), nullable=True)

    # 内容保留
    auto_cleanup_enabled = Column(Boolean, default=False)
    retention_days = Column(Integer, nullable=True)  # NULL = 使用全局默认

    # 运行状态
    last_collected_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    content_items = relationship("ContentItem", back_populates="source")
    collection_records = relationship("CollectionRecord", back_populates="source", cascade="all, delete-orphan")
    finance_data_points = relationship("FinanceDataPoint", back_populates="source", cascade="all, delete-orphan")
    credential = relationship("PlatformCredential", back_populates="sources")

    __table_args__ = (
        Index("ix_source_credential_id", "credential_id"),
        Index("ix_source_next_collection", "is_active", "schedule_enabled", "next_collection_at"),
    )


class ContentItem(Base):
    """内容项

    脑图「内容记录」: 原始内容 → 中间内容 → 最终内容 + 发布时间 + 采集时间
    """
    __tablename__ = "content_items"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, ForeignKey("source_configs.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    url = Column(String)
    author = Column(String)

    # 三层内容
    raw_data = Column(Text)              # 原始内容 (JSON)
    processed_content = Column(Text)     # 中间内容 (清洗/富化后)
    analysis_result = Column(Text)       # 最终内容 (LLM 分析结果 JSON)

    status = Column(String, default=ContentStatus.PENDING.value)
    language = Column(String)

    published_at = Column(DateTime, nullable=True)   # 发布时间
    collected_at = Column(DateTime, default=_utcnow)  # 采集时间

    is_favorited = Column(Boolean, default=False)
    favorited_at = Column(DateTime, nullable=True)
    user_note = Column(Text)
    chat_history = Column(Text, nullable=True)  # JSON: [{"role":"user","content":"..."},{"role":"assistant","content":"..."}]

    view_count = Column(Integer, default=0)
    last_viewed_at = Column(DateTime, nullable=True)     # 最后浏览时间
    playback_position = Column(Integer, default=0)       # 视频播放进度（秒）
    last_played_at = Column(DateTime, nullable=True)     # 最后播放时间

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    source = relationship("SourceConfig", back_populates="content_items")
    pipeline_executions = relationship("PipelineExecution", back_populates="content", cascade="all, delete-orphan")
    media_items = relationship("MediaItem", back_populates="content", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external"),
    )


class CollectionRecord(Base):
    """数据源抓取记录 (脑图: 数据源抓取纪录)

    独立于 Pipeline 执行, 记录每次数据源采集的结果。
    一次采集可发现 N 条内容, 可触发 N 条 Pipeline。
    """
    __tablename__ = "collection_records"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, ForeignKey("source_configs.id"), nullable=False)
    status = Column(String, default="running")           # running / completed / failed
    items_found = Column(Integer, default=0)
    items_new = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    source = relationship("SourceConfig", back_populates="collection_records")


class MediaItem(Base):
    """内容关联的媒体项 — ContentItem 一对多 MediaItem"""
    __tablename__ = "media_items"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id"), nullable=False)
    media_type = Column(String, nullable=False)    # MediaType 枚举值
    original_url = Column(String, nullable=False)   # 远程 URL
    local_path = Column(String, nullable=True)      # 下载后的本地路径
    filename = Column(String, nullable=True)         # 本地文件名
    status = Column(String, default="pending")       # pending / downloaded / failed
    metadata_json = Column(Text, nullable=True)      # JSON: 类型特定元数据

    created_at = Column(DateTime, default=_utcnow)

    content = relationship("ContentItem", back_populates="media_items")

    __table_args__ = (
        Index("ix_media_item_content_id", "content_id"),
    )
