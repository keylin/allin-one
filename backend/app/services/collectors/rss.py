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
from app.models.content import SourceConfig, ContentItem, ContentStatus, MediaItem
from app.services.collectors.base import BaseCollector
from app.services.collectors.utils import resolve_rss_feed_url
from app.services.media_detection import detect_media_for_content

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

        # 预取本源已有 URL 集合（一次查询），过渡期安全网
        existing_urls = set(
            url for (url,) in db.query(ContentItem.url)
            .filter(ContentItem.source_id == source.id, ContentItem.url.isnot(None))
            .all()
        )

        new_items = []
        for entry in feed.entries:
            url = self._fix_link(entry.get("link"))
            if url and url in existing_urls:
                continue  # URL 已存在，跳过

            external_id = self._extract_external_id(entry)
            raw_dict = self._entry_to_dict(entry)
            item = ContentItem(
                source_id=source.id,
                title=entry.get("title", "Untitled")[:500],
                external_id=external_id,
                url=url,
                author=entry.get("author"),
                raw_data=json.dumps(raw_dict, ensure_ascii=False),
                status=ContentStatus.PENDING.value,
                published_at=self._parse_published(entry),
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                    # 检测媒体，创建 pending MediaItem
                    for det in detect_media_for_content(url, raw_dict):
                        db.add(MediaItem(
                            content_id=item.id,
                            media_type=det.media_type,
                            original_url=det.original_url,
                            status="pending",
                        ))
                new_items.append(item)
            except IntegrityError:
                pass  # SAVEPOINT 已自动回滚，MediaItem 也一起回滚

        if new_items:
            db.commit()
        logger.info(
            f"[RSSCollector] {source.name}: {len(new_items)} new / {len(feed.entries)} total entries"
        )
        return new_items

    def _resolve_feed_url(self, source: SourceConfig) -> str | None:
        """解析 Feed URL（调用共享工具）"""
        try:
            return resolve_rss_feed_url(source, settings.RSSHUB_URL)
        except ValueError as e:
            logger.error(f"Failed to resolve feed URL: {e}")
            raise

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
        eid = entry.get("link") or entry.get("id") or entry.get("title", "")
        if not eid:
            eid = json.dumps(entry, sort_keys=True, default=str)
        return hashlib.md5(eid.encode()).hexdigest()

    def _parse_published(self, entry: dict) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            tp = entry.get(field)
            if tp:
                try:
                    import calendar
                    return datetime.fromtimestamp(calendar.timegm(tp), tz=timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass
        for field in ("published", "updated"):
            val = entry.get(field)
            if val:
                try:
                    return parsedate_to_datetime(val).astimezone(timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass
        return None

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
