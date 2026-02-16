"""Pipeline step: localize_media — 检测并下载内容中的图片/视频/音频"""

import hashlib
import json
import logging
import os
import re

logger = logging.getLogger(__name__)


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


def _handle_localize_media(context: dict) -> dict:
    """媒体本地化 — 检测并下载内容中的图片/视频/音频，创建 MediaItem，改写URL

    处理流程:
    1. 检测内容 URL 是否为视频页面 (bilibili/youtube)
       - 是 → yt-dlp 下载视频+字幕+封面 → 创建 video MediaItem
       - 否 → 扫描 HTML 中的媒体标签
    2. 扫描 <img> → 创建 image MediaItem, 下载, 改写 src
    3. 更新 processed_content
    """
    import httpx
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.content import ContentItem, MediaItem, MediaType
    from app.services.media_detection import url_matches_video_pattern

    content_id = context["content_id"]
    content_url = context.get("content_url", "")

    # Load content
    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if not content:
            return {"status": "skipped", "reason": "content not found"}
        html_content = content.processed_content or ""
        raw_data_json = content.raw_data

    # Check: is the content URL a video page?
    is_video_url = url_matches_video_pattern(content_url)

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
                # 优先更新采集时创建的 pending MediaItem，无则新建
                existing = db.query(MediaItem).filter(
                    MediaItem.content_id == content_id,
                    MediaItem.media_type == MediaType.VIDEO.value,
                    MediaItem.status == "pending",
                ).first()
                if existing:
                    existing.original_url = content_url
                    existing.local_path = video_path
                    existing.filename = os.path.basename(video_path) if video_path else None
                    existing.status = "downloaded" if video_path else "failed"
                    existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
                else:
                    db.add(MediaItem(
                        content_id=content_id,
                        media_type=MediaType.VIDEO.value,
                        original_url=content_url,
                        local_path=video_path,
                        filename=os.path.basename(video_path) if video_path else None,
                        status="downloaded" if video_path else "failed",
                        metadata_json=json.dumps(metadata, ensure_ascii=False),
                    ))

                # Update content title and published_at from video info
                content = db.get(ContentItem, content_id)
                if content:
                    if info.get("title"):
                        content.title = info["title"]
                    upload_date = info.get("upload_date")
                    if upload_date and not content.published_at:
                        try:
                            from datetime import datetime
                            content.published_at = datetime.strptime(upload_date, "%Y%m%d")
                        except ValueError:
                            pass
                    # Set processed_content to video description
                    desc = info.get("description", "")
                    if desc:
                        content.processed_content = desc

                db.commit()

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
            # 更新已有 pending MediaItem 或新建 failed 记录
            with SessionLocal() as db:
                existing = db.query(MediaItem).filter(
                    MediaItem.content_id == content_id,
                    MediaItem.media_type == MediaType.VIDEO.value,
                    MediaItem.status == "pending",
                ).first()
                if existing:
                    existing.status = "failed"
                    existing.metadata_json = json.dumps({"error": str(e)[:200]})
                else:
                    db.add(MediaItem(
                        content_id=content_id,
                        media_type=MediaType.VIDEO.value,
                        original_url=content_url,
                        status="failed",
                        metadata_json=json.dumps({"error": str(e)[:200]}),
                    ))
                db.commit()
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
                db.commit()

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
                db.commit()

    logger.info(f"[localize_media] content={content_id}: {images_downloaded} images downloaded")
    return result
