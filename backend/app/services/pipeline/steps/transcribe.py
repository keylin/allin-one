"""Pipeline step: transcribe_content — 字幕提取 / Whisper ASR"""

import logging
import os
import re

logger = logging.getLogger(__name__)


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
