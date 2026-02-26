"""Pipeline step: localize_media — 检测并下载内容中的图片/视频/音频"""

import hashlib
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
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
    from urllib.parse import urlparse, urljoin
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
        content_is_favorited = content.is_favorited or False
        content_favorited_at = content.favorited_at

    # Check: is the content URL a video page?
    is_video_url = url_matches_video_pattern(content_url)

    result = {
        "status": "done",
        "media_items_created": 0,
        "media_items": [],
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
        # 检查是否应该下载：content.is_favorited=True，或存在 pending+is_favorited 的视频 MediaItem
        should_download_video = content_is_favorited
        if not should_download_video:
            with SessionLocal() as db:
                _fav_video = db.query(MediaItem).filter(
                    MediaItem.content_id == content_id,
                    MediaItem.media_type == MediaType.VIDEO.value,
                    MediaItem.status == "pending",
                    MediaItem.is_favorited == True,
                ).first()
                should_download_video = _fav_video is not None

        if not should_download_video:
            logger.info(f"[localize_media] Skip video download (not favorited): {content_url}")
            result["summary"] = {}
            return result

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
                "ignoreerrors": True,  # 字幕下载失败不中断视频下载
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
                        is_favorited=True,
                        favorited_at=content_favorited_at,
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
            result["media_items"].append({
                "type": "video",
                "status": "downloaded",
                "path": video_path or "",
                "platform": platform,
            })

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
                        is_favorited=True,
                        favorited_at=content_favorited_at,
                    ))
                db.commit()
            result["media_items_created"] += 1
            result["media_items"].append({
                "type": "video",
                "status": "failed",
                "error": str(e)[:100],
            })

        # 视频路径提前返回，也需要汇总
        type_counts = {}
        for mi in result["media_items"]:
            t = mi["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
        result["summary"] = type_counts
        return result

    # ---- 1.5 Audio download ----
    # Download pending audio MediaItems (e.g. podcast episodes)
    # 仅下载已收藏 (is_favorited=True) 且 pending 的音频项
    with SessionLocal() as db:
        audio_items = db.query(MediaItem).filter(
            MediaItem.content_id == content_id,
            MediaItem.media_type == MediaType.AUDIO.value,
            MediaItem.status == "pending",
            MediaItem.is_favorited == True,
        ).all()

    for audio_mi in audio_items:
        audio_url = audio_mi.original_url
        if not audio_url:
            continue
        try:
            audio_dir = os.path.join(media_dir, "audio")
            os.makedirs(audio_dir, exist_ok=True)

            parsed = urlparse(audio_url)
            ext = os.path.splitext(parsed.path)[1] or ".mp3"
            if ext not in (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac"):
                ext = ".mp3"
            url_hash = hashlib.md5(audio_url.encode()).hexdigest()[:12]
            filename = f"{url_hash}{ext}"
            local_path = os.path.join(audio_dir, filename)

            # Stream download (audio files can be tens of MB)
            with httpx.Client(timeout=120, follow_redirects=True, headers=_BROWSER_HEADERS) as client:
                with client.stream("GET", audio_url) as resp:
                    resp.raise_for_status()
                    with open(local_path, "wb") as f:
                        for chunk in resp.iter_bytes(8192):
                            f.write(chunk)

            with SessionLocal() as db:
                mi = db.get(MediaItem, audio_mi.id)
                mi.local_path = local_path
                mi.filename = filename
                mi.status = "downloaded"
                mi.metadata_json = json.dumps({
                    "file_size": os.path.getsize(local_path),
                })
                db.commit()
            result["media_items_created"] += 1
            result["media_items"].append({
                "type": "audio",
                "status": "downloaded",
                "path": local_path,
                "file_size": os.path.getsize(local_path),
            })
            logger.info(f"[localize_media] Audio downloaded: {audio_url[:80]} -> {local_path}")

        except Exception as e:
            logger.warning(f"[localize_media] Audio download failed {audio_url[:80]}: {e}")
            with SessionLocal() as db:
                mi = db.get(MediaItem, audio_mi.id)
                mi.status = "failed"
                mi.metadata_json = json.dumps({"error": str(e)[:200]})
                db.commit()
            result["media_items"].append({
                "type": "audio",
                "status": "failed",
                "url": audio_url[:80],
                "error": str(e)[:100],
            })

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
    # Build download headers with Referer
    dl_headers = {**_BROWSER_HEADERS}
    if content_url:
        parsed_base = urlparse(content_url)
        dl_headers["Referer"] = f"{parsed_base.scheme}://{parsed_base.netloc}/"

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:") or src.startswith("/api/media/"):
            continue

        # Resolve relative / protocol-relative URLs
        if src.startswith("//"):
            src = "https:" + src
        elif not src.startswith(("http://", "https://")):
            if content_url:
                src = urljoin(content_url, src)
            else:
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

            if content_is_favorited:
                # Download image with browser headers + Referer
                with httpx.Client(timeout=15, follow_redirects=True, headers=dl_headers) as client:
                    resp = client.get(src)
                    resp.raise_for_status()
                    with open(local_path, "wb") as f:
                        f.write(resp.content)

                # Create MediaItem (downloaded)
                with SessionLocal() as db:
                    media_item = MediaItem(
                        content_id=content_id,
                        media_type=MediaType.IMAGE.value,
                        original_url=src,
                        local_path=local_path,
                        filename=filename,
                        status="downloaded",
                        metadata_json=json.dumps({"alt": img.get("alt", "")}),
                        is_favorited=True,
                        favorited_at=content_favorited_at,
                    )
                    db.add(media_item)
                    db.commit()

                # Rewrite URL in HTML
                img["src"] = f"/api/media/{content_id}/images/{filename}"
                images_downloaded += 1
                result["media_items_created"] += 1
                result["media_items"].append({
                    "type": "image",
                    "status": "downloaded",
                    "path": local_path,
                })
            else:
                # 内容未收藏：创建 pending MediaItem，不下载
                with SessionLocal() as db:
                    media_item = MediaItem(
                        content_id=content_id,
                        media_type=MediaType.IMAGE.value,
                        original_url=src,
                        local_path=None,
                        filename=filename,
                        status="pending",
                        metadata_json=json.dumps({"alt": img.get("alt", "")}),
                        is_favorited=False,
                    )
                    db.add(media_item)
                    db.commit()
                result["media_items_created"] += 1
                result["media_items"].append({
                    "type": "image",
                    "status": "pending",
                    "url": src[:80],
                })

        except Exception as e:
            logger.warning(f"[localize_media] Failed to download image {src[:80]}: {e}")
            continue

    # Always save processed_content (even if no images downloaded, preserves HTML structure)
    with SessionLocal() as db:
        content = db.get(ContentItem, content_id)
        if content:
            content.processed_content = str(soup)
            db.commit()

    # 按类型汇总
    type_counts = {}
    for mi in result["media_items"]:
        t = mi["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    result["summary"] = type_counts

    logger.info(f"[localize_media] content={content_id}: {images_downloaded} images downloaded")
    return result
