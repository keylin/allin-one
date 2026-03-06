"""Pipeline step: extract_content — 从 raw_data 提取内容到 processed_content"""

import logging
import re

from app.core.database import SessionLocal
from app.models.content import ContentItem

logger = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    """去除 HTML 标签, 返回纯文本"""
    text = re.sub(r"<[^>]+>", "", html)
    return text.strip()


def _extract_raw_text(raw_data: dict | None) -> str:
    """从 raw_data dict 提取文本内容

    提取优先级:
    1. raw_data.content[0].value (RSS content:encoded, 全文 HTML)
    2. raw_data.summary (RSS 摘要)
    """
    if not raw_data or not isinstance(raw_data, dict):
        return ""
    # 优先 content[0].value (RSS <content:encoded>, 通常是全文 HTML)
    contents = raw_data.get("content", [])
    if isinstance(contents, list) and contents:
        value = contents[0].get("value", "")
        if value:
            return value
    # 回退 summary
    return raw_data.get("summary", "")


def _handle_extract_content(context: dict) -> dict:
    """从 raw_data 提取内容填充 processed_content

    此步骤从 ContentItem.raw_data 中提取文本内容，填充到 processed_content。
    这是流水线的第一个步骤，为后续步骤提供初始内容。

    提取优先级:
    1. raw_data.content[0].value (RSS content:encoded, 全文 HTML)
    2. raw_data.summary (RSS 摘要)
    """
    content_id = context["content_id"]

    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if not content:
            raise ValueError(f"ContentItem not found: {content_id}")

        # 如果已有 processed_content，跳过
        if content.processed_content:
            logger.info(f"[extract_content] content {content_id} already has processed_content, skipping")
            return {"status": "skipped", "reason": "processed_content already exists"}

        # 从 raw_data 提取
        raw_text = _extract_raw_text(content.raw_data)
        if not raw_text:
            logger.warning(f"[extract_content] no content found in raw_data for {content_id}")
            return {"status": "skipped", "reason": "no content in raw_data"}

        content.processed_content = raw_text

        # 在 session 内计算 source 字段，避免 session 关闭后访问 ORM 属性
        raw = content.raw_data or {}
        source_field = "raw_data.content[0].value" if "content" in raw else "raw_data.summary"

        db.commit()

        text_len = len(raw_text)
        logger.info(f"[extract_content] populated processed_content for {content_id} ({text_len} chars)")

        return {
            "status": "done",
            "text_length": text_len,
            "source": source_field,
        }
