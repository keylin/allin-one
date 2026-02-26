"""共享 upsert 逻辑 — 供 API 路由和 Worker 任务共用"""

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.content import ContentItem, ContentStatus, MediaItem, SourceConfig
from app.models.ebook import ReadingProgress, BookAnnotation
from app.services.media_detection import detect_media_for_content

logger = logging.getLogger(__name__)


def upsert_videos(db: Session, source: SourceConfig, videos: list[dict]) -> dict:
    """批量 upsert 视频数据，返回统计

    videos 条目格式同 VideoSyncRequest.videos (dict 化后)
    返回: {"new_videos": int, "updated_videos": int}
    """
    platform_key = source.source_type.removeprefix("sync.")
    new_videos = 0
    updated_videos = 0

    for video_data in videos:
        external_id = video_data.get("external_id") or video_data.get("bvid", "")
        if not external_id:
            continue

        content = db.query(ContentItem).filter(
            ContentItem.source_id == source.id,
            ContentItem.external_id == external_id,
        ).first()

        is_new = content is None
        if is_new:
            content = ContentItem(
                id=uuid.uuid4().hex,
                source_id=source.id,
                external_id=external_id,
                title=video_data.get("title", ""),
                author=video_data.get("author"),
                url=video_data.get("url") or f"https://www.bilibili.com/video/{external_id}",
                status=ContentStatus.READY.value,
            )
            db.add(content)
            new_videos += 1
        else:
            content.title = video_data.get("title", content.title)
            if video_data.get("author"):
                content.author = video_data["author"]
            if video_data.get("url"):
                content.url = video_data["url"]
            content.updated_at = utcnow()
            updated_videos += 1

        # Store complete original data in raw_data
        raw = {**video_data, "source": platform_key}
        content.raw_data = json.dumps(raw, ensure_ascii=False)

        # published_at
        if video_data.get("published_at"):
            try:
                from datetime import datetime
                content.published_at = datetime.fromisoformat(
                    video_data["published_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

        db.flush()

        # --- Upsert MediaItems (auto-detect from URL) ---
        content_url = video_data.get("url") or f"https://www.bilibili.com/video/{external_id}"
        detected = detect_media_for_content(content_url, video_data.get("extra"))
        if not detected and video_data.get("playback_position", 0) > 0:
            logger.warning(
                "upsert_videos: no media detected for %s (external_id=%s), playback_position=%s will not be stored",
                content_url, external_id, video_data["playback_position"],
            )

        # Build metadata for media items
        media_meta = {}
        if video_data.get("cover_url"):
            media_meta["cover_url"] = video_data["cover_url"]
        if video_data.get("duration") is not None:
            media_meta["duration"] = video_data["duration"]
        meta_json = json.dumps(media_meta, ensure_ascii=False) if media_meta else None

        for det in detected:
            media = db.query(MediaItem).filter(
                MediaItem.content_id == content.id,
                MediaItem.media_type == det.media_type,
            ).first()

            if not media:
                media = MediaItem(
                    id=uuid.uuid4().hex,
                    content_id=content.id,
                    media_type=det.media_type,
                    status="pending",
                    original_url=det.original_url,
                    metadata_json=meta_json,
                )
                db.add(media)
            else:
                if media_meta:
                    existing_meta = {}
                    if media.metadata_json:
                        try:
                            existing_meta = json.loads(media.metadata_json)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    existing_meta.update(media_meta)
                    media.metadata_json = json.dumps(existing_meta, ensure_ascii=False)

            # playback_position → MediaItem (video/audio only)
            if det.media_type in ("video", "audio") and video_data.get("playback_position", 0) > 0:
                media.playback_position = video_data["playback_position"]

    # Update source last_collected_at
    source.last_collected_at = utcnow()
    db.commit()

    return {"new_videos": new_videos, "updated_videos": updated_videos}


def upsert_ebooks(db: Session, source: SourceConfig, books: list[dict]) -> dict:
    """批量 upsert 电子书数据，返回统计

    books 条目格式同 EbookSyncRequest.books (dict 化后)
    返回: {"new_books": int, "updated_books": int, "new_annotations": int,
            "updated_annotations": int, "deleted_annotations": int}
    """
    platform_key = source.source_type.removeprefix("sync.")
    new_books = 0
    updated_books = 0
    new_annotations = 0
    updated_annotations = 0
    deleted_annotations = 0

    for book_data in books:
        external_id = book_data.get("external_id") or book_data.get("asset_id", "")
        if not external_id:
            continue

        # --- Upsert ContentItem ---
        content = db.query(ContentItem).filter(
            ContentItem.source_id == source.id,
            ContentItem.external_id == external_id,
        ).first()

        is_new_book = content is None
        if is_new_book:
            content = ContentItem(
                id=uuid.uuid4().hex,
                source_id=source.id,
                external_id=external_id,
                title=book_data.get("title", ""),
                author=book_data.get("author"),
                status=ContentStatus.READY.value,
                url=f"{platform_key}://asset/{external_id}",
            )
            db.add(content)
            new_books += 1
        else:
            content.title = book_data.get("title", content.title)
            content.author = book_data.get("author", content.author)
            content.updated_at = utcnow()
            updated_books += 1

        # Store complete original data in raw_data
        raw = {**book_data, "source": platform_key}
        # Exclude annotations from raw_data (stored separately)
        raw.pop("annotations", None)
        content.raw_data = json.dumps(raw, ensure_ascii=False)

        db.flush()

        # --- Upsert MediaItem (virtual ebook) ---
        media = db.query(MediaItem).filter(
            MediaItem.content_id == content.id,
            MediaItem.media_type == "ebook",
        ).first()

        if not media:
            media = MediaItem(
                id=uuid.uuid4().hex,
                content_id=content.id,
                media_type="ebook",
                status="pending",
                original_url=f"{platform_key}://{external_id}",
            )
            db.add(media)

        # --- Upsert ReadingProgress ---
        progress = db.query(ReadingProgress).filter(
            ReadingProgress.content_id == content.id,
        ).first()

        reading_progress = book_data.get("reading_progress", 0)
        if not progress:
            progress = ReadingProgress(
                content_id=content.id,
                progress=reading_progress,
            )
            db.add(progress)
        else:
            progress.progress = reading_progress
            progress.updated_at = utcnow()

        # --- Upsert Annotations ---
        for ann_data in book_data.get("annotations", []):
            ann_id = ann_data.get("id", "")
            if not ann_id:
                continue

            existing_ann = db.query(BookAnnotation).filter(
                BookAnnotation.content_id == content.id,
                BookAnnotation.external_id == ann_id,
            ).first()

            if ann_data.get("is_deleted"):
                if existing_ann:
                    db.delete(existing_ann)
                    deleted_annotations += 1
                continue

            if existing_ann:
                existing_ann.selected_text = ann_data.get("selected_text")
                existing_ann.note = ann_data.get("note")
                existing_ann.color = ann_data.get("color", "yellow")
                existing_ann.type = ann_data.get("type", "highlight")
                existing_ann.location = ann_data.get("chapter")
                existing_ann.updated_at = utcnow()
                updated_annotations += 1
            else:
                new_ann = BookAnnotation(
                    id=uuid.uuid4().hex,
                    content_id=content.id,
                    external_id=ann_id,
                    selected_text=ann_data.get("selected_text"),
                    note=ann_data.get("note"),
                    color=ann_data.get("color", "yellow"),
                    type=ann_data.get("type", "highlight"),
                    location=ann_data.get("chapter"),
                )
                if ann_data.get("created_at"):
                    try:
                        from datetime import datetime
                        new_ann.created_at = datetime.fromisoformat(
                            ann_data["created_at"].replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except (ValueError, AttributeError):
                        pass
                db.add(new_ann)
                new_annotations += 1

    # Update source last_collected_at
    source.last_collected_at = utcnow()
    db.commit()

    return {
        "new_books": new_books,
        "updated_books": updated_books,
        "new_annotations": new_annotations,
        "updated_annotations": updated_annotations,
        "deleted_annotations": deleted_annotations,
    }


def upsert_bookmarks(db: Session, source: SourceConfig, bookmarks: list[dict]) -> dict:
    """批量 upsert 书签数据，返回统计

    bookmarks 条目格式同 BookmarkSyncRequest.bookmarks (dict 化后)
    返回: {"new_bookmarks": int, "updated_bookmarks": int}
    """
    new_bookmarks = 0
    updated_bookmarks = 0

    for bm in bookmarks:
        url = bm.get("url", "").strip()
        if not url:
            continue

        content = db.query(ContentItem).filter(
            ContentItem.source_id == source.id,
            ContentItem.url == url,
        ).first()

        is_new = content is None
        if is_new:
            content = ContentItem(
                id=uuid.uuid4().hex,
                source_id=source.id,
                external_id=uuid.uuid5(uuid.NAMESPACE_URL, url).hex,
                title=bm.get("title") or url,
                url=url,
                status=ContentStatus.READY.value,
            )
            db.add(content)
            new_bookmarks += 1
        else:
            if bm.get("title"):
                content.title = bm["title"]
            content.updated_at = utcnow()
            updated_bookmarks += 1

        raw = {
            "url": url,
            "title": bm.get("title") or url,
            "folder": bm.get("folder"),
            "added_at": bm.get("added_at"),
        }
        content.raw_data = json.dumps(raw, ensure_ascii=False)

        if bm.get("added_at"):
            try:
                from datetime import datetime
                content.published_at = datetime.fromisoformat(
                    bm["added_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                pass

    source.last_collected_at = utcnow()
    db.commit()

    return {"new_bookmarks": new_bookmarks, "updated_bookmarks": updated_bookmarks}
