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
    "download_video": StepDefinition(
        step_type="download_video",
        display_name="下载视频",
        description="通过 yt-dlp 下载 Bilibili/YouTube 视频",
        max_retries=2,
        retry_delay=60,
        config_schema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["bilibili", "youtube", "auto"],
                    "default": "auto",
                },
                "quality": {
                    "type": "string",
                    "enum": ["360p", "720p", "1080p", "best"],
                    "default": "1080p",
                },
                "download_subtitle": {
                    "type": "boolean",
                    "default": True,
                },
            },
        },
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
                    "description": "提示词模版 ID (数据关联)",
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


# ============ 内置流水线模版 ============
# 流水线只做处理, 不含 fetch — 输入是已存在的 ContentItem

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "文章分析",
        "description": "提取全文 → LLM分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "enrich_content",  "is_critical": True,  "config": {"scrape_level": "auto"}},
            {"step_type": "analyze_content", "is_critical": False, "config": {}},
            {"step_type": "publish_content", "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "英文文章翻译分析",
        "description": "全文提取 → 翻译 → 分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "enrich_content",     "is_critical": True,  "config": {"scrape_level": "auto"}},
            {"step_type": "translate_content",  "is_critical": False, "config": {"target_language": "zh"}},
            {"step_type": "analyze_content",    "is_critical": False, "config": {}},
            {"step_type": "publish_content",    "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "视频下载分析",
        "description": "下载视频 → 字幕提取 → 分析 → 推送",
        "steps_config": json.dumps([
            {"step_type": "download_video",      "is_critical": True,  "config": {"quality": "1080p"}},
            {"step_type": "transcribe_content",  "is_critical": False, "config": {}},
            {"step_type": "analyze_content",     "is_critical": False, "config": {}},
            {"step_type": "publish_content",     "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "视频翻译分析",
        "description": "下载视频 → 字幕 → 翻译 → 分析 → 推送 (YouTube等外语视频)",
        "steps_config": json.dumps([
            {"step_type": "download_video",      "is_critical": True,  "config": {"quality": "1080p"}},
            {"step_type": "transcribe_content",  "is_critical": False, "config": {}},
            {"step_type": "translate_content",   "is_critical": False, "config": {"target_language": "zh"}},
            {"step_type": "analyze_content",     "is_critical": False, "config": {}},
            {"step_type": "publish_content",     "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "仅分析",
        "description": "直接 LLM 分析 → 推送 (适合 RSS 全文输出的源, 无需全文提取)",
        "steps_config": json.dumps([
            {"step_type": "analyze_content", "is_critical": True,  "config": {}},
            {"step_type": "publish_content", "is_critical": False, "config": {"channel": "none"}},
        ], ensure_ascii=False),
    },
    {
        "name": "仅推送",
        "description": "直接推送新内容通知, 不做分析",
        "steps_config": json.dumps([
            {"step_type": "publish_content", "is_critical": True, "config": {"channel": "email"}},
        ], ensure_ascii=False),
    },
]
