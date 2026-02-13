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
    """抓取全文 — L1 HTTP + readability，失败时降级到 L2 Browserless"""
    config = context["step_config"]
    url = context["content_url"]
    if not url:
        return {"status": "skipped", "reason": "no url"}

    logger.info(f"[enrich_content] url={url}")

    import httpx
    from readability import Document
    from bs4 import BeautifulSoup

    clean_html = ""
    method = "L1_HTTP"

    # L1: 尝试普通 HTTP 抓取
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        doc = Document(html)
        readable_html = doc.summary()

        # 检查内容是否太短（可能是 JS 渲染页面）
        soup = BeautifulSoup(readable_html, "lxml")
        plain_text = soup.get_text(separator="\n", strip=True)
        if len(plain_text.strip()) < 100:
            logger.warning(f"[enrich_content] L1 content too short ({len(plain_text)} chars), trying L2")
            clean_html = ""  # 清空，准备升级到 L2
        else:
            clean_html = _sanitize_html(readable_html)
    except Exception as e:
        logger.warning(f"[enrich_content] L1 failed: {e}, trying L2")
        clean_html = ""

    # L2: 如果 L1 失败或内容太短，使用 Browserless 渲染
    if not clean_html:
        try:
            from app.core.config import settings
            clean_html = _fetch_with_browserless(url, settings.BROWSERLESS_URL)
            method = "L2_Browserless"
            logger.info(f"[enrich_content] L2 succeeded, html_length={len(clean_html)}")
        except Exception as e:
            logger.error(f"[enrich_content] L2 also failed: {e}")
            if not clean_html:
                raise Exception(f"Both L1 and L2 failed for {url}")

    # 更新 content.processed_content（存储清理后的 HTML）
    from app.core.database import SessionLocal
    from app.models.content import ContentItem
    with SessionLocal() as db:
        content = db.get(ContentItem, context["content_id"])
        if content:
            content.processed_content = clean_html
            db.commit()

    return {"status": "enriched", "text_length": len(clean_html), "method": method}


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


def _fetch_with_browserless(url: str, browserless_url: str, timeout: int = 60) -> str:
    """使用 Browserless 渲染 JS 页面并提取清理后的 HTML"""
    import httpx
    from readability import Document

    # Browserless API: POST /content with JSON {url}
    endpoint = f"{browserless_url.rstrip('/')}/content"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            endpoint,
            json={"url": url},
            params={"waitFor": "networkidle0"},  # 等待网络空闲
        )
        resp.raise_for_status()
        html = resp.text

    # 用 Readability 提取正文，再用白名单清理
    doc = Document(html)
    readable_html = doc.summary()
    return _sanitize_html(readable_html)


def _handle_download_video(context: dict) -> dict:
    """下载视频 — yt-dlp"""
    config = context["step_config"]
    quality = config.get("quality", "1080p")
    url = context["content_url"]
    if not url:
        raise ValueError("No URL for video download")

    logger.info(f"[download_video] quality={quality}, url={url}")

    from app.core.config import settings
    import yt_dlp

    output_dir = os.path.join(settings.MEDIA_DIR, context["content_id"])
    os.makedirs(output_dir, exist_ok=True)

    quality_map = {
        "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
        "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "best": "bestvideo+bestaudio/best",
    }

    ydl_opts = {
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "format": quality_map.get(quality, quality_map["1080p"]),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["zh", "en", "zh-Hans", "zh-Hant"],
        "writethumbnail": True,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # 查找下载的文件
    video_path = None
    subtitle_path = None
    thumbnail_path = None
    for f in os.listdir(output_dir):
        full = os.path.join(output_dir, f)
        if f.endswith((".mp4", ".webm", ".mkv")):
            video_path = full
        elif f.endswith((".srt", ".vtt", ".ass")):
            if subtitle_path is None:
                subtitle_path = full
        elif f.endswith((".jpg", ".jpeg", ".png", ".webp")):
            thumbnail_path = full

    # 封面兜底: yt-dlp 未下载到封面时，用 ffmpeg 从视频截取
    if not thumbnail_path and video_path:
        thumbnail_path = _extract_thumbnail_ffmpeg(video_path, output_dir)

    platform = "youtube" if "youtube" in url or "youtu.be" in url else "bilibili" if "bilibili" in url else "other"

    # 回写 ContentItem 的标题和发布时间
    upload_date = info.get("upload_date")  # yt-dlp 返回 "YYYYMMDD" 格式
    from app.core.database import SessionLocal
    from app.models.content import ContentItem
    from datetime import datetime, timezone
    with SessionLocal() as db:
        content = db.get(ContentItem, context["content_id"])
        if content:
            if info.get("title"):
                content.title = info["title"]
            if upload_date and not content.published_at:
                try:
                    content.published_at = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            db.commit()

    return {
        "status": "downloaded",
        "platform": platform,
        "file_path": video_path or "",
        "subtitle_path": subtitle_path or "",
        "thumbnail_path": thumbnail_path or "",
        "title": info.get("title", ""),
        "duration": info.get("duration"),
        "width": info.get("width"),
        "height": info.get("height"),
        "upload_date": upload_date or "",
    }


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
            logger.info(f"[download_video] Thumbnail extracted via ffmpeg: {thumbnail_path}")
            return thumbnail_path
    except Exception as e:
        logger.warning(f"[download_video] ffmpeg thumbnail extraction failed: {e}")
    return None


def _handle_extract_audio(context: dict) -> dict:
    """音频提取 — FFmpeg"""
    video_path = context["previous_steps"].get("download_video", {}).get("file_path", "")
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
    download_output = context["previous_steps"].get("download_video", {})
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
                db.commit()

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
                db.commit()

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
            db.commit()

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
            db.commit()

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


# step_type → handler
STEP_HANDLERS = {
    "enrich_content": _handle_enrich_content,
    "download_video": _handle_download_video,
    "extract_audio": _handle_extract_audio,
    "transcribe_content": _handle_transcribe_content,
    "translate_content": _handle_translate_content,
    "analyze_content": _handle_analyze_content,
    "publish_content": _handle_publish_content,
}
