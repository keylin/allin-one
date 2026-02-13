"""RSS 采集器 — 统一处理 rss.hub 和 rss.standard"""

import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaType
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """统一 RSS/Atom 采集器，支持 RSSHub 和标准 RSS"""

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        feed_url = self._resolve_feed_url(source)
        if not feed_url:
            raise ValueError(f"No feed URL configured for source '{source.name}'")

        logger.info(f"[RSSCollector] Fetching {source.name}: {feed_url}")
        raw_text = await self._fetch_feed(feed_url)

        feed = feedparser.parse(raw_text)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse failed for '{source.name}': {feed.bozo_exception}")

        new_items = []
        for entry in feed.entries:
            external_id = self._extract_external_id(entry)
            item = ContentItem(
                source_id=source.id,
                title=entry.get("title", "Untitled")[:500],
                external_id=external_id,
                url=self._fix_link(entry.get("link")),
                author=entry.get("author"),
                raw_data=json.dumps(self._entry_to_dict(entry), ensure_ascii=False),
                status=ContentStatus.PENDING.value,
                media_type=self._detect_media_type(entry, source.media_type),
                published_at=self._parse_published(entry),
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                new_items.append(item)
            except IntegrityError:
                pass  # SAVEPOINT 已自动回滚，外层事务不受影响

        if new_items:
            db.commit()
        logger.info(
            f"[RSSCollector] {source.name}: {len(new_items)} new / {len(feed.entries)} total entries"
        )
        return new_items

    def _resolve_feed_url(self, source: SourceConfig) -> str | None:
        if source.source_type == "rss.hub":
            # 优先从 config_json 读 rsshub_route
            config = json.loads(source.config_json) if source.config_json else {}
            route = config.get("rsshub_route") or ""
            # url 为路由路径时也当作 route
            if not route and source.url and not source.url.startswith(("http://", "https://")):
                route = source.url
            if route:
                base = settings.RSSHUB_URL.rstrip("/")
                if not route.startswith("/"):
                    route = f"/{route}"
                return f"{base}{route}"
            return source.url
        else:
            return source.url

    async def _fetch_feed(self, url: str) -> str:
        """抓取 feed 内容，失败时抛异常"""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def _fix_link(link: str | None) -> str | None:
        """修正畸形 URL — 如 http://example.com/https://real.url/path"""
        if not link:
            return link
        # 检测 scheme://host/https:// 或 scheme://host/http:// 模式
        m = re.match(r'https?://[^/]+/(https?://.*)', link)
        if m:
            return m.group(1)
        return link

    def _extract_external_id(self, entry: dict) -> str:
        """提取或生成唯一 ID"""
        eid = entry.get("id") or entry.get("link") or entry.get("title", "")
        if not eid:
            eid = json.dumps(entry, sort_keys=True, default=str)
        return hashlib.md5(eid.encode()).hexdigest()

    def _parse_published(self, entry: dict) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            tp = entry.get(field)
            if tp:
                try:
                    import calendar
                    return datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc)
                except Exception:
                    pass
        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return parsedate_to_datetime(val).astimezone(timezone.utc)
                except Exception:
                    pass
        return None

    def _detect_media_type(self, entry: dict, source_default: str) -> str:
        """从 RSS entry 元数据推断媒体类型"""
        # 1. enclosures MIME type (feedparser 解析)
        for enc in entry.get("enclosures", []):
            mime = (enc.get("type") or "").lower()
            if mime.startswith("video/"):
                return MediaType.VIDEO.value
            if mime.startswith("audio/"):
                return MediaType.AUDIO.value

        # 2. media:content 元素
        for mc in entry.get("media_content", []):
            medium = (mc.get("medium") or "").lower()
            if medium == "video":
                return MediaType.VIDEO.value
            if medium == "audio":
                return MediaType.AUDIO.value

        # 3. URL 特征匹配
        link = entry.get("link", "")
        if any(p in link for p in ["bilibili.com/video/", "youtube.com/watch", "youtu.be/"]):
            return MediaType.VIDEO.value

        # 4. 回退到数据源默认
        return source_default or MediaType.TEXT.value

    def _entry_to_dict(self, entry) -> dict:
        """将 feedparser entry 转为可序列化 dict"""
        result = {}
        for key in ("title", "link", "id", "author", "published", "updated", "summary"):
            if key in entry:
                result[key] = entry[key]
        if "content" in entry:
            result["content"] = [
                {"value": c.get("value", ""), "type": c.get("type", "")}
                for c in entry.get("content", [])
            ]
        # 保存 enclosures 和 media:content（供路由调试审计）
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
        return result
