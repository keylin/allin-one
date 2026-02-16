"""Pipeline step: translate_content — LLM 翻译"""

import json
import logging

from app.services.pipeline.steps._helpers import _run_async, _llm_chat

logger = logging.getLogger(__name__)


def _handle_translate_content(context: dict) -> dict:
    """文章翻译 — LLM"""
    config = context["step_config"]
    target_lang = config.get("target_language", "zh")
    content_id = context["content_id"]

    logger.info(f"[translate_content] target={target_lang}, content={content_id}")

    from app.core.database import SessionLocal
    from app.models.content import ContentItem

    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if not content:
            raise ValueError(f"Content not found: {content_id}")

        # 优先取 processed_content，否则从 raw_data 取
        text = content.processed_content
        if not text and content.raw_data:
            raw = json.loads(content.raw_data)
            text = raw.get("summary") or raw.get("content", [{}])[0].get("value", "") if isinstance(raw.get("content"), list) else raw.get("content", "")

    if not text:
        return {"status": "skipped", "reason": "no text to translate"}

    lang_names = {"zh": "中文", "en": "English", "ja": "日本語"}
    target_name = lang_names.get(target_lang, target_lang)

    result = _run_async(_llm_chat(
        messages=[
            {"role": "system", "content": f"你是一位专业翻译。请将以下内容翻译为{target_name}，保持原文格式和语义。只输出翻译结果，不要添加解释。"},
            {"role": "user", "content": text},
        ],
    ))
    translated = result.choices[0].message.content

    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if content:
            content.processed_content = translated
            db.commit()

    return {"status": "translated", "target_language": target_lang, "text_length": len(translated)}
