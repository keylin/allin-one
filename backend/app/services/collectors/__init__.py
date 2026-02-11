"""采集服务 — 调度分发"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, CollectionRecord
from app.services.collectors.rss import RSSCollector
from app.services.collectors.web_scraper import ScraperCollector

logger = logging.getLogger(__name__)

_rss_collector = RSSCollector()
_scraper_collector = ScraperCollector()

COLLECTOR_MAP = {
    "rss.hub": _rss_collector,
    "rss.standard": _rss_collector,
    "web.scraper": _scraper_collector,
}

_UNIMPLEMENTED_TYPES = {
    "api.akshare", "file.upload",
    "account.bilibili", "account.generic",
    "user.note", "system.notification",
}


async def collect_source(source: SourceConfig, db: Session) -> list[ContentItem]:
    """按 source_type 选择 collector 执行采集，创建 CollectionRecord"""
    record = CollectionRecord(
        source_id=source.id,
        status="running",
    )
    db.add(record)
    db.flush()

    try:
        collector = COLLECTOR_MAP.get(source.source_type)

        if not collector:
            if source.source_type in _UNIMPLEMENTED_TYPES:
                logger.warning(f"[collect] Collector not implemented for {source.source_type}, skipping")
            else:
                logger.error(f"[collect] Unknown source_type: {source.source_type}")
            record.status = "completed"
            record.items_found = 0
            record.items_new = 0
            record.completed_at = datetime.now(timezone.utc)
            db.commit()
            return []

        new_items = await collector.collect(source, db)

        record.status = "completed"
        record.items_found = len(new_items)
        record.items_new = len(new_items)
        record.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"[collect] {source.name}: found {len(new_items)} new items")
        return new_items

    except Exception as e:
        record.status = "failed"
        record.error_message = str(e)[:500]
        record.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception(f"[collect] Failed for {source.name}: {e}")
        raise
