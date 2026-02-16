"""AI 对话服务 — 从 content route 提取"""

import json
import logging
import re
from typing import AsyncIterator

from app.models.content import ContentItem, SourceConfig

logger = logging.getLogger(__name__)


def build_chat_context(item: ContentItem, source: SourceConfig | None) -> str:
    """组装 AI 对话的系统消息上下文

    Args:
        item: ContentItem 实例
        source: 关联的 SourceConfig（可为 None）

    Returns:
        完整的 system message 字符串
    """
    context_parts = [f"标题: {item.title or '无标题'}"]
    if source:
        context_parts.append(f"来源: {source.name}")
    if item.author:
        context_parts.append(f"作者: {item.author}")
    if item.analysis_result:
        try:
            parsed = json.loads(item.analysis_result) if isinstance(item.analysis_result, str) else item.analysis_result
            if isinstance(parsed, dict):
                if parsed.get("summary"):
                    context_parts.append(f"AI 摘要: {parsed['summary']}")
                if parsed.get("tags"):
                    context_parts.append(f"标签: {', '.join(parsed['tags']) if isinstance(parsed['tags'], list) else parsed['tags']}")
            else:
                context_parts.append(f"分析结果: {str(parsed)[:500]}")
        except (json.JSONDecodeError, TypeError):
            context_parts.append(f"分析结果: {str(item.analysis_result)[:500]}")
    if item.processed_content:
        context_parts.append(f"正文内容:\n{item.processed_content[:2000]}")
    elif item.raw_data:
        try:
            raw = json.loads(item.raw_data) if isinstance(item.raw_data, str) else item.raw_data
            if isinstance(raw, dict):
                text = raw.get("summary") or raw.get("description") or ""
                if not text and isinstance(raw.get("content"), list) and raw["content"]:
                    first = raw["content"][0]
                    text = first.get("value", "") if isinstance(first, dict) else str(first)
                text = re.sub(r'<[^>]+>', '', str(text)).strip()
                if text:
                    context_parts.append(f"正文内容:\n{text[:2000]}")
        except (json.JSONDecodeError, TypeError):
            pass

    system_message = (
        "你是一个内容分析助手。用户正在阅读以下内容，请基于这篇内容回答用户的问题。"
        "回答要准确、简洁，使用中文。如果问题与内容无关，可以礼貌地提示用户。\n\n"
        "---\n" + "\n".join(context_parts) + "\n---"
    )
    return system_message


async def stream_chat_response(
    system_message: str,
    user_messages: list[dict],
    db=None,
) -> AsyncIterator[str]:
    """流式生成 AI 对话响应（SSE 格式）

    Args:
        system_message: 系统提示词（含内容上下文）
        user_messages: 用户对话历史 [{role, content}, ...]
        db: 可选数据库会话（传给 get_llm_config 读取配置）

    Yields:
        SSE data 行
    """
    from app.core.config import get_llm_config
    from openai import AsyncOpenAI

    llm_config = get_llm_config(db)
    client = AsyncOpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)

    messages = [{"role": "system", "content": system_message}]
    for msg in user_messages:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    try:
        response = await client.chat.completions.create(
            model=llm_config.model,
            messages=messages,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield f"data: {content}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.exception("Chat stream error")
        yield f"data: [ERROR] {str(e)}\n\n"
        yield "data: [DONE]\n\n"
