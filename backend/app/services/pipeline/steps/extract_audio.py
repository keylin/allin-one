"""Pipeline step: extract_audio — FFmpeg 音频提取"""

import logging
import os

logger = logging.getLogger(__name__)


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
