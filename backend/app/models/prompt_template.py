"""提示词模板模型"""

import uuid
from enum import Enum

from sqlalchemy import Column, String, Boolean, DateTime, Text

from app.core.database import Base
from app.core.time import utcnow


class TemplateType(str, Enum):
    NEWS_ANALYSIS = "news_analysis"
    SUMMARY = "summary"
    TRANSLATION = "translation"
    CUSTOM = "custom"


class OutputFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"


class PromptTemplate(Base):
    """提示词模板"""
    __tablename__ = "prompt_templates"

    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    name = Column(String, nullable=False)
    template_type = Column(String, default=TemplateType.NEWS_ANALYSIS.value)
    system_prompt = Column(Text)
    user_prompt = Column(Text, nullable=False)
    output_format = Column(Text)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
