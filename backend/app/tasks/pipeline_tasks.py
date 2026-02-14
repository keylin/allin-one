"""Pipeline 异步任务

每个步骤处理函数接收 context, 其中:
- content_id: 必有, 被处理的 ContentItem
- content_url: 内容原始链接
- step_config: 该步骤的操作配置
- previous_steps: 之前步骤的输出

注意: 没有 fetch_content 处理函数。
数据抓取由 CollectionService + 定时器完成, 不是流水线步骤。
"""

import asyncio
import json
import logging
import os
import re

from app.tasks.huey_instance import huey
import app.models  # noqa: F401 — 确保所有 ORM 模型注册，避免 relationship 解析失败
from app.core.database import commit_with_retry as _commit_with_retry
from app.services.pipeline.executor import PipelineExecutor

logger = logging.getLogger(__name__)
executor = PipelineExecutor()


def _run_async(coro):
    """Run an async coroutine from sync code.

    Uses asyncio.run() in Huey worker (no running loop).
    Falls back to a thread pool when called from FastAPI test endpoint
    (event loop already running).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop (e.g. FastAPI) — run in a new thread to avoid blocking
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _llm_chat(messages, response_format=None):
    """Create LLM client, call chat, close client properly."""
    from app.services.analyzers.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    try:
        return await analyzer.client.chat.completions.create(
            model=analyzer.model,
            messages=messages,
            response_format=response_format,
        )
    finally:
        await analyzer.client.close()


async def _llm_analyze(text, prompt_tpl):
    """Create LLM analyzer, run analysis, close client properly."""
    from app.services.analyzers.llm_analyzer import LLMAnalyzer
    analyzer = LLMAnalyzer()
    try:
        return await analyzer.analyze(text, prompt_tpl)
    finally:
        await analyzer.client.close()


@huey.task(retries=3, retry_delay=30)
def execute_pipeline_step(execution_id: str, step_index: int):
    """通用步骤执行入口 — 根据 step_type 分派

    使用 prepare_step + finish_step 将 5 次事务合并为 2 次。
    """
    try:
        context = executor.prepare_step(execution_id, step_index)
    except ValueError as e:
        logger.error(str(e))
        return

    step_type = context["step_type"]
    logger.info(f"Step [{step_index}] {step_type} starting (pipeline={execution_id})")

    try:
        handler = STEP_HANDLERS.get(step_type)
        if not handler:
            raise ValueError(f"Unknown step_type: {step_type}")

        result = handler(context)

        executor.finish_step(execution_id, step_index, output_data=result)
        logger.info(f"Step [{step_index}] {step_type} completed (pipeline={execution_id})")

    except Exception as e:
        logger.exception(f"Step [{step_index}] {step_type} failed (pipeline={execution_id}): {e}")
        executor.finish_step(execution_id, step_index, error=str(e))


# ============ 步骤处理函数 ============
# 所有函数的输入都是已存在的 ContentItem, 通过 context 获取


def _handle_enrich_content(context: dict) -> dict:
    """抓取全文 — L1 HTTP + trafilatura，失败时降级到 L2 Browserless

    输出 Markdown 格式。质量保障：反爬检测 + enriched vs original 对比 + 自动回退。
    此函数永远不 raise，失败时 fallback 到原始内容。
    """
    url = context["content_url"]
    if not url:
        return {"status": "skipped", "reason": "no url"}

    logger.info(f"[enrich_content] url={url}")

    import httpx
    from bs4 import BeautifulSoup
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    # 1. 提取原始文本（用于对比和回退）
    from app.core.database import SessionLocal
    from app.models.content import ContentItem
    with SessionLocal() as db:
        content = db.get(ContentItem, context["content_id"])
        raw_data_json = content.raw_data if content else None

    original_html = PipelineOrchestrator._extract_raw_text(raw_data_json)
    original_text = PipelineOrchestrator._strip_html(original_html) if original_html else ""

    enriched_md = ""
    method = "L1_HTTP"
    anti_scraping_info = None

    # 2. L1: 尝试普通 HTTP 抓取
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
            logger.warning(f"[enrich_content] L1 anti-scraping detected: {block_reason}, trying L2")
            anti_scraping_info = {"level": "L1", "reason": block_reason}
        else:
            # trafilatura 提取 Markdown
            result = _extract_with_trafilatura(html, url=url)
            if result and len(result.strip()) >= 100:
                enriched_md = result
            else:
                logger.warning(f"[enrich_content] L1 trafilatura content too short ({len(result) if result else 0} chars), trying L2")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            logger.warning(f"[enrich_content] L1 got 403, trying L2")
            anti_scraping_info = {"level": "L1", "reason": "http_403"}
        else:
            logger.warning(f"[enrich_content] L1 HTTP error {e.response.status_code}, trying L2")
    except Exception as e:
        logger.warning(f"[enrich_content] L1 failed: {e}, trying L2")

    # 3. L2: Browserless 渲染
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

    # 4. 质量对比：enriched vs original
    if enriched_md:
        quality = _compare_quality(enriched_md, original_text)
        logger.info(f"[enrich_content] quality check: {quality}")

        if not quality["use_enriched"]:
            logger.warning(f"[enrich_content] enriched rejected: {quality['reason']}, fallback to original")
            with SessionLocal() as db:
                content = db.get(ContentItem, context["content_id"])
                if content and original_html:
                    content.processed_content = original_html
                    _commit_with_retry(db)
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
                _commit_with_retry(db)

        return {
            "status": "enriched",
            "text_length": len(enriched_md),
            "method": method,
            "format": "markdown",
            "quality": quality,
        }

    # 5. 抓取完全失败，回退到原始内容
    if original_html:
        logger.warning(f"[enrich_content] all fetch failed, fallback to original ({len(original_text)} chars)")
        with SessionLocal() as db:
            content = db.get(ContentItem, context["content_id"])
            if content:
                content.processed_content = original_html
                _commit_with_retry(db)
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


_LAZY_ATTRS = ["data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "data-url"]
_PLACEHOLDER_PATTERNS = re.compile(
    r"data:image/|placeholder|spacer|blank\.(gif|png)|1x1|loading.*\.(gif|png|svg)", re.I
)


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

    if original_len < 100:
        result["use_enriched"] = True
        result["reason"] = f"original too short ({original_len} chars), prefer enriched"
        return result

    if enriched_len < original_len * 0.5:
        result["use_enriched"] = False
        result["reason"] = f"enriched shrunk to {enriched_len}/{original_len} ({enriched_len*100//original_len}%)"
        return result

    result["use_enriched"] = True
    result["reason"] = "enriched passed quality check"
    return result


def _fetch_with_browserless(url: str, browserless_url: str, timeout: int = 60) -> str:
    """使用 Browserless 渲染 JS 页面，返回原始 HTML（由调用方统一提取）"""
    import httpx

    # Browserless API: POST /content with JSON {url}
    endpoint = f"{browserless_url.rstrip('/')}/content"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            endpoint,
            json={"url": url},
            params={"waitFor": "networkidle0"},  # 等待网络空闲
        )
        resp.raise_for_status()
        return resp.text


def _extract_thumbnail_ffmpeg(video_path: str, output_dir: str) -> str | None:
    """用 ffmpeg 从视频第 3 秒截取一帧作为封面"""
    import subprocess

    thumbnail_path = os.path.join(output_dir, "thumbnail.jpg")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", "3",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                thumbnail_path,
            ],
            capture_output=True, timeout=30,
        )
        if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
            logger.info(f"[localize_media] Thumbnail extracted via ffmpeg: {thumbnail_path}")
            return thumbnail_path
    except Exception as e:
        logger.warning(f"[localize_media] ffmpeg thumbnail extraction failed: {e}")
    return None


def _handle_extract_audio(context: dict) -> dict:
    """音频提取 — FFmpeg"""
    video_path = context["previous_steps"].get("localize_media", {}).get("file_path", "")
    if not video_path or not os.path.exists(video_path):
        return {"status": "skipped", "reason": "no video file"}

    logger.info(f"[extract_audio] Extracting audio from {video_path}")

    from app.core.config import settings
    import subprocess

    # 准备输出路径
    audio_dir = os.path.join(settings.MEDIA_DIR, "audio", context["content_id"])
    os.makedirs(audio_dir, exist_ok=True)

    # 生成音频文件名（使用 mp3 格式）
    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(audio_dir, f"{video_basename}.mp3")

    try:
        # 使用 FFmpeg 提取音频
        # -i: 输入文件
        # -vn: 禁用视频
        # -acodec libmp3lame: 使用 MP3 编码器
        # -q:a 2: 音质 (0-9, 2 为高质量)
        # -y: 覆盖已存在文件
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",  # 不处理视频
            "-acodec", "libmp3lame",
            "-q:a", "2",  # 高质量
            "-y",  # 覆盖
            audio_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
        )

        if result.returncode != 0:
            logger.error(f"[extract_audio] FFmpeg failed: {result.stderr}")
            raise Exception(f"FFmpeg extraction failed: {result.stderr[:200]}")

        # 检查文件是否生成
        if not os.path.exists(audio_path):
            raise Exception("Audio file not created")

        file_size = os.path.getsize(audio_path)
        logger.info(f"[extract_audio] Extracted: {audio_path} ({file_size} bytes)")

        return {
            "status": "extracted",
            "audio_path": audio_path,
            "file_size": file_size,
            "format": "mp3",
        }

    except subprocess.TimeoutExpired:
        logger.error("[extract_audio] FFmpeg timeout")
        raise Exception("Audio extraction timeout (>5min)")
    except Exception as e:
        logger.error(f"[extract_audio] Failed: {e}")
        raise


def _handle_transcribe_content(context: dict) -> dict:
    """字幕提取 — 优先字幕文件，降级到 Whisper ASR"""
    download_output = context["previous_steps"].get("localize_media", {})
    subtitle_path = download_output.get("subtitle_path", "")

    # 策略 1: 读取 yt-dlp 下载的字幕文件
    if subtitle_path and os.path.exists(subtitle_path):
        logger.info(f"[transcribe_content] Reading subtitle: {subtitle_path}")
        with open(subtitle_path, "r", encoding="utf-8") as f:
            raw_subtitle = f.read()
        text = _parse_subtitle(raw_subtitle)

        from app.core.database import SessionLocal
        from app.models.content import ContentItem
        with SessionLocal() as db:
            content = db.get(ContentItem, context["content_id"])
            if content:
                content.processed_content = text
                _commit_with_retry(db)

        return {"status": "transcribed", "text_length": len(text), "source": "subtitle_file"}

    # 策略 2: 使用 Whisper ASR（需要音频文件）
    audio_path = None

    # 先尝试从 extract_audio 步骤获取
    extract_output = context["previous_steps"].get("extract_audio", {})
    if extract_output.get("audio_path"):
        audio_path = extract_output["audio_path"]
    else:
        # 没有音频，尝试使用视频文件
        video_path = download_output.get("file_path")
        if video_path and os.path.exists(video_path):
            audio_path = video_path  # Whisper 也支持直接处理视频

    if not audio_path or not os.path.exists(audio_path):
        logger.warning("[transcribe_content] No subtitle and no audio/video file for ASR")
        return {"status": "skipped", "reason": "no subtitle file and no audio for ASR"}

    # 使用 Whisper API 进行 ASR
    try:
        text = _transcribe_with_whisper(audio_path)

        from app.core.database import SessionLocal
        from app.models.content import ContentItem
        with SessionLocal() as db:
            content = db.get(ContentItem, context["content_id"])
            if content:
                content.processed_content = text
                _commit_with_retry(db)

        return {"status": "transcribed", "text_length": len(text), "source": "whisper_asr"}

    except Exception as e:
        logger.error(f"[transcribe_content] Whisper ASR failed: {e}")
        return {"status": "failed", "reason": f"ASR error: {str(e)[:100]}"}


def _transcribe_with_whisper(audio_path: str) -> str:
    """使用 Whisper API 进行语音识别

    支持 OpenAI Whisper API 或兼容端点
    """
    from app.core.config import get_llm_config
    from openai import OpenAI

    logger.info(f"[whisper] Transcribing: {audio_path}")

    # 检查文件大小（Whisper API 限制 25MB）
    file_size = os.path.getsize(audio_path)
    max_size = 25 * 1024 * 1024  # 25MB

    if file_size > max_size:
        logger.warning(f"[whisper] File too large ({file_size} bytes), splitting not implemented")
        raise Exception(f"Audio file too large: {file_size} bytes (max 25MB)")

    # 使用 OpenAI client（支持兼容端点）
    cfg = get_llm_config()
    client = OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    )

    try:
        with open(audio_path, "rb") as audio_file:
            # 调用 Whisper API
            transcript = client.audio.transcriptions.create(
                model="whisper-1",  # 或兼容模型名
                file=audio_file,
                language="zh",  # 中文优先，可配置
            )

        text = transcript.text
        logger.info(f"[whisper] Transcribed {len(text)} characters")
        return text

    except Exception as e:
        logger.error(f"[whisper] API call failed: {e}")
        # 如果 Whisper API 不可用，可以降级到本地 whisper.cpp
        # 但这需要额外依赖，暂不实现
        raise


def _parse_subtitle(raw: str) -> str:
    """解析 SRT/VTT 字幕为纯文本"""
    lines = raw.split("\n")
    text_lines = []
    for line in lines:
        line = line.strip()
        # 跳过 SRT 序号行
        if re.match(r"^\d+$", line):
            continue
        # 跳过时间轴行
        if re.match(r"^\d{2}:\d{2}[:.]", line) or "-->" in line:
            continue
        # 跳过 VTT header
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        # 移除 HTML 标签
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            text_lines.append(line)
    # 去重相邻重复行
    deduped = []
    for line in text_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return "\n".join(deduped)


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
            _commit_with_retry(db)

    return {"status": "translated", "target_language": target_lang, "text_length": len(translated)}


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
            _commit_with_retry(db)

    return {"status": "analyzed", "result_keys": list(result.keys()) if isinstance(result, dict) else []}


def _handle_publish_content(context: dict) -> dict:
    """消息推送"""
    config = context["step_config"]
    channel = config.get("channel", "none")
    if channel == "none":
        return {"status": "skipped", "reason": "channel=none"}

    content_id = context["content_id"]
    logger.info(f"[publish_content] channel={channel}, content={content_id}")

    if channel == "webhook":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.webhook import publish_webhook

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)
            setting = db.get(SystemSetting, "notify_webhook")
            webhook_url = setting.value if setting else None

        if not webhook_url:
            return {"status": "skipped", "reason": "no webhook URL configured"}

        payload = {
            "title": content.title,
            "url": content.url,
            "summary": (content.processed_content or "")[:500],
            "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
            "source_name": source.name if source else None,
        }

        result = _run_async(publish_webhook(payload, webhook_url))
        return result

    if channel == "email":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.email import publish_email, format_content_email

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)

            # 读取 SMTP 配置
            smtp_host = db.get(SystemSetting, "smtp_host")
            smtp_port = db.get(SystemSetting, "smtp_port")
            smtp_user = db.get(SystemSetting, "smtp_user")
            smtp_password = db.get(SystemSetting, "smtp_password")
            notify_email = db.get(SystemSetting, "notify_email")

        if not all([smtp_host, smtp_user, smtp_password, notify_email]):
            return {"status": "skipped", "reason": "SMTP not configured"}

        email_content = format_content_email({
            "title": content.title,
            "url": content.url,
            "author": content.author,
            "processed_content": content.processed_content,
            "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
        })

        to_emails = [e.strip() for e in notify_email.value.split(",") if e.strip()]
        result = _run_async(publish_email(
            content=email_content,
            smtp_host=smtp_host.value,
            smtp_port=int(smtp_port.value) if smtp_port else 465,
            smtp_user=smtp_user.value,
            smtp_password=smtp_password.value,
            to_emails=to_emails,
        ))
        return result

    if channel == "dingtalk":
        from app.core.database import SessionLocal
        from app.models.content import ContentItem, SourceConfig
        from app.models.system_setting import SystemSetting
        from app.services.publishers.dingtalk import publish_dingtalk, format_content_dingtalk

        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if not content:
                raise ValueError(f"Content not found: {content_id}")

            source = db.get(SourceConfig, content.source_id)
            setting = db.get(SystemSetting, "notify_dingtalk_webhook")
            dingtalk_url = setting.value if setting else None

        if not dingtalk_url:
            return {"status": "skipped", "reason": "DingTalk webhook not configured"}

        dingtalk_content = format_content_dingtalk({
            "title": content.title,
            "url": content.url,
            "author": content.author,
            "processed_content": content.processed_content,
            "analysis_result": json.loads(content.analysis_result) if content.analysis_result else None,
        })

        result = _run_async(publish_dingtalk(
            content=dingtalk_content,
            webhook_url=dingtalk_url,
        ))
        return result

    logger.warning(f"[publish_content] Channel '{channel}' not implemented")
    return {"status": "skipped", "reason": f"channel '{channel}' not implemented"}


def _handle_localize_media(context: dict) -> dict:
    """媒体本地化 — 检测并下载内容中的图片/视频/音频，创建 MediaItem，改写URL

    处理流程:
    1. 检测内容 URL 是否为视频页面 (bilibili/youtube)
       - 是 → yt-dlp 下载视频+字幕+封面 → 创建 video MediaItem
       - 否 → 扫描 HTML 中的媒体标签
    2. 扫描 <img> → 创建 image MediaItem, 下载, 改写 src
    3. 更新 processed_content
    """
    import hashlib
    import httpx
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.content import ContentItem, MediaItem, MediaType

    content_id = context["content_id"]
    content_url = context.get("content_url", "")

    VIDEO_URL_PATTERNS = [
        r'bilibili\.com/video/', r'youtube\.com/watch',
        r'youtu\.be/', r'b23\.tv/',
    ]

    # Load content
    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if not content:
            return {"status": "skipped", "reason": "content not found"}
        html_content = content.processed_content or ""
        raw_data_json = content.raw_data

    # Check: is the content URL a video page?
    is_video_url = False
    if content_url:
        for pattern in VIDEO_URL_PATTERNS:
            if re.search(pattern, content_url):
                is_video_url = True
                break

    result = {
        "status": "done",
        "media_items_created": 0,
        "has_video": False,
        "file_path": "",
        "subtitle_path": "",
        "thumbnail_path": "",
        "duration": None,
    }

    media_dir = os.path.join(settings.MEDIA_DIR, content_id)
    os.makedirs(media_dir, exist_ok=True)

    # ---- 1. Video URL → yt-dlp download ----
    if is_video_url:
        logger.info(f"[localize_media] Video URL detected: {content_url}")
        try:
            import yt_dlp

            quality_map = {
                "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
                "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "best": "bestvideo+bestaudio/best",
            }

            ydl_opts = {
                "outtmpl": os.path.join(media_dir, "%(title)s.%(ext)s"),
                "format": quality_map["1080p"],
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["zh", "en", "zh-Hans", "zh-Hant"],
                "writethumbnail": True,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(content_url, download=True)

            # Find downloaded files
            video_path = None
            subtitle_path = None
            thumbnail_path = None
            for f in os.listdir(media_dir):
                full = os.path.join(media_dir, f)
                if f.endswith((".mp4", ".webm", ".mkv")):
                    video_path = full
                elif f.endswith((".srt", ".vtt", ".ass")):
                    if subtitle_path is None:
                        subtitle_path = full
                elif f.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    thumbnail_path = full

            # Fallback thumbnail via ffmpeg
            if not thumbnail_path and video_path:
                thumbnail_path = _extract_thumbnail_ffmpeg(video_path, media_dir)

            platform = "youtube" if "youtube" in content_url or "youtu.be" in content_url else "bilibili" if "bilibili" in content_url else "other"

            # Create video MediaItem
            metadata = {
                "duration": info.get("duration"),
                "width": info.get("width"),
                "height": info.get("height"),
                "platform": platform,
                "subtitle_path": subtitle_path or "",
                "thumbnail_path": thumbnail_path or "",
            }

            with SessionLocal() as db:
                media_item = MediaItem(
                    content_id=content_id,
                    media_type=MediaType.VIDEO.value,
                    original_url=content_url,
                    local_path=video_path,
                    filename=os.path.basename(video_path) if video_path else None,
                    status="downloaded" if video_path else "failed",
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
                db.add(media_item)

                # Update content title and published_at from video info
                content = db.get(ContentItem, content_id)
                if content:
                    if info.get("title"):
                        content.title = info["title"]
                    upload_date = info.get("upload_date")
                    if upload_date and not content.published_at:
                        try:
                            from datetime import datetime, timezone
                            content.published_at = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
                        except ValueError:
                            pass
                    # Set processed_content to video description
                    desc = info.get("description", "")
                    if desc:
                        content.processed_content = desc

                _commit_with_retry(db)

            result["has_video"] = True
            result["file_path"] = video_path or ""
            result["subtitle_path"] = subtitle_path or ""
            result["thumbnail_path"] = thumbnail_path or ""
            result["duration"] = info.get("duration")
            result["title"] = info.get("title", "")
            result["platform"] = platform
            result["width"] = info.get("width")
            result["height"] = info.get("height")
            result["media_items_created"] += 1

        except Exception as e:
            logger.error(f"[localize_media] Video download failed: {e}")
            # Create failed MediaItem for tracking
            with SessionLocal() as db:
                media_item = MediaItem(
                    content_id=content_id,
                    media_type=MediaType.VIDEO.value,
                    original_url=content_url,
                    status="failed",
                    metadata_json=json.dumps({"error": str(e)[:200]}),
                )
                db.add(media_item)
                _commit_with_retry(db)
            result["media_items_created"] += 1

        return result

    # ---- 2. Non-video: scan HTML for images ----
    # Get HTML content to scan
    if not html_content:
        # Try extracting from raw_data
        if raw_data_json:
            try:
                raw = json.loads(raw_data_json)
                contents = raw.get("content", [])
                if isinstance(contents, list) and contents:
                    html_content = contents[0].get("value", "")
                if not html_content:
                    html_content = raw.get("summary", "")
            except (json.JSONDecodeError, TypeError):
                pass

    if not html_content:
        logger.info(f"[localize_media] No HTML content to scan for {content_id}")
        return result

    soup = BeautifulSoup(html_content, "lxml")
    images_dir = os.path.join(media_dir, "images")
    images_downloaded = 0

    # Scan <img> tags
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:") or src.startswith("/api/media/"):
            continue

        # Skip very small images (likely icons/trackers)
        width = img.get("width", "")
        height = img.get("height", "")
        try:
            if width and int(width) < 32:
                continue
            if height and int(height) < 32:
                continue
        except (ValueError, TypeError):
            pass

        try:
            os.makedirs(images_dir, exist_ok=True)
            url_hash = hashlib.md5(src.encode()).hexdigest()[:12]
            parsed = urlparse(src)
            ext = os.path.splitext(parsed.path)[1] or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
                ext = ".jpg"
            filename = f"{url_hash}{ext}"
            local_path = os.path.join(images_dir, filename)

            # Download image
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(src)
                resp.raise_for_status()
                with open(local_path, "wb") as f:
                    f.write(resp.content)

            # Create MediaItem
            with SessionLocal() as db:
                media_item = MediaItem(
                    content_id=content_id,
                    media_type=MediaType.IMAGE.value,
                    original_url=src,
                    local_path=local_path,
                    filename=filename,
                    status="downloaded",
                    metadata_json=json.dumps({"alt": img.get("alt", "")}),
                )
                db.add(media_item)
                _commit_with_retry(db)

            # Rewrite URL in HTML
            img["src"] = f"/api/media/{content_id}/images/{filename}"
            images_downloaded += 1
            result["media_items_created"] += 1

        except Exception as e:
            logger.warning(f"[localize_media] Failed to download image {src[:80]}: {e}")
            continue

    # Update processed_content with rewritten HTML
    if images_downloaded > 0:
        with SessionLocal() as db:
            content = db.get(ContentItem, content_id)
            if content:
                content.processed_content = str(soup)
                _commit_with_retry(db)

    logger.info(f"[localize_media] content={content_id}: {images_downloaded} images downloaded")
    return result


# step_type → handler
STEP_HANDLERS = {
    "enrich_content": _handle_enrich_content,
    "extract_audio": _handle_extract_audio,
    "transcribe_content": _handle_transcribe_content,
    "translate_content": _handle_translate_content,
    "analyze_content": _handle_analyze_content,
    "publish_content": _handle_publish_content,
    "localize_media": _handle_localize_media,
}
