"""Miniflux 采集器 — 通过 Miniflux REST API 拉取新条目

Miniflux 负责 RSS 订阅管理和全文提取，本采集器仅拉取结果。
SourceConfig.config_json 示例: {"miniflux_feed_id": 42}
"""

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import SourceConfig, ContentItem, ContentStatus
from app.services.collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class MinifluxCollector(BaseCollector):
    """通过 Miniflux API 拉取新条目"""

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        config = json.loads(source.config_json) if source.config_json else {}
        feed_id = config.get("miniflux_feed_id")
        if not feed_id:
            raise ValueError(f"miniflux_feed_id not configured for source '{source.name}'")

        miniflux_url = config.get("miniflux_url") or settings.MINIFLUX_URL
        api_key = config.get("miniflux_api_key") or settings.MINIFLUX_API_KEY
        if not api_key:
            raise ValueError("MINIFLUX_API_KEY not configured")

        # Fetch unread entries from specific feed
        url = f"{miniflux_url.rstrip('/')}/v1/feeds/{feed_id}/entries"
        params = {"status": "unread", "direction": "desc", "limit": 100}
        headers = {"X-Auth-Token": api_key}

        logger.info(f"[MinifluxCollector] Fetching feed_id={feed_id} from {miniflux_url}")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        entries = data.get("entries", [])
        if not entries:
            logger.info(f"[MinifluxCollector] No unread entries for feed_id={feed_id}")
            return []

        new_items = []
        entry_ids_to_mark = []

        for entry in entries:
            external_id = f"mf:{entry['id']}"
            published_at = self._parse_datetime(entry.get("published_at"))

            item = ContentItem(
                source_id=source.id,
                title=(entry.get("title") or "Untitled")[:500],
                external_id=external_id,
                url=entry.get("url"),
                author=entry.get("author"),
                raw_data=json.dumps(entry, ensure_ascii=False, default=str),
                processed_content=entry.get("content", ""),
                status=ContentStatus.PENDING.value,
                published_at=published_at,
            )
            try:
                with db.begin_nested():
                    db.add(item)
                    db.flush()
                new_items.append(item)
                entry_ids_to_mark.append(entry["id"])
            except IntegrityError:
                pass  # duplicate, skip

        if new_items:
            db.commit()

        # Mark pulled entries as read in Miniflux
        if entry_ids_to_mark:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.put(
                        f"{miniflux_url.rstrip('/')}/v1/entries",
                        headers=headers,
                        json={"entry_ids": entry_ids_to_mark, "status": "read"},
                    )
            except Exception as e:
                logger.warning(f"[MinifluxCollector] Failed to mark entries as read: {e}")

        logger.info(f"[MinifluxCollector] feed_id={feed_id}: {len(new_items)} new items")
        return new_items

    @staticmethod
    def _parse_datetime(dt_str: str | None) -> datetime | None:
        """Parse ISO 8601 datetime string from Miniflux"""
        if not dt_str:
            return None
        try:
            # Miniflux returns ISO 8601 format
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
