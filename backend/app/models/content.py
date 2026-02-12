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
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship

from app.core.database import Base


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


class MediaType(str, Enum):
    """媒体类型 — 描述内容本身的形态"""
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    MIXED = "mixed"


class ContentStatus(str, Enum):
    """内容处理状态"""
    PENDING = "pending"        # 已采集原始数据，尚未处理
    PROCESSING = "processing"  # 流水线处理中
    ANALYZED = "analyzed"      # 分析完成
    FAILED = "failed"          # 处理失败


# ============ 辅助函数 ============

def _uuid():
    return uuid.uuid4().hex

def _utcnow():
    return datetime.now(timezone.utc)


# ============ 模型定义 ============

class SourceConfig(Base):
    """数据源配置

    只关心「从哪获取信息」:
    - source_type: 来源渠道 (rsshub / rss_std / scraper / ...)
    - url: 订阅/抓取地址
    - config_json: 渠道特定配置
    - pipeline_template_id: 绑定的处理流水线 (决定"怎么处理")

    config_json 示例:
      RSSHub B站UP主:  {"rsshub_route": "/bilibili/user/video/12345"}
      RSSHub YouTube:   {"rsshub_route": "/youtube/channel/UCxxxx"}
      标准RSS:          {"feed_format": "atom"}
      Scraper:          {"scrape_level": "L2", "selectors": {"title": "h1"}}
      AkShare:          {"indicator": "macro_china_cpi"}
    """
    __tablename__ = "source_configs"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)       # SourceType 枚举
    url = Column(String)                                # 订阅/抓取地址
    description = Column(Text)
    media_type = Column(String, default=MediaType.TEXT.value)  # 该源产出的媒体类型

    # 调度
    schedule_enabled = Column(Boolean, default=True)
    schedule_interval = Column(Integer, default=3600)   # 采集间隔 (秒)

    # 流水线绑定 — 解耦的关键
    pipeline_template_id = Column(String, ForeignKey("pipeline_templates.id"), nullable=True)

    # 渠道特定配置 (JSON)
    config_json = Column(Text)

    # 运行状态
    last_collected_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    content_items = relationship("ContentItem", back_populates="source", cascade="all, delete-orphan")
    collection_records = relationship("CollectionRecord", back_populates="source", cascade="all, delete-orphan")


class ContentItem(Base):
    """内容项

    脑图「内容记录」: 原始内容 → 中间内容 → 最终内容 + 发布时间 + 抓取时间
    """
    __tablename__ = "content_items"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, ForeignKey("source_configs.id"), nullable=False)
    title = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    url = Column(String)
    author = Column(String)

    # 三层内容
    raw_data = Column(Text)              # 原始内容 (JSON)
    processed_content = Column(Text)     # 中间内容 (清洗/富化后)
    analysis_result = Column(Text)       # 最终内容 (LLM 分析结果 JSON)

    status = Column(String, default=ContentStatus.PENDING.value)
    media_type = Column(String, default=MediaType.TEXT.value)
    language = Column(String)

    published_at = Column(DateTime, nullable=True)   # 发布时间
    collected_at = Column(DateTime, default=_utcnow)  # 抓取时间

    is_favorited = Column(Boolean, default=False)
    user_note = Column(Text)

    view_count = Column(Integer, default=0)
    last_viewed_at = Column(DateTime, nullable=True)     # 最后浏览时间
    playback_position = Column(Integer, default=0)       # 视频播放进度（秒）
    last_played_at = Column(DateTime, nullable=True)     # 最后播放时间

    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # Relationships
    source = relationship("SourceConfig", back_populates="content_items")
    pipeline_executions = relationship("PipelineExecution", back_populates="content")

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
