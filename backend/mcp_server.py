"""Allin-One MCP Server -- 信息流数据服务

复用 backend ORM 模型，直连 PostgreSQL。
供 Claude Code / Cursor 等 AI CLI 查询个人信息流数据。

传输模式：
- 默认 stdio（本地开发）
- 设置 MCP_TRANSPORT=http 时使用 streamable-http，监听 0.0.0.0:8001（远程部署）
"""

import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta

# 确保 backend/ 在 sys.path 中，使 import app.* 可用
sys.path.insert(0, os.path.dirname(__file__))

import app.models  # noqa: F401 — 确保 mapper 初始化

from fastmcp import FastMCP
from sqlalchemy import create_engine, func
from sqlalchemy.orm import joinedload, sessionmaker

from app.core.config import settings
from app.core.time import utcnow
from app.models.content import (
    ContentItem,
    ContentStatus,
    SourceConfig,
)

logger = logging.getLogger(__name__)

# ============ 数据库连接（独立 engine） ============

mcp_engine = create_engine(
    settings.DATABASE_URL,
    pool_size=3,
    max_overflow=2,
    pool_recycle=3600,
    pool_pre_ping=True,
)
MCPSession = sessionmaker(bind=mcp_engine)

_TIME_RANGE_DAYS = {"1d": 1, "3d": 3, "7d": 7, "30d": 30}

_VALID_STATUSES = {s.value for s in ContentStatus}


@contextmanager
def get_db():
    db = MCPSession()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ============ 辅助函数 ============

def _parse_date(date_str: str | None) -> datetime | None:
    """解析 YYYY-MM-DD 日期字符串为 naive datetime"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def _extract_analysis(item: ContentItem) -> dict:
    """安全解析 analysis_result JSON"""
    try:
        data = json.loads(item.analysis_result) if item.analysis_result else {}
        if isinstance(data, dict):
            return {
                "summary": data.get("summary") or data.get("content", ""),
                "tags": data.get("tags", []),
                "sentiment": data.get("sentiment", ""),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {"summary": "", "tags": [], "sentiment": ""}


def _time_range_to_dates(time_range: str | None) -> tuple[datetime | None, datetime | None]:
    """将快捷时间范围转换为 (start_date, end_date)"""
    if not time_range:
        return None, None
    now = utcnow()
    days = _TIME_RANGE_DAYS.get(time_range)
    if days is None:
        return None, None
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


# ============ MCP Server ============

mcp = FastMCP("allin-one")


@mcp.tool()
def list_content(
    time_range: str = "",
    start_date: str = "",
    end_date: str = "",
    source_name: str = "",
    keyword: str = "",
    status: str = "",
    favorites_only: bool = False,
    limit: int = 20,
) -> str:
    """Search and list content items from your information feed.
    Supports filtering by date range, source, keyword, and favorites.
    Returns summaries — use get_content_detail for full text.

    Args:
        time_range: Shortcut "1d/3d/7d/30d", overrides start/end_date.
        start_date: Start date YYYY-MM-DD. Defaults to today if time_range not set.
        end_date: End date YYYY-MM-DD. Defaults to end of today if time_range not set.
        source_name: Source name, fuzzy match.
        keyword: Search in title.
        status: Filter by content status ("analyzed", "ready", "pending", "processing", "failed"). Default: show analyzed + ready.
        favorites_only: Only return favorited content.
        limit: Number of items to return (default 20, max 50).
    """
    limit = max(1, min(limit, 50))

    try:
        with get_db() as db:
            query = (
                db.query(ContentItem)
                .options(joinedload(ContentItem.source))
                .outerjoin(SourceConfig, ContentItem.source_id == SourceConfig.id)
            )

            # Date filtering
            if time_range:
                start_dt, end_dt = _time_range_to_dates(time_range)
            else:
                today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                start_dt = _parse_date(start_date) if start_date else today
                end_dt = _parse_date(end_date) if end_date else today.replace(hour=23, minute=59, second=59)
                if end_dt and end_dt != today.replace(hour=23, minute=59, second=59):
                    end_dt = end_dt.replace(hour=23, minute=59, second=59)

            if start_dt:
                query = query.filter(ContentItem.collected_at >= start_dt)
            if end_dt:
                query = query.filter(ContentItem.collected_at <= end_dt)

            # Status filtering
            if status:
                if status not in _VALID_STATUSES:
                    return json.dumps({
                        "error": f"Invalid status '{status}'",
                        "valid_values": sorted(_VALID_STATUSES),
                    })
                query = query.filter(ContentItem.status == status)
            else:
                query = query.filter(
                    ContentItem.status.in_([ContentStatus.ANALYZED.value, ContentStatus.READY.value])
                )

            # Source name
            if source_name:
                query = query.filter(SourceConfig.name.ilike(f"%{source_name}%"))

            # Keyword search in title
            if keyword:
                query = query.filter(ContentItem.title.ilike(f"%{keyword}%"))

            # Favorites
            if favorites_only:
                query = query.filter(ContentItem.is_favorited == True)  # noqa: E712

            total_count = query.count()
            items = query.order_by(ContentItem.collected_at.desc()).limit(limit).all()

            result_items = []
            for item in items:
                analysis = _extract_analysis(item)
                result_items.append({
                    "id": item.id,
                    "title": item.title,
                    "source_name": item.source.name if item.source else None,
                    "published_at": str(item.published_at) if item.published_at else None,
                    "summary": (analysis["summary"] or "")[:300],
                    "tags": analysis["tags"],
                    "sentiment": analysis["sentiment"],
                    "url": item.url,
                    "is_favorited": item.is_favorited,
                })

            return json.dumps(
                {"items": result_items, "total_count": total_count},
                ensure_ascii=False,
                default=str,
            )
    except Exception as e:
        logger.error("list_content failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_content_detail(content_id: str) -> str:
    """Get full details of a specific content item including processed text,
    AI analysis results, media attachments, and user notes.

    Args:
        content_id: The content item ID (32-char hex UUID from list_content).
    """
    try:
        with get_db() as db:
            item = db.get(ContentItem, content_id)
            if not item:
                return json.dumps({"error": "Content not found", "content_id": content_id})

            analysis = _extract_analysis(item)
            processed = item.processed_content or ""
            truncated = len(processed) > 20000
            if truncated:
                processed = processed[:20000]

            media = []
            for m in item.media_items:
                media.append({
                    "media_type": m.media_type,
                    "original_url": m.original_url,
                    "local_path": m.local_path,
                    "status": m.status,
                })

            return json.dumps({
                "id": item.id,
                "title": item.title,
                "author": item.author,
                "url": item.url,
                "source_name": item.source.name if item.source else None,
                "published_at": str(item.published_at) if item.published_at else None,
                "collected_at": str(item.collected_at) if item.collected_at else None,
                "status": item.status,
                "processed_content": processed,
                "analysis_result": analysis,
                "user_note": item.user_note,
                "is_favorited": item.is_favorited,
                "media_items": media,
                "truncated": truncated,
            }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_content_detail failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_sources(
    status: str = "",
    keyword: str = "",
) -> str:
    """List all content sources with their status, last collection time,
    and today's content count. Use this to check system health or find source names.

    Args:
        status: Filter by "active", "inactive", or "failing".
        keyword: Search source name.
    """
    try:
        with get_db() as db:
            query = db.query(SourceConfig)

            if status == "active":
                query = query.filter(SourceConfig.is_active == True)  # noqa: E712
            elif status == "inactive":
                query = query.filter(SourceConfig.is_active == False)  # noqa: E712
            elif status == "failing":
                query = query.filter(SourceConfig.consecutive_failures > 0)

            if keyword:
                query = query.filter(SourceConfig.name.ilike(f"%{keyword}%"))

            sources = query.order_by(SourceConfig.name).all()
            source_ids = [s.id for s in sources]

            # Batch aggregate: today's content count per source
            today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_counts = {}
            if source_ids:
                rows = (
                    db.query(ContentItem.source_id, func.count(ContentItem.id))
                    .filter(
                        ContentItem.source_id.in_(source_ids),
                        ContentItem.collected_at >= today_start,
                    )
                    .group_by(ContentItem.source_id)
                    .all()
                )
                today_counts = dict(rows)

            result_sources = []
            total_active = 0
            total_failing = 0
            for s in sources:
                if s.is_active:
                    total_active += 1
                if s.consecutive_failures and s.consecutive_failures > 0:
                    total_failing += 1
                result_sources.append({
                    "id": s.id,
                    "name": s.name,
                    "source_type": s.source_type,
                    "is_active": s.is_active,
                    "last_collected_at": str(s.last_collected_at) if s.last_collected_at else None,
                    "next_collection_at": str(s.next_collection_at) if s.next_collection_at else None,
                    "consecutive_failures": s.consecutive_failures or 0,
                    "content_count_today": today_counts.get(s.id, 0),
                })

            return json.dumps({
                "sources": result_sources,
                "summary": {
                    "total": len(sources),
                    "active": total_active,
                    "failing": total_failing,
                },
            }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_sources failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool()
def toggle_favorite(
    content_ids: list[str],
    action: str = "favorite",
) -> str:
    """Favorite or unfavorite content items. Supports batch operations.

    Args:
        content_ids: List of content item IDs.
        action: "favorite" (default) or "unfavorite".
    """
    if action not in ("favorite", "unfavorite"):
        return json.dumps({"error": f"Invalid action '{action}'. Use 'favorite' or 'unfavorite'."})

    try:
        with get_db() as db:
            items = db.query(ContentItem).filter(ContentItem.id.in_(content_ids)).all()
            if not items:
                return json.dumps({"error": "No matching content items found", "content_ids": content_ids})

            now = utcnow()
            updated_ids = []
            for item in items:
                if action == "favorite":
                    item.is_favorited = True
                    item.favorited_at = now
                else:
                    item.is_favorited = False
                    item.favorited_at = None
                updated_ids.append(item.id)

            db.commit()

            not_found = [cid for cid in content_ids if cid not in updated_ids]
            result = {
                "updated_count": len(updated_ids),
                "updated_ids": updated_ids,
                "action": action,
            }
            if not_found:
                result["not_found_ids"] = not_found
            return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("toggle_favorite failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
    else:
        mcp.run()
