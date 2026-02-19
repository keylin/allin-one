"""Apple Podcasts 采集器

通过 iTunes Lookup API 解析播客 RSS feed URL，再用 feedparser 采集剧集。
仅采集元数据（标题、描述、发布时间、时长、封面），不下载音频。
"""

import json
import hashlib
import logging
import re
import calendar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaItem
from app.services.collectors.base import BaseCollector
from app.services.media_detection import detect_media_for_content

logger = logging.getLogger(__name__)

# Apple Podcasts URL 中提取 podcast ID 的正则
_APPLE_ID_RE = re.compile(r'/id(\d+)')

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"


class PodcastCollector(BaseCollector):
    """Apple Podcasts 采集器"""

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        config = json.loads(source.config_json or "{}")

        feed_url = config.get("feed_url")
        if not feed_url:
            feed_url = await self._resolve_feed_url(source, config, db)

        max_episodes = config.get("max_episodes", 50)

        logger.info(f"[PodcastCollector] Fetching {source.name}: {feed_url}")
        raw_text = await self._fetch_feed(feed_url)

        feed = feedparser.parse(raw_text)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse failed for '{source.name}': {feed.bozo_exception}")

        # 提取播客级元数据
        podcast_meta = self._extract_podcast_meta(feed.feed, config)

        # 预取本源已有 URL 集合
        existing_urls = set(
            url for (url,) in db.query(ContentItem.url)
            .filter(ContentItem.source_id == source.id, ContentItem.url.isnot(None))
            .all()
        )

        new_items = []
        for entry in feed.entries[:max_episodes]:
            url = entry.get("link")
            if url and url in existing_urls:
                continue

            external_id = self._extract_external_id(entry)
            raw_dict = self._entry_to_dict(entry, podcast_meta)
            item = ContentItem(
                source_id=source.id,
                title=entry.get("title", "Untitled")[:500],
                external_id=external_id,
                url=url,
                author=entry.get("author") or feed.feed.get("author"),
                raw_data=json.dumps(raw_dict, ensure_ascii=False),
                status=ContentStatus.PENDING.value,
                published_at=self._parse_published(entry),
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                    for det in detect_media_for_content(url, raw_dict):
                        db.add(MediaItem(
                            content_id=item.id,
                            media_type=det.media_type,
                            original_url=det.original_url,
                            status="pending",
                        ))
                new_items.append(item)
            except IntegrityError:
                pass

        if new_items:
            db.commit()
        logger.info(
            f"[PodcastCollector] {source.name}: {len(new_items)} new / {len(feed.entries)} total entries"
        )
        return new_items

    async def _resolve_feed_url(
        self, source: SourceConfig, config: dict, db: Session
    ) -> str:
        """通过 iTunes Lookup API 解析 RSS feed URL，并缓存到 config_json"""
        podcast_id = config.get("podcast_id")
        if not podcast_id:
            apple_url = config.get("apple_podcast_url", "")
            m = _APPLE_ID_RE.search(apple_url)
            if not m:
                raise ValueError(
                    f"无法从 URL 中提取 podcast ID: {apple_url}"
                )
            podcast_id = m.group(1)

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                ITUNES_LOOKUP_URL, params={"id": podcast_id, "entity": "podcast"}
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        if not results:
            raise ValueError(f"iTunes Lookup 未找到 podcast ID: {podcast_id}")

        podcast_info = results[0]
        feed_url = podcast_info.get("feedUrl")
        if not feed_url:
            raise ValueError(f"iTunes Lookup 返回无 feedUrl: {podcast_id}")

        # 缓存到 config_json
        config["podcast_id"] = podcast_id
        config["feed_url"] = feed_url
        config["podcast_name"] = podcast_info.get("collectionName", "")
        config["artwork_url"] = podcast_info.get("artworkUrl600") or podcast_info.get("artworkUrl100", "")
        source.config_json = json.dumps(config, ensure_ascii=False)
        db.flush()

        logger.info(
            f"[PodcastCollector] Resolved feed for '{source.name}': {feed_url}"
        )
        return feed_url

    async def _fetch_feed(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    def _extract_podcast_meta(self, feed_info: dict, config: dict) -> dict:
        """提取播客级元数据"""
        return {
            "podcast_name": config.get("podcast_name") or feed_info.get("title", ""),
            "podcast_author": feed_info.get("author", ""),
            "podcast_description": (feed_info.get("subtitle") or feed_info.get("summary", ""))[:1000],
            "artwork_url": config.get("artwork_url") or "",
        }

    def _extract_external_id(self, entry: dict) -> str:
        eid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not eid:
            eid = json.dumps(entry, sort_keys=True, default=str)
        return hashlib.md5(eid.encode()).hexdigest()

    def _parse_published(self, entry: dict) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            tp = entry.get(field)
            if tp:
                try:
                    return datetime.fromtimestamp(
                        calendar.timegm(tp), tz=timezone.utc
                    ).replace(tzinfo=None)
                except Exception:
                    pass
        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return (
                        parsedate_to_datetime(val)
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                except Exception:
                    pass
        return None

    def _entry_to_dict(self, entry, podcast_meta: dict) -> dict:
        """将 feedparser entry 转为可序列化 dict，附加 iTunes 扩展字段"""
        result = {}
        for key in ("title", "link", "id", "author", "published", "updated", "summary"):
            if key in entry:
                result[key] = entry[key]
        if "content" in entry:
            result["content"] = [
                {"value": c.get("value", ""), "type": c.get("type", "")}
                for c in entry.get("content", [])
            ]
        # enclosures (音频文件)
        if entry.get("enclosures"):
            result["enclosures"] = [
                {"href": e.get("href"), "type": e.get("type"), "length": e.get("length")}
                for e in entry["enclosures"]
            ]
        if entry.get("media_content"):
            result["media_content"] = [
                {"url": m.get("url"), "medium": m.get("medium"), "type": m.get("type")}
                for m in entry["media_content"]
            ]
        # iTunes 扩展字段
        itunes = {}
        if hasattr(entry, "get"):
            itunes_duration = entry.get("itunes_duration")
            if itunes_duration:
                itunes["duration"] = itunes_duration
            itunes_episode = entry.get("itunes_episode")
            if itunes_episode:
                itunes["episode"] = itunes_episode
            itunes_season = entry.get("itunes_season")
            if itunes_season:
                itunes["season"] = itunes_season
            itunes_image = entry.get("image")
            if itunes_image and isinstance(itunes_image, dict):
                itunes["image"] = itunes_image.get("href", "")
            elif itunes_image and isinstance(itunes_image, str):
                itunes["image"] = itunes_image
            itunes_explicit = entry.get("itunes_explicit")
            if itunes_explicit:
                itunes["explicit"] = itunes_explicit
            itunes_subtitle = entry.get("subtitle")
            if itunes_subtitle:
                itunes["subtitle"] = itunes_subtitle
        if itunes:
            result["itunes"] = itunes

        result["podcast_meta"] = podcast_meta
        return result
