"""Pipeline step: analyze_content — LLM 分析"""

import json
import logging

from app.services.pipeline.steps._helpers import _run_async, _llm_chat, _llm_analyze

logger = logging.getLogger(__name__)


def _handle_analyze_content(context: dict) -> dict:
    """模型分析 — LLMAnalyzer"""
    config = context["step_config"]
    prompt_template_id = config.get("prompt_template_id")
    content_id = context["content_id"]

    logger.info(f"[analyze_content] prompt={prompt_template_id}, content={content_id}")

    from app.core.database import SessionLocal
    from app.models.content import ContentItem
    from app.models.prompt_template import PromptTemplate

    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if not content:
            raise ValueError(f"Content not found: {content_id}")

        # 确定输入文本
        text = content.processed_content
        if not text and content.raw_data:
            raw = json.loads(content.raw_data)
            text = raw.get("summary", "")
            if not text:
                contents = raw.get("content", [])
                if isinstance(contents, list) and contents:
                    text = contents[0].get("value", "")
        if not text:
            text = content.title or ""
        if not text:
            return {"status": "skipped", "reason": "no text to analyze"}

        # 确定 prompt template
        prompt_tpl = None
        if prompt_template_id:
            prompt_tpl = db.get(PromptTemplate, prompt_template_id)
        if not prompt_tpl:
            prompt_tpl = db.query(PromptTemplate).filter(PromptTemplate.is_default == True).first() if hasattr(PromptTemplate, "is_default") else None
        if not prompt_tpl:
            prompt_tpl = db.query(PromptTemplate).first()

    # 使用 LLMAnalyzer 或 fallback
    if prompt_tpl:
        result = _run_async(_llm_analyze(text, prompt_tpl))
    else:
        # 内置 fallback prompt
        result = _run_async(_llm_chat(
            messages=[
                {"role": "system", "content": "你是一位信息分析助手。请对以下内容进行分析，提取关键信息。返回 JSON 格式，包含 summary（摘要）、key_points（要点列表）、sentiment（情感倾向）字段。"},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        ))
        try:
            result = json.loads(result.choices[0].message.content)
        except (json.JSONDecodeError, AttributeError):
            result = {"summary": result.choices[0].message.content if hasattr(result, "choices") else str(result)}

    # 写回 analysis_result
    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if content:
            content.analysis_result = json.dumps(result, ensure_ascii=False)
            db.commit()

    return {"status": "analyzed", "result_keys": list(result.keys()) if isinstance(result, dict) else []}
