"""Pipeline 注册表

架构原则:
  定时器 → Collector 抓取 → 产出 ContentItem
  流水线 → 处理已有的 ContentItem (不含 fetch 步骤)

fetch_content 不是原子操作, 它是定时器 + CollectionService 的职责。
"""

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepDefinition:
    """原子操作定义"""
    step_type: str
    display_name: str
    description: str
    is_critical_default: bool = False
    max_retries: int = 3
    retry_delay: int = 30
    config_schema: dict = field(default_factory=dict)


# ============ 原子操作注册表 ============
# 对照脑图「原子操作」: 抓取全文、下载视频、音频提取、文章翻译、模型分析、消息推送
# 注意: 没有 fetch_content

STEP_DEFINITIONS: dict[str, StepDefinition] = {
    "extract_content": StepDefinition(
        step_type="extract_content",
        display_name="提取内容",
        description="从 raw_data 提取文本内容到 processed_content",
    ),
    "enrich_content": StepDefinition(
        step_type="enrich_content",
        display_name="抓取全文",
        description="富化内容: L1 HTTP → L2 浏览器模拟 → L3 browser-use",
        config_schema={
            "type": "object",
            "properties": {
                "scrape_level": {
                    "type": "string",
                    "enum": ["L1", "L2", "L3", "auto"],
                    "default": "auto",
                    "description": "抓取级别: L1=HTTP, L2=浏览器, L3=AI浏览器, auto=逐级递进",
                },
            },
        },
    ),
    "localize_media": StepDefinition(
        step_type="localize_media",
        display_name="媒体本地化",
        description="检测并下载内容中的图片/视频/音频，创建 MediaItem，改写URL为本地引用",
    ),
    "extract_audio": StepDefinition(
        step_type="extract_audio",
        display_name="音频提取",
        description="从视频中提取音频 (待实现)",
    ),
    "transcribe_content": StepDefinition(
        step_type="transcribe_content",
        display_name="语音转文字",
        description="视频/音频字幕提取或 ASR 转写",
    ),
    "translate_content": StepDefinition(
        step_type="translate_content",
        display_name="文章翻译",
        description="通过 LLM 翻译内容",
        config_schema={
            "type": "object",
            "properties": {
                "target_language": {
                    "type": "string",
                    "default": "zh",
                },
            },
        },
    ),
    "analyze_content": StepDefinition(
        step_type="analyze_content",
        display_name="模型分析",
        description="调用 LLM 进行内容分析",
        config_schema={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "模型名称 (下拉枚举)",
                },
                "prompt_template_id": {
                    "type": "string",
                    "description": "提示词模板 ID (数据关联)",
                },
            },
        },
    ),
    "publish_content": StepDefinition(
        step_type="publish_content",
        display_name="消息推送",
        description="将分析结果推送到通知渠道",
        config_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["email", "dingtalk", "webhook", "none"],
                    "default": "none",
                },
                "frequency": {
                    "type": "string",
                    "enum": ["immediate", "hourly", "daily"],
                    "default": "immediate",
                },
            },
        },
    ),
}


# ============ 内置流水线模板 ============
# 流水线只做处理, 不含 fetch — 输入是已存在的 ContentItem

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "文章分析",
        "description": "提取内容 → 媒体本地化 → LLM分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",  "is_critical": True,  "config": {}},
            {"step_type": "localize_media",   "is_critical": False, "config": {}},
            {"step_type": "analyze_content",  "is_critical": True,  "config": {}},
            {"step_type": "publish_content",  "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "英文文章翻译分析",
        "description": "提取内容 → 媒体本地化 → 翻译 → 分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",   "is_critical": True,  "config": {}},
            {"step_type": "localize_media",    "is_critical": False, "config": {}},
            {"step_type": "translate_content", "is_critical": True,  "config": {"target_language": "zh"}},
            {"step_type": "analyze_content",   "is_critical": False, "config": {}},
            {"step_type": "publish_content",   "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "视频下载分析",
        "description": "提取内容 → 媒体本地化(含视频下载) → 字幕提取 → 分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",    "is_critical": True,  "config": {}},
            {"step_type": "localize_media",     "is_critical": True,  "config": {}},
            {"step_type": "transcribe_content", "is_critical": True,  "config": {}},
            {"step_type": "analyze_content",    "is_critical": False, "config": {}},
            {"step_type": "publish_content",    "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "视频翻译分析",
        "description": "提取内容 → 媒体本地化 → 字幕提取 → 翻译 → 分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",    "is_critical": True,  "config": {}},
            {"step_type": "localize_media",     "is_critical": True,  "config": {}},
            {"step_type": "transcribe_content", "is_critical": True,  "config": {}},
            {"step_type": "translate_content",  "is_critical": False, "config": {"target_language": "zh"}},
            {"step_type": "analyze_content",    "is_critical": False, "config": {}},
            {"step_type": "publish_content",    "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "仅分析",
        "description": "提取内容 → LLM分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",  "is_critical": True,  "config": {}},
            {"step_type": "analyze_content",  "is_critical": True,  "config": {}},
            {"step_type": "publish_content",  "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "仅推送",
        "description": "提取内容 → 推送新内容通知",
        "steps_config": json.dumps([
            {"step_type": "extract_content",  "is_critical": True,  "config": {}},
            {"step_type": "publish_content",  "is_critical": True,  "config": {"channel": "email"}},
        ], ensure_ascii=False),
    },
    {
        "name": "金融数据分析",
        "description": "提取内容 → LLM分析金融数据趋势 → 推送",
        "steps_config": json.dumps([
            {"step_type": "extract_content",  "is_critical": True,  "config": {}},
            {"step_type": "analyze_content",  "is_critical": True,  "config": {}},
            {"step_type": "publish_content",  "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "媒体下载",
        "description": "仅执行媒体本地化（单个步骤），用于收藏触发或手动下载",
        "steps_config": json.dumps([
            {"step_type": "localize_media", "is_critical": True, "config": {}},
        ], ensure_ascii=False),
    },
]
