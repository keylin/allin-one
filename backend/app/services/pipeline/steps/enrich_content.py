"""Pipeline step: enrich_content — 抓取全文 L1/Crawl4AI/L2"""

import logging

from app.services.pipeline.steps._helpers import _run_async

logger = logging.getLogger(__name__)

_SANITIZE_ALLOWED_TAGS = frozenset([
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'a', 'img', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'em', 'strong', 'b', 'i', 'table', 'thead', 'tbody', 'tr', 'td', 'th',
    'figure', 'figcaption', 'hr', 'div', 'span', 'sub', 'sup',
])
_SANITIZE_ALLOWED_ATTRS = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'width', 'height'},
}


def _sanitize_html(html: str) -> str:
    """清理 HTML，只保留安全的内容标签（使用 BeautifulSoup，无需额外依赖）"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(True):
        if tag.name not in _SANITIZE_ALLOWED_TAGS:
            # 用子节点替换不允许的标签（保留文本内容）
            tag.unwrap()
        else:
            # 只保留白名单属性
            allowed = _SANITIZE_ALLOWED_ATTRS.get(tag.name, set())
            for attr in list(tag.attrs):
                if attr not in allowed:
                    del tag[attr]

    return str(soup)


def _handle_enrich_content(context: dict) -> dict:
    """抓取全文 — L1 HTTP 优先 + Crawl4AI/L2 兜底

    提取流程：L1 HTTP+trafilatura → Crawl4AI → L2 Browserless+trafilatura → 原始内容回退。
    输出 Markdown 格式。质量保障：反爬检测 + enriched vs original 对比 + 自动回退。
    此函数永远不 raise，失败时 fallback 到原始内容。
    """
    url = context["content_url"]
    if not url:
        return {"status": "skipped", "reason": "no url"}

    logger.info(f"[enrich_content] url={url}")

    import httpx
    from bs4 import BeautifulSoup
    from app.services.pipeline.steps.extract_content import _extract_raw_text, _strip_html
    from app.services.enrichment import (
        _extract_with_trafilatura,
        _detect_anti_scraping,
        _compare_quality,
        _fetch_with_browserless,
        _extract_with_crawl4ai,
    )

    # 1. 提取原始文本（用于对比和回退）
    from app.core.database import SessionLocal
    from app.models.content import ContentItem
    with SessionLocal() as db:
        content = db.get(ContentItem, context["content_id"])
        raw_data_json = content.raw_data if content else None

    original_html = _extract_raw_text(raw_data_json)
    original_text = _strip_html(original_html) if original_html else ""

    enriched_md = ""
    method = ""
    anti_scraping_info = None

    # 2. 快速尝试 L1: 普通 HTTP + trafilatura
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        # 反爬检测（用原始 HTML 的纯文本）
        soup = BeautifulSoup(html, "lxml")
        plain_text = soup.get_text(separator="\n", strip=True)

        block_reason = _detect_anti_scraping(html, plain_text)
        if block_reason:
            logger.warning(f"[enrich_content] L1 anti-scraping detected: {block_reason}, trying Crawl4AI")
            anti_scraping_info = {"level": "L1", "reason": block_reason}
        else:
            # trafilatura 提取 Markdown
            result = _extract_with_trafilatura(html, url=url)
            if result and len(result.strip()) >= 100:
                enriched_md = result
                method = "L1_HTTP"
            else:
                logger.warning(f"[enrich_content] L1 trafilatura content too short ({len(result) if result else 0} chars), trying Crawl4AI")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.warning(f"[enrich_content] L1 got 403, trying Crawl4AI")
            anti_scraping_info = {"level": "L1", "reason": "http_403"}
        else:
            logger.warning(f"[enrich_content] L1 HTTP error {e.response.status_code}, trying Crawl4AI")
    except Exception as e:
        logger.warning(f"[enrich_content] L1 failed: {e}, trying Crawl4AI")

    # 3. 兜底：Crawl4AI（通过 CDP 连接 Browserless）
    if not enriched_md:
        try:
            crawl4ai_result = _run_async(_extract_with_crawl4ai(url))
            if crawl4ai_result and len(crawl4ai_result.strip()) >= 100:
                enriched_md = crawl4ai_result
                method = "crawl4ai"
                logger.info(f"[enrich_content] Crawl4AI succeeded, md_length={len(enriched_md)}")
            else:
                logger.info(f"[enrich_content] Crawl4AI result too short ({len(crawl4ai_result.strip()) if crawl4ai_result else 0} chars), trying L2")
        except Exception as e:
            logger.warning(f"[enrich_content] Crawl4AI failed: {e}, trying L2")

    # 4. 兜底 L2: Browserless 渲染 + trafilatura
    if not enriched_md:
        try:
            from app.core.config import settings
            l2_html = _fetch_with_browserless(url, settings.BROWSERLESS_URL)

            # L2 反爬检测
            soup = BeautifulSoup(l2_html, "lxml")
            l2_plain = soup.get_text(separator="\n", strip=True)
            block_reason = _detect_anti_scraping(l2_html, l2_plain)
            if block_reason:
                logger.warning(f"[enrich_content] L2 anti-scraping detected: {block_reason}")
                anti_scraping_info = {"level": "L2", "reason": block_reason}
            else:
                result = _extract_with_trafilatura(l2_html, url=url)
                if result and len(result.strip()) >= 100:
                    enriched_md = result
                    method = "L2_Browserless"
                    logger.info(f"[enrich_content] L2 succeeded, md_length={len(enriched_md)}")
                else:
                    logger.warning(f"[enrich_content] L2 trafilatura content too short ({len(result) if result else 0} chars)")

        except Exception as e:
            logger.error(f"[enrich_content] L2 also failed: {e}")

    # 5. 质量对比：enriched vs original
    if enriched_md:
        quality = _compare_quality(enriched_md, original_text)
        logger.info(f"[enrich_content] quality check: {quality}")

        if not quality["use_enriched"]:
            logger.warning(f"[enrich_content] enriched rejected: {quality['reason']}, fallback to original")
            with SessionLocal() as db:
                content = db.get(ContentItem, context["content_id"])
                if content and original_html:
                    content.processed_content = original_html
                    db.commit()
            return {
                "status": "fallback_to_original",
                "reason": quality["reason"],
                "method": method,
                "quality": quality,
                "anti_scraping_detected": anti_scraping_info,
            }

        # 质量通过，存储 Markdown
        with SessionLocal() as db:
            content = db.get(ContentItem, context["content_id"])
            if content:
                content.processed_content = enriched_md
                db.commit()

        return {
            "status": "enriched",
            "text_length": len(enriched_md),
            "method": method,
            "format": "markdown",
            "quality": quality,
        }

    # 6. 抓取完全失败，回退到原始内容
    if original_html:
        logger.warning(f"[enrich_content] all fetch failed, fallback to original ({len(original_text)} chars)")
        with SessionLocal() as db:
            content = db.get(ContentItem, context["content_id"])
            if content:
                content.processed_content = original_html
                db.commit()
        return {
            "status": "fallback_to_original",
            "reason": "all fetch methods failed",
            "original_len": len(original_text),
            "anti_scraping_detected": anti_scraping_info,
        }

    logger.error(f"[enrich_content] no enriched content and no original to fallback")
    return {
        "status": "failed_no_content",
        "reason": "no enriched content and no original fallback",
        "anti_scraping_detected": anti_scraping_info,
    }
