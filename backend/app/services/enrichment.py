"""内容富化服务 — 三级并行抓取对比

提供 L1 HTTP、Crawl4AI、L3 Browserless 三种抓取方式，
支持并行执行并返回对比结果。

同时作为 pipeline_tasks.py 中 enrich_content 步骤的底层函数库。
"""

import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

# ============ 常量 ============

_LAZY_ATTRS = ["data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "data-url"]
_PLACEHOLDER_PATTERNS = re.compile(
    r"data:image/|placeholder|spacer|blank\.(gif|png)|1x1|loading.*\.(gif|png|svg)", re.I
)

_BLOCKED_PAGE_PATTERNS = [
    # Cloudflare
    (re.compile(r"cf-browser-verification|cf-challenge|checking your browser", re.I), "cloudflare_challenge"),
    (re.compile(r"ray\s*id|cloudflare", re.I), "cloudflare_block"),
    # HTTP 错误页
    (re.compile(r"403\s*forbidden|access\s*denied|you don'?t have permission", re.I), "403_forbidden"),
    (re.compile(r"401\s*unauthorized", re.I), "401_unauthorized"),
    # 验证码 / 人机验证
    (re.compile(r"captcha|recaptcha|hcaptcha|verify you are human|are you a robot", re.I), "captcha"),
    # 付费墙
    (re.compile(r"subscribe to (read|continue|access)|paywall|premium content|sign in to read", re.I), "paywall"),
    # 通用拦截
    (re.compile(r"please enable (javascript|cookies)|browser.*not supported", re.I), "browser_requirement"),
]


# ============ 辅助函数 ============

def _parse_srcset_best(srcset: str) -> str | None:
    """从 srcset 中提取最大分辨率的 URL"""
    best_url, best_w = None, 0
    for part in srcset.split(","):
        part = part.strip()
        tokens = part.split()
        if len(tokens) >= 2:
            url = tokens[0]
            descriptor = tokens[-1]
            try:
                w = int(descriptor.rstrip("wx"))
                if w > best_w:
                    best_url, best_w = url, w
            except ValueError:
                pass
        elif len(tokens) == 1 and tokens[0].startswith("http"):
            best_url = tokens[0]
    return best_url


def _fix_lazy_images(html: str) -> str:
    """在正文提取前，将懒加载图片的真实 URL 写入 src"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for img in soup.find_all("img"):
        src = img.get("src", "")
        is_placeholder = not src or _PLACEHOLDER_PATTERNS.search(src)

        if is_placeholder:
            for attr in _LAZY_ATTRS:
                val = img.get(attr, "")
                if val and val.startswith("http"):
                    img["src"] = val
                    break

            if not img.get("src") or _PLACEHOLDER_PATTERNS.search(img.get("src", "")):
                srcset = img.get("srcset", "")
                if srcset:
                    best = _parse_srcset_best(srcset)
                    if best:
                        img["src"] = best

    for noscript in soup.find_all("noscript"):
        noscript_img = noscript.find("img")
        if noscript_img and noscript_img.get("src"):
            prev = noscript.find_previous_sibling("img")
            if prev:
                prev["src"] = noscript_img["src"]
                noscript.decompose()

    return str(soup)


def _extract_with_trafilatura(html: str, url: str | None = None) -> str | None:
    """用 trafilatura 提取正文，输出 Markdown"""
    import trafilatura

    html = _fix_lazy_images(html)

    result = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_tables=True,
        include_comments=False,
        include_formatting=True,
        favor_recall=True,
    )
    return result


def _detect_anti_scraping(html: str, plain_text: str) -> str | None:
    """检测反爬/拦截页面，返回原因字符串或 None（正常）"""
    # 纯文本太短，高度可疑
    if len(plain_text.strip()) < 50:
        return "content_too_short"

    for pattern, reason in _BLOCKED_PAGE_PATTERNS:
        if pattern.search(html) or pattern.search(plain_text):
            return reason

    return None


def _compare_quality(enriched_text: str, original_text: str) -> dict:
    """对比 enriched 与 original 内容质量，决定是否采用 enriched"""
    enriched_len = len(enriched_text.strip())
    original_len = len(original_text.strip())
    result = {"enriched_len": enriched_len, "original_len": original_len}

    if enriched_len < 100:
        result["use_enriched"] = False
        result["reason"] = f"enriched too short ({enriched_len} chars)"
        return result

    if original_len > 0 and enriched_len < original_len * 0.5:
        result["use_enriched"] = False
        result["reason"] = f"enriched shrunk to {enriched_len}/{original_len} ({enriched_len*100//original_len}%)"
        return result

    if original_len >= 50 and enriched_len > original_len * 20:
        result["use_enriched"] = False
        result["reason"] = f"noise inflation: {enriched_len}/{original_len} ({enriched_len//original_len}x), likely page noise"
        return result

    result["use_enriched"] = True
    result["reason"] = "enriched passed quality check"
    return result


def _fetch_with_browserless(url: str, browserless_url: str, timeout: int = 60) -> str:
    """使用 Browserless 渲染 JS 页面，返回原始 HTML（由调用方统一提取）"""
    import httpx

    endpoint = f"{browserless_url.rstrip('/')}/content"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            endpoint,
            json={"url": url},
            params={"waitFor": "networkidle0"},
        )
        resp.raise_for_status()
        return resp.text


async def _extract_with_crawl4ai(url: str) -> str | None:
    """用 Crawl4AI 提取网页正文，通过 CDP 连接 Browserless，返回 fit_markdown"""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        logger.warning("[crawl4ai] crawl4ai not installed, skipping")
        return None

    from app.core.config import settings

    browser_config = BrowserConfig(cdp_url=settings.CRAWL4AI_CDP_URL)
    run_config = CrawlerRunConfig(
        word_count_threshold=100,
    )

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=run_config),
                timeout=45,
            )
            if result and result.success:
                md = None
                if result.markdown and hasattr(result.markdown, "fit_markdown"):
                    md = result.markdown.fit_markdown
                if not md and result.markdown and hasattr(result.markdown, "raw_markdown"):
                    md = result.markdown.raw_markdown
                if not md and isinstance(result.markdown, str):
                    md = result.markdown
                return md
            else:
                logger.warning(f"[crawl4ai] Crawl failed for {url}: {getattr(result, 'error_message', 'unknown')}")
                return None
    except asyncio.TimeoutError:
        logger.warning(f"[crawl4ai] Timeout (45s) for {url}")
        return None
    except Exception as e:
        logger.warning(f"[crawl4ai] Failed for {url}: {e}")
        return None


# ============ 异步封装（用于 API 端点并行调用） ============

async def fetch_l1_http(url: str) -> tuple[str | None, str | None]:
    """L1: async httpx GET -> trafilatura -> (markdown, error)"""
    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "lxml")
        plain_text = soup.get_text(separator="\n", strip=True)

        block_reason = _detect_anti_scraping(html, plain_text)
        if block_reason:
            return None, f"anti-scraping detected: {block_reason}"

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _extract_with_trafilatura, html, url)

        if result and len(result.strip()) >= 100:
            return result, None
        return None, f"content too short ({len(result) if result else 0} chars)"
    except httpx.HTTPStatusError as e:
        return None, f"HTTP {e.response.status_code}"
    except Exception as e:
        return None, str(e)


async def fetch_crawl4ai(url: str) -> tuple[str | None, str | None]:
    """Crawl4AI: CDP -> (markdown, error)"""
    try:
        result = await _extract_with_crawl4ai(url)
        if result and len(result.strip()) >= 100:
            return result, None
        return None, f"content too short ({len(result) if result else 0} chars)"
    except Exception as e:
        return None, str(e)


async def fetch_l3_browserless(url: str) -> tuple[str | None, str | None]:
    """L3: async httpx POST to Browserless -> trafilatura -> (markdown, error)"""
    import httpx
    from bs4 import BeautifulSoup
    from app.core.config import settings

    try:
        endpoint = f"{settings.BROWSERLESS_URL.rstrip('/')}/content"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                endpoint,
                json={"url": url},
                params={"waitFor": "networkidle0"},
            )
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "lxml")
        plain_text = soup.get_text(separator="\n", strip=True)

        block_reason = _detect_anti_scraping(html, plain_text)
        if block_reason:
            return None, f"anti-scraping detected: {block_reason}"

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _extract_with_trafilatura, html, url)

        if result and len(result.strip()) >= 100:
            return result, None
        return None, f"content too short ({len(result) if result else 0} chars)"
    except httpx.HTTPStatusError as e:
        return None, f"HTTP {e.response.status_code}"
    except Exception as e:
        return None, str(e)


async def _timed_fetch(label: str, level: str, coro) -> dict:
    """包装一个 fetch 协程，计时并捕获异常"""
    start = time.monotonic()
    try:
        content, error = await coro
        elapsed = round(time.monotonic() - start, 2)
        return {
            "level": level,
            "label": label,
            "success": content is not None,
            "content": content,
            "content_length": len(content) if content else 0,
            "elapsed_seconds": elapsed,
            "error": error,
        }
    except Exception as e:
        elapsed = round(time.monotonic() - start, 2)
        return {
            "level": level,
            "label": label,
            "success": False,
            "content": None,
            "content_length": 0,
            "elapsed_seconds": elapsed,
            "error": str(e),
        }


async def enrich_compare(url: str) -> list[dict]:
    """并行运行三级抓取，返回对比结果列表"""
    results = await asyncio.gather(
        _timed_fetch("L1 HTTP + Trafilatura", "l1", fetch_l1_http(url)),
        _timed_fetch("Crawl4AI (CDP)", "crawl4ai", fetch_crawl4ai(url)),
        _timed_fetch("L3 Browserless + Trafilatura", "l3", fetch_l3_browserless(url)),
    )
    return list(results)
