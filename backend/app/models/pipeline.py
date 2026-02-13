"""流水线模型

架构原则 (对照脑图「任务调度」):
  定时器 → 数据抓取 (Collector 负责, 产出 ContentItem)
  流水线 → 数据处理 (对已有的 ContentItem 执行原子操作)

流水线不包含 fetch 步骤。它的输入是已经存在的 ContentItem。
抓取动作由定时器 + CollectionService 完成。
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Integer, ForeignKey
)
from sqlalchemy.orm import relationship

from app.core.database import Base


# ============ 枚举定义 ============

class StepType(str, Enum):
    """原子操作类型 — 对照脑图「原子操作」分支

    注意: 没有 fetch_content!
    数据抓取是定时器的职责, 不是流水线步骤。
    """
    ENRICH_CONTENT = "enrich_content"          # 抓取全文 (L1/L2/L3)
    DOWNLOAD_VIDEO = "download_video"          # 下载视频 (bilibili/youtube)
    EXTRACT_AUDIO = "extract_audio"            # 音频提取 (待实现)
    TRANSCRIBE_CONTENT = "transcribe_content"  # 语音转文字
    TRANSLATE_CONTENT = "translate_content"     # 文章翻译
    ANALYZE_CONTENT = "analyze_content"        # 模型分析
    PUBLISH_CONTENT = "publish_content"        # 消息推送


class PipelineStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TriggerSource(str, Enum):
    SCHEDULED = "scheduled"    # 定时抓取后自动触发
    MANUAL = "manual"          # 用户手动触发
    API = "api"
    WEBHOOK = "webhook"


# ============ 辅助函数 ============

def _uuid():
    return uuid.uuid4().hex

def _utcnow():
    return datetime.now(timezone.utc)


# ============ 模型定义 ============

class PipelineTemplate(Base):
    """流水线模板

    定义一组有序的原子处理步骤。绑定到数据源后, 每次抓取到新内容会自动触发。

    steps_config JSON 示例 (注意: 没有 fetch_content):
    [
      {"step_type": "enrich_content",  "is_critical": false, "config": {"scrape_level": "auto"}},
      {"step_type": "analyze_content", "is_critical": false, "config": {"prompt_template_id": "xxx"}},
      {"step_type": "publish_content", "is_critical": false, "config": {"channel": "email"}}
    ]
    """
    __tablename__ = "pipeline_templates"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text)
    steps_config = Column(Text, nullable=False)       # JSON
    is_builtin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class PipelineExecution(Base):
    """流水线执行记录

    一次具体的处理实例。必须关联一条 ContentItem (流水线的输入)。
    content_id 不可为空 — 流水线处理的是已存在的内容。
    """
    __tablename__ = "pipeline_executions"

    id = Column(String, primary_key=True, default=_uuid)
    content_id = Column(String, ForeignKey("content_items.id"), nullable=False)
    source_id = Column(String, ForeignKey("source_configs.id"), nullable=True)
    template_id = Column(String, ForeignKey("pipeline_templates.id"), nullable=True)
    template_name = Column(String)

    status = Column(String, default=PipelineStatus.PENDING.value)
    current_step = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)
    trigger_source = Column(String, default=TriggerSource.MANUAL.value)
    error_message = Column(Text)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    content = relationship("ContentItem", back_populates="pipeline_executions")
    steps = relationship("PipelineStep", back_populates="pipeline",
                         cascade="all, delete-orphan",
                         order_by="PipelineStep.step_index")


class PipelineStep(Base):
    """流水线步骤执行记录"""
    __tablename__ = "pipeline_steps"

    id = Column(String, primary_key=True, default=_uuid)
    pipeline_id = Column(String, ForeignKey("pipeline_executions.id"), nullable=False)
    step_index = Column(Integer, nullable=False)
    step_type = Column(String, nullable=False)         # StepType 枚举
    step_config = Column(Text)                          # 操作配置 (JSON)
    is_critical = Column(Boolean, default=False)

    status = Column(String, default=StepStatus.PENDING.value)
    input_data = Column(Text)
    output_data = Column(Text)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # Relationships
    pipeline = relationship("PipelineExecution", back_populates="steps")
