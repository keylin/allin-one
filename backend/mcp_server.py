"""Allin-One MCP Server -- 信息流数据服务

复用 backend ORM 模型，直连 PostgreSQL。
供 Claude Code / Cursor 等 AI CLI 查询个人信息流数据。

传输模式：
- 默认 stdio（本地开发）
- MCP_TRANSPORT=http → streamable-http (stateless JSON)，监听 0.0.0.0:8001/mcp
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd

# 确保 backend/ 在 sys.path 中，使 import app.* 可用
sys.path.insert(0, os.path.dirname(__file__))

import app.models  # noqa: F401 — 确保 mapper 初始化

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, func
from sqlalchemy.orm import joinedload, sessionmaker

from app.core.config import settings
from app.core.time import utcnow
from app.models.content import (
    ContentItem,
    ContentStatus,
    SourceCategory,
    SourceConfig,
    SourceType,
    get_source_category,
)
from app.models.pipeline import PipelineTemplate
from app.services.financial_data_client import (
    FinancialDataClient,
    get_financial_client,
    tool_enabled,
)
from app.services.financial_symbols import a_share_suffix, from_fd_symbol, to_fd_symbol
from app.services.source_cleanup import cascade_delete_source
from app.services.source_service import (
    validate_source_config,
    validate_source_name_unique,
    validate_source_type,
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
    """安全解析 analysis_result JSONB 字段"""
    data = item.analysis_result if isinstance(item.analysis_result, dict) else {}
    if data:
        return {
            "summary": data.get("summary") or data.get("content", ""),
            "tags": data.get("tags", []),
            "sentiment": data.get("sentiment", ""),
        }
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


def _resolve_source(db, source_id: str | None, source_name: str | None) -> tuple[SourceConfig | None, str | None]:
    """通过 ID 或名称定位数据源。

    返回: (source, error_json) — 恰好一个为 None。
    - source_id 优先精确匹配
    - source_name 使用模糊匹配，多个匹配时返回候选列表的 error_json
    """
    if not source_id and not source_name:
        return None, json.dumps({"error": "需要提供 source_id 或 source_name"})
    if source_id:
        source = db.get(SourceConfig, source_id)
        if not source:
            return None, json.dumps({"error": f"数据源不存在: {source_id}"})
        return source, None
    # 按名称模糊查找
    matches = db.query(SourceConfig).filter(SourceConfig.name.ilike(f"%{source_name}%")).all()
    if not matches:
        return None, json.dumps({"error": f"找不到名称匹配 '{source_name}' 的数据源"})
    if len(matches) > 1:
        candidates = [{"id": s.id, "name": s.name, "source_type": s.source_type} for s in matches]
        return None, json.dumps({"error": f"找到 {len(matches)} 个匹配，请用 source_id 精确指定", "candidates": candidates})
    return matches[0], None


def _resolve_template_by_name(db, template_name: str) -> tuple[str | None, str | None]:
    """通过模板名称（模糊匹配）获取模板 ID。

    返回: (template_id, error_msg)
    """
    matches = db.query(PipelineTemplate).filter(PipelineTemplate.name.ilike(f"%{template_name}%")).all()
    if not matches:
        all_names = [row[0] for row in db.query(PipelineTemplate.name).limit(20).all()]
        return None, f"找不到模板 '{template_name}'，可用模板: {all_names}"
    if len(matches) > 1:
        candidates = [t.name for t in matches]
        return None, f"找到 {len(matches)} 个匹配模板: {candidates}，请提供更精确的名称"
    return matches[0].id, None


# ============ MCP Server ============

mcp = FastMCP(
    "allin-one",
    host="0.0.0.0",
    port=8001,
    transport_security={
        "enable_dns_rebinding_protection": False,
    },
)


@mcp.tool(annotations={"readOnlyHint": True})
def list_content(
    time_range: str = "",
    start_date: str = "",
    end_date: str = "",
    source_name: str = "",
    keyword: str = "",
    status: str = "",
    favorites_only: bool = False,
    unread_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Search and list content items from your information feed.
    Supports filtering by date range, source, keyword, and favorites.
    Returns summaries — use get_content_detail for full text.

    Pagination: results are ordered by collected_at desc. Use offset+limit to
    page through large result sets (total_count and has_more are returned).
    For incremental consumption, prefer unread_only=True + mark_read() over
    offset paging — marking read shrinks the unread set, so mixing offset with
    mark_read causes the page window to drift. Do not combine the two.

    Args:
        time_range: Shortcut "1d/3d/7d/30d", overrides start/end_date.
        start_date: Start date YYYY-MM-DD. Defaults to today if time_range not set.
        end_date: End date YYYY-MM-DD. Defaults to end of today if time_range not set.
        source_name: Source name, fuzzy match.
        keyword: Search in title.
        status: Filter by content status ("analyzed", "ready", "pending", "processing", "failed"). Default: show analyzed + ready.
        favorites_only: Only return favorited content.
        unread_only: Only return unread items (view_count == 0). Same read state
            as the web UI. Combine with mark_read() to walk the feed exactly once.
        limit: Number of items to return (default 20, max 50).
        offset: Number of items to skip for pagination (default 0).
    """
    limit = max(1, min(limit, 50))
    offset = max(0, offset)

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

            # Unread (view_count == 0 or NULL) — same read state as the web UI
            if unread_only:
                query = query.filter(
                    (ContentItem.view_count == 0) | (ContentItem.view_count.is_(None))
                )

            total_count = query.count()
            items = (
                query.order_by(ContentItem.collected_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

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
                    "is_read": bool(item.view_count and item.view_count > 0),
                })

            return json.dumps(
                {
                    "items": result_items,
                    "total_count": total_count,
                    "offset": offset,
                    "returned": len(result_items),
                    "has_more": offset + len(result_items) < total_count,
                },
                ensure_ascii=False,
                default=str,
            )
    except Exception as e:
        logger.error("list_content failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": True})
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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
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


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
def mark_read(content_ids: list[str]) -> str:
    """Mark content items as read. Batch, idempotent.

    Sets view_count=1 and last_viewed_at for items currently unread
    (view_count == 0 or NULL); items already read are left unchanged. This is the
    same read state used by list_content(unread_only=True) and the web UI's
    read/unread filter — so after marking, the items drop out of future unread
    queries. Intended flow: list_content(unread_only=True) → analyze → mark_read
    the batch → repeat until empty, walking the feed exactly once.

    Args:
        content_ids: List of content item IDs to mark as read.
    """
    if not content_ids:
        return json.dumps({"error": "content_ids is empty"})

    try:
        with get_db() as db:
            items = db.query(ContentItem).filter(ContentItem.id.in_(content_ids)).all()
            found_ids = {item.id for item in items}

            now = utcnow()
            marked_ids = []
            already_read_ids = []
            for item in items:
                if not item.view_count:  # 0 or None → unread
                    item.view_count = 1
                    item.last_viewed_at = now
                    marked_ids.append(item.id)
                else:
                    already_read_ids.append(item.id)

            db.commit()

            result = {
                "marked_read_count": len(marked_ids),
                "marked_read_ids": marked_ids,
                "already_read_ids": already_read_ids,
            }
            not_found = [cid for cid in content_ids if cid not in found_ids]
            if not_found:
                result["not_found_ids"] = not_found
            return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("mark_read failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def create_source(
    name: str,
    url: str = "",
    source_type: str = "",
    rsshub_route: str = "",
    pipeline_template_name: str = "",
    description: str = "",
    schedule_interval_minutes: int = 0,
) -> str:
    """Create a new data source for content collection.

    Supports smart type inference: provide url for RSS feeds, rsshub_route for RSSHub sources.

    Args:
        name: Display name for the source (must be unique).
        url: RSS/Atom feed URL or webpage URL. Required for rss.standard sources.
        source_type: Source type code (e.g. "rss.standard", "rss.hub", "web.scraper").
                     Auto-inferred from url/rsshub_route if omitted.
        rsshub_route: RSSHub route path (e.g. "/bilibili/user/video/123"). Required for rss.hub sources.
        pipeline_template_name: Pipeline template name (fuzzy match). Auto-recommended if omitted.
        description: Optional description.
        schedule_interval_minutes: Collection interval in minutes (0 = auto mode).
    """
    try:
        with get_db() as db:
            # 智能推导 source_type
            inferred_type = source_type.strip()
            if not inferred_type:
                if rsshub_route:
                    inferred_type = "rss.hub"
                elif url:
                    inferred_type = "rss.standard"
                else:
                    valid = sorted(e.value for e in SourceType)
                    return json.dumps({"error": "无法推导 source_type，请明确提供", "valid_values": valid})

            # 校验 source_type
            err = validate_source_type(inferred_type)
            if err:
                return json.dumps({"error": err})

            # 构造 config_json
            config_json: dict = {}
            if rsshub_route:
                config_json["rsshub_route"] = rsshub_route.strip()

            # 校验必填配置
            err = validate_source_config(inferred_type, url or None, config_json)
            if err:
                return json.dumps({"error": err})

            # 名称唯一性
            err = validate_source_name_unique(name, db)
            if err:
                return json.dumps({"error": err})

            # 解析模板
            template_id = None
            if pipeline_template_name:
                template_id, err = _resolve_template_by_name(db, pipeline_template_name)
                if err:
                    return json.dumps({"error": err})

            # 构造数据源对象
            source_data = {
                "id": uuid.uuid4().hex,
                "name": name.strip(),
                "source_type": inferred_type,
                "url": url.strip() or None,
                "description": description.strip() or None,
                "pipeline_template_id": template_id,
                "config_json": config_json if config_json else None,
                "schedule_enabled": get_source_category(inferred_type) != SourceCategory.USER,
                "schedule_mode": "auto" if schedule_interval_minutes == 0 else "fixed",
                "schedule_interval_override": schedule_interval_minutes if schedule_interval_minutes > 0 else None,
            }
            source = SourceConfig(**source_data)
            db.add(source)
            db.commit()
            db.refresh(source)

            logger.info("MCP create_source: %s (%s, type=%s)", source.id, source.name, source.source_type)
            return json.dumps({
                "created": True,
                "source": {"id": source.id, "name": source.name, "source_type": source.source_type, "url": source.url},
            }, ensure_ascii=False)
    except Exception as e:
        logger.error("create_source failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
def update_source(
    source_id: str = "",
    source_name: str = "",
    name: str = "",
    url: str = "",
    pipeline_template_name: str = "",
    description: str = "",
    schedule_interval_minutes: int = -1,
) -> str:
    """Update an existing data source configuration.

    Locate the source by source_id (exact) or source_name (fuzzy match).

    Args:
        source_id: Source ID (exact match, preferred).
        source_name: Source name (fuzzy match, used if source_id not provided).
        name: New display name (leave empty to keep current).
        url: New feed/webpage URL (leave empty to keep current).
        pipeline_template_name: New pipeline template name (fuzzy match, leave empty to keep current).
        description: New description (leave empty to keep current).
        schedule_interval_minutes: New interval in minutes (-1 = keep current, 0 = switch to auto mode).
    """
    try:
        with get_db() as db:
            source, err = _resolve_source(db, source_id or None, source_name or None)
            if err:
                return err

            updates = {}
            if name.strip():
                err = validate_source_name_unique(name.strip(), db, exclude_id=source.id)
                if err:
                    return json.dumps({"error": err})
                updates["name"] = name.strip()
            if url.strip():
                updates["url"] = url.strip()
            if description.strip():
                updates["description"] = description.strip()
            if pipeline_template_name.strip():
                template_id, err = _resolve_template_by_name(db, pipeline_template_name.strip())
                if err:
                    return json.dumps({"error": err})
                updates["pipeline_template_id"] = template_id
            if schedule_interval_minutes == 0:
                updates["schedule_mode"] = "auto"
                updates["schedule_interval_override"] = None
            elif schedule_interval_minutes > 0:
                updates["schedule_mode"] = "fixed"
                updates["schedule_interval_override"] = schedule_interval_minutes

            if not updates:
                return json.dumps({"error": "没有提供任何要更新的字段"})

            for k, v in updates.items():
                setattr(source, k, v)
            db.commit()

            logger.info("MCP update_source: %s (%s)", source.id, source.name)
            return json.dumps({
                "updated": True,
                "source_id": source.id,
                "source_name": source.name,
                "changes": list(updates.keys()),
            }, ensure_ascii=False)
    except Exception as e:
        logger.error("update_source failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False})
def delete_source(
    source_id: str = "",
    source_name: str = "",
    cascade: bool = False,
) -> str:
    """Delete a data source.

    By default keeps associated content items (only removes the source config).
    Set cascade=True to also delete all associated content.

    Args:
        source_id: Source ID (exact match, preferred).
        source_name: Source name (fuzzy match, used if source_id not provided).
        cascade: If True, delete all associated content items. Default False (keep content).
    """
    try:
        with get_db() as db:
            source, err = _resolve_source(db, source_id or None, source_name or None)
            if err:
                return err

            sid = source.id
            sname = source.name

            cascade_delete_source([sid], db, cascade=cascade)
            db.commit()

            logger.info("MCP delete_source: %s (%s) cascade=%s", sid, sname, cascade)
            return json.dumps({
                "deleted": True,
                "source_id": sid,
                "source_name": sname,
                "content_deleted": cascade,
                "note": "关联内容已删除" if cascade else "关联内容已保留（source_id 已置空）",
            }, ensure_ascii=False)
    except Exception as e:
        logger.error("delete_source failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
def toggle_source(
    source_id: str = "",
    source_name: str = "",
    action: str = "enable",
) -> str:
    """Enable or disable a data source.

    Disabled sources are not collected automatically but their content is preserved.

    Args:
        source_id: Source ID (exact match, preferred).
        source_name: Source name (fuzzy match, used if source_id not provided).
        action: "enable" or "disable".
    """
    if action not in ("enable", "disable"):
        return json.dumps({"error": f"Invalid action '{action}'. Use 'enable' or 'disable'."})

    try:
        with get_db() as db:
            source, err = _resolve_source(db, source_id or None, source_name or None)
            if err:
                return err

            source.is_active = (action == "enable")
            db.commit()

            logger.info("MCP toggle_source: %s (%s) -> %s", source.id, source.name, action)
            return json.dumps({
                "updated": True,
                "source_id": source.id,
                "source_name": source.name,
                "is_active": source.is_active,
            }, ensure_ascii=False)
    except Exception as e:
        logger.error("toggle_source failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# ============ 影视资料库 ============

@mcp.tool(annotations={"readOnlyHint": True})
def list_films(
    status: str = "",
    kind: str = "",
    genre: str = "",
    year_from: int = 0,
    year_to: int = 0,
    in_emby: str = "",
    keyword: str = "",
    limit: int = 200,
    offset: int = 0,
) -> str:
    """List films/series in the personal film library (Emby-synced + manually added),
    with the user's own marks. Use this BEFORE recommending films so you can exclude
    what the user has already watched, and to learn their taste from ratings/comments.

    Each row: content_id, tmdb_id, title, original_title, kind (movie/series), year,
    genres, directors, countries, community_rating, in_emby, emby facts (played,
    play_count, progress, last_played_at, episodes), and record (status, my_rating,
    watched_at, tags, comment, log_count, status_source). my_rating / watched_at / comment are
    from the LATEST viewing; log_count > 1 means the user has rewatched it (each viewing has its
    own date/rating/note; fetch the full history via the REST detail endpoint if needed).

    Data layers: `emby` = viewing facts from the media server (evidence);
    `record` = the user's own claim. status_source=emby_autofill means "watched" was
    inferred from Emby played=true, not confirmed by the user.

    Args:
        status: Filter by record.status, comma-separated: unmarked/want/watching/watched/dropped.
        kind: "movie" or "series".
        genre: Exact genre name (as stored, usually zh-CN from Emby/TMDb).
        year_from: Minimum production year (0 = no bound).
        year_to: Maximum production year (0 = no bound).
        in_emby: "true" = only titles currently in the Emby library, "false" = only those not in Emby, "" = all.
        keyword: Fuzzy match on title / original title / director.
        limit: Max rows (default 200, max 500).
        offset: Pagination offset.
    """
    import sqlalchemy as sa
    from sqlalchemy import or_
    from sqlalchemy.orm import selectinload
    from app.models.film import WatchRecord, WATCH_STATUSES
    from app.services.film_library import FILM_SOURCE_TYPES, KINDS, serialize_film

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    try:
        with get_db() as db:
            query = (
                db.query(ContentItem, WatchRecord)
                .join(SourceConfig, ContentItem.source_id == SourceConfig.id)
                .outerjoin(WatchRecord, WatchRecord.content_id == ContentItem.id)
                .options(selectinload(WatchRecord.logs))
                .filter(SourceConfig.source_type.in_(FILM_SOURCE_TYPES))
            )
            if status:
                wanted = [x.strip() for x in status.split(",") if x.strip() in WATCH_STATUSES]
                if wanted:
                    if "unmarked" in wanted:
                        query = query.filter(or_(WatchRecord.status.in_(wanted), WatchRecord.id.is_(None)))
                    else:
                        query = query.filter(WatchRecord.status.in_(wanted))
            if kind in KINDS:
                query = query.filter(ContentItem.raw_data["kind"].astext == kind)
            if genre:
                query = query.filter(ContentItem.raw_data["genres"].contains([genre]))
            if year_from:
                query = query.filter(ContentItem.raw_data["year"].astext.cast(sa.Integer) >= year_from)
            if year_to:
                query = query.filter(ContentItem.raw_data["year"].astext.cast(sa.Integer) <= year_to)
            if in_emby.lower() == "true":
                query = query.filter(ContentItem.raw_data["emby"]["in_library"].astext == "true")
            elif in_emby.lower() == "false":
                query = query.filter(or_(
                    ContentItem.raw_data["emby"]["in_library"].astext.is_(None),
                    ContentItem.raw_data["emby"]["in_library"].astext != "true",
                ))
            if keyword:
                like = f"%{keyword}%"
                query = query.filter(or_(
                    ContentItem.title.ilike(like),
                    ContentItem.author.ilike(like),
                    ContentItem.raw_data["original_title"].astext.ilike(like),
                ))
            total = query.count()
            rows = (
                query.order_by(ContentItem.raw_data["year"].astext.cast(sa.Integer).desc().nulls_last(), ContentItem.title.asc())
                .offset(offset).limit(limit).all()
            )
            items = []
            for content, record in rows:
                f = serialize_film(content, record, brief=True)
                f.pop("poster_url", None)
                items.append(f)
            return json.dumps({
                "items": items, "total_count": total, "offset": offset,
                "returned": len(items), "has_more": offset + len(items) < total,
            }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("list_films failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": True})
def search_film(q: str, year: int = 0) -> str:
    """Search TMDb for a film/series to get its tmdb_id before marking it.
    Requires the TMDb API key configured in system settings; otherwise returns an error
    and you should fall back to mark_films with title+year.

    Args:
        q: Title to search (Chinese or original title).
        year: Optional release year to narrow results (0 = ignore).
    """
    from app.services.film_library import TMDB_IMAGE_BASE, get_tmdb_api_key, tmdb_search

    try:
        with get_db() as db:
            api_key = get_tmdb_api_key(db)
        if not api_key:
            return json.dumps({"error": "TMDb API key not configured; use mark_films with title+year instead"})
        results = tmdb_search(api_key, q, year or None)
        for r in results:
            r.pop("poster_path", None)
        return json.dumps({"results": results}, ensure_ascii=False)
    except Exception as e:
        logger.error("search_film failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
def mark_films(items: list[dict]) -> str:
    """Create or update the user's watch marks for films, in batch. Films that are not
    yet in the library are created first (via TMDb when tmdb_id is given and the key is
    configured, otherwise as a title+year skeleton). Typical use: after a recommendation
    round the user says "I've seen 1, 3 and 5" — call this once with those titles.

    Any mark written here is a user claim (status_source=manual) and will never be
    overwritten by Emby sync. Only call this for what the user explicitly confirmed.

    Args:
        items: List of dicts. Each locates a film by ONE of: content_id | tmdb_id (+kind:
            "movie"/"series", default movie) | title (+year). Optional fields:
            status (want/watching/watched/dropped/unmarked; default "watched"),
            my_rating (1-10), watched_at ("YYYY-MM-DD", or "YYYY-MM" / "YYYY" when only roughly
            remembered; omit when unknown — never guess a date), comment (the user's note for this
            viewing, any length), tags (list, film-level), rewatch (true = record a NEW viewing
            instead of editing the latest one; use when the user says they watched it again;
            its date defaults to today unless watched_at is given).
            my_rating / watched_at / comment belong to a viewing; a film keeps one viewing log per
            watch, and the latest one is what list_films shows.
            Example: [{"tmdb_id": "603", "kind": "movie", "status": "watched", "my_rating": 9},
                      {"title": "一一", "year": 2000, "status": "watched"},
                      {"title": "教父", "year": 1972, "rewatch": true, "watched_at": "2026-09", "my_rating": 10}]
    """
    from app.services.film_library import apply_record_update, get_or_create_record, resolve_or_create_film

    if not isinstance(items, list) or not items:
        return json.dumps({"error": "items must be a non-empty list"})
    results = []
    try:
        with get_db() as db:
            for item in items:
                if not isinstance(item, dict):
                    results.append({"ok": False, "error": "item must be an object", "input": item})
                    continue
                content, err = resolve_or_create_film(
                    db,
                    content_id=item.get("content_id"),
                    tmdb_id=str(item["tmdb_id"]) if item.get("tmdb_id") else None,
                    kind=item.get("kind"),
                    title=item.get("title"),
                    year=int(item["year"]) if item.get("year") else None,
                )
                if err or not content:
                    results.append({"ok": False, "error": err or "resolve failed", "input": item})
                    continue
                record = get_or_create_record(db, content.id)
                update = {"status": item.get("status") or "watched"}
                for key in ("my_rating", "watched_at", "comment", "tags", "rewatch"):
                    if key in item and item[key] is not None:
                        update[key] = item[key]
                errors = apply_record_update(db, record, update, content)
                if errors:
                    db.rollback()
                    results.append({"ok": False, "error": "; ".join(errors), "content_id": content.id, "title": content.title})
                    continue
                db.commit()
                results.append({
                    "ok": True, "content_id": content.id, "title": content.title,
                    "year": (content.raw_data or {}).get("year"), "status": record.status,
                    "external_id": content.external_id,
                })
        ok = sum(1 for r in results if r["ok"])
        return json.dumps({"processed": len(results), "ok": ok, "results": results}, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("mark_films failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": True})
def get_favorites_summary(
    time_range: str = "all",
) -> str:
    """Get statistics and summary of your favorited content.

    Useful for understanding your reading patterns and content preferences.

    Args:
        time_range: "7d", "30d", "90d", or "all" (default).
    """
    try:
        with get_db() as db:
            # 时间范围解析
            since = None
            if time_range and time_range != "all":
                days_map = {"7d": 7, "30d": 30, "90d": 90}
                days = days_map.get(time_range)
                if days is None:
                    return json.dumps({"error": f"Invalid time_range '{time_range}'. Use '7d', '30d', '90d', or 'all'."})
                since = utcnow() - timedelta(days=days)

            # 基础过滤条件（所有子查询复用）
            base_filters = [ContentItem.is_favorited == True]  # noqa: E712
            if since is not None:
                base_filters.append(ContentItem.favorited_at >= since)

            total = db.query(ContentItem).filter(*base_filters).count()
            if total == 0:
                return json.dumps({"total_favorites": 0, "by_source": [], "by_month": [], "recent": []})

            # 按数据源分布（top 10）— 以 ContentItem 为驱动表，left join SourceConfig
            source_counts = (
                db.query(SourceConfig.name, func.count(ContentItem.id))
                .select_from(ContentItem)
                .outerjoin(SourceConfig, ContentItem.source_id == SourceConfig.id)
                .filter(*base_filters)
                .group_by(SourceConfig.name)
                .order_by(func.count(ContentItem.id).desc())
                .limit(10)
                .all()
            )
            by_source = [{"source_name": name or "未知来源", "count": cnt} for name, cnt in source_counts]

            # 按月分布（最近 12 个月）— 同样受时间范围约束
            month_counts = (
                db.query(
                    func.to_char(ContentItem.favorited_at, "YYYY-MM").label("month"),
                    func.count(ContentItem.id),
                )
                .filter(*base_filters, ContentItem.favorited_at.isnot(None))
                .group_by(func.to_char(ContentItem.favorited_at, "YYYY-MM"))
                .order_by(func.to_char(ContentItem.favorited_at, "YYYY-MM").desc())
                .limit(12)
                .all()
            )
            by_month = [{"month": month, "count": cnt} for month, cnt in month_counts]

            # 最近 10 条收藏
            recent_items = (
                db.query(ContentItem)
                .options(joinedload(ContentItem.source))
                .filter(*base_filters)
                .order_by(ContentItem.favorited_at.desc())
                .limit(10)
                .all()
            )
            recent = [
                {
                    "id": item.id,
                    "title": item.title,
                    "source_name": item.source.name if item.source else None,
                    "favorited_at": str(item.favorited_at) if item.favorited_at else None,
                    "url": item.url,
                }
                for item in recent_items
            ]

            return json.dumps({
                "total_favorites": total,
                "time_range": time_range,
                "by_source": by_source,
                "by_month": by_month,
                "recent": recent,
            }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_favorites_summary failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


# ============ 金融数据工具 ============

_finance_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def _finance_get_cached(key: str, ttl: int = 30) -> pd.DataFrame | None:
    if key in _finance_cache:
        ts, df = _finance_cache[key]
        if time.time() - ts < ttl:
            return df
    return None


def _finance_set_cache(key: str, df: pd.DataFrame):
    _finance_cache[key] = (time.time(), df)


def _safe_val(val, as_str: bool = False):
    """安全提取 DataFrame 值"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if as_str:
        return str(val)
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return str(val)


def _df_to_records(
    df: pd.DataFrame,
    field_map: dict[str, str],
    str_fields: set[str] | None = None,
) -> list[dict]:
    """DataFrame → list[dict]，按 field_map {输出键: 源列名} 映射"""
    str_fields = str_fields or set()
    records = []
    for _, row in df.iterrows():
        rec = {}
        for out_key, src_col in field_map.items():
            if src_col not in row.index:
                rec[out_key] = None
                continue
            rec[out_key] = _safe_val(row[src_col], as_str=(out_key in str_fields))
        records.append(rec)
    return records


async def _ak_call(func, *args, timeout: int = 15, retries: int = 2, **kwargs) -> pd.DataFrame | None:
    """带超时和重试退避的 akshare 调用"""
    for attempt in range(retries):
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(func, *args, **kwargs),
                timeout=timeout,
            )
            return df if df is not None and not df.empty else None
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("akshare call %s attempt %d/%d failed: %s", func.__name__, attempt + 1, retries, e)
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s 指数退避
    return None


# --- 列映射 ---

_SPOT_FIELDS = {
    "code": "代码", "name": "名称", "price": "最新价",
    "change_pct": "涨跌幅", "change_amount": "涨跌额",
    "volume": "成交量", "amount": "成交额",
    "high": "最高", "low": "最低", "open": "今开", "prev_close": "昨收",
    "turnover_rate": "换手率", "pe_ratio": "市盈率-动态",
    "pb_ratio": "市净率", "market_cap": "总市值",
}
_SPOT_STR = {"code", "name"}

_INDEX_SPOT_FIELDS = {
    "code": "代码", "name": "名称", "price": "最新价",
    "change_pct": "涨跌幅", "change_amount": "涨跌额",
    "volume": "成交量", "amount": "成交额",
    "high": "最高", "low": "最低", "open": "今开", "prev_close": "昨收",
}

_KLINE_FIELDS_CN = {
    "date": "日期", "open": "开盘", "close": "收盘",
    "high": "最高", "low": "最低", "volume": "成交量",
    "amount": "成交额", "change_pct": "涨跌幅", "turnover": "换手率",
}

_KLINE_FIELDS_EN = {
    "date": "date", "open": "open", "close": "close",
    "high": "high", "low": "low", "volume": "volume",
}

_CRYPTO_FIELDS = {
    "name": "交易品种", "price": "最近报价",
    "change_amount": "涨跌额", "change_pct": "涨跌幅",
    "high_24h": "24小时最高", "low_24h": "24小时最低",
    "volume_24h": "24小时成交量", "market": "市场",
    "updated_at": "更新时间",
}

# --- 宏观指标定义 ---

_MACRO_MAP: dict[str, tuple] = {
    "cpi": ("macro_china_cpi_monthly", {}, "日期", "今值", "CPI 月率"),
    "ppi": ("macro_china_ppi", {}, "月份", "当月", "PPI 工业品出厂价格指数"),
    "pmi": ("macro_china_pmi", {}, "月份", "制造业-指数", "PMI 采购经理指数"),
    "gdp": ("macro_china_gdp", {}, "季度", "国内生产总值-绝对值", "GDP 国内生产总值"),
    "m2":  ("macro_china_money_supply", {}, "月份", "货币和准货币(M2)-数量(亿元)", "M2 货币供应量"),
    "shibor": (
        "rate_interbank",
        {"market": "上海银行同业拆借市场", "symbol": "Shibor人民币", "indicator": "隔夜"},
        "报告日", "利率", "Shibor 隔夜利率",
    ),
}

# 蚂蚁宏观指标 seed（探针经 macro_recall + macro_query 数值验证，口径与 _MACRO_MAP 一致）
# (indicator_code, 每条数据覆盖天数——用于按 count 推算 start_date)
# cpi/shibor 不在此表：蚂蚁无全国 CPI 月率口径、无 Shibor 定盘利率，无限期保持 akshare
_MACRO_FD_SEED: dict[str, tuple[str, int, str]] = {
    # (indicator_code, 每条数据覆盖天数, 精确口径名)
    "ppi": ("110002644", 31, "工业生产者出厂价格指数（上年同月=100，月度）"),
    "pmi": ("110166523", 31, "制造业采购经理指数（季调，月度）"),
    "gdp": ("110000001", 92, "GDP 现价累计值（季度，亿元）"),
    "m2":  ("110111410", 31, "M2 期末值（月度，亿元）"),
}


# --- 加密货币 CoinGecko ---

# 常用币种 symbol → CoinGecko ID 映射
_COIN_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin",
    "ADA": "cardano", "DOT": "polkadot", "AVAX": "avalanche-2",
    "MATIC": "matic-network", "LINK": "chainlink", "UNI": "uniswap",
    "LTC": "litecoin", "ATOM": "cosmos", "FIL": "filecoin",
    "TRX": "tron", "NEAR": "near", "APT": "aptos",
    "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    "PEPE": "pepe", "SHIB": "shiba-inu", "TON": "the-open-network",
}

_COINGECKO_API = "https://api.coingecko.com/api/v3"


async def _crypto_quote(symbols: str, keyword: str, limit: int) -> str:
    """通过 CoinGecko 查询加密货币行情"""
    import httpx

    cache_key = "crypto_coingecko"
    cached = _finance_get_cached(cache_key, ttl=120)  # 2 分钟缓存，避免 rate limit

    if cached is not None:
        records = cached  # 缓存的是 list[dict]
    else:
        # 请求 Top 100 币种（含重试退避）
        data = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(f"{_COINGECKO_API}/coins/markets", params={
                        "vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": 100, "page": 1, "sparkline": "false",
                        "price_change_percentage": "24h",
                    })
                    if r.status_code == 429:
                        await asyncio.sleep(2 ** attempt * 5)  # 5s, 10s, 20s
                        continue
                    r.raise_for_status()
                    data = r.json()
                    break
            except Exception as e:
                logger.warning("CoinGecko API attempt %d failed: %s", attempt + 1, e)
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt * 5)
        if data is None:
            return json.dumps({"error": "加密货币接口暂不可用（CoinGecko rate limit），请稍后重试"})

        records = []
        for coin in data:
            records.append({
                "symbol": (coin.get("symbol") or "").upper(),
                "name": coin.get("name", ""),
                "price": _safe_val(coin.get("current_price")),
                "change_pct": _safe_val(coin.get("price_change_percentage_24h")),
                "market_cap": _safe_val(coin.get("market_cap")),
                "volume_24h": _safe_val(coin.get("total_volume")),
                "high_24h": _safe_val(coin.get("high_24h")),
                "low_24h": _safe_val(coin.get("low_24h")),
            })
        _finance_set_cache(cache_key, records)

    # 过滤
    if symbols:
        keys = {s.strip().upper() for s in symbols.split(",") if s.strip()}
        records = [r for r in records if r["symbol"] in keys]
    elif keyword:
        kw = keyword.lower()
        records = [r for r in records if kw in r["symbol"].lower() or kw in r["name"].lower()]

    records = records[:limit]
    return json.dumps({"stocks": records, "count": len(records), "market": "crypto"},
                      ensure_ascii=False, default=str)


_SNAPSHOT_INDICES = [
    # (雪球 symbol, 代码, 市场, 名称)；蚂蚁 symbol 由 to_fd_symbol(code, "index") 派生，
    # 唯一数据源是 financial_symbols.INDEX_FD_SYMBOLS
    ("SH000001", "000001", "A", "上证指数"),
    ("SZ399001", "399001", "A", "深证成指"),
    ("SZ399006", "399006", "A", "创业板指"),
    ("SH000300", "000300", "A", "沪深300"),
    ("SH000905", "000905", "A", "中证500"),
    ("SH000688", "000688", "A", "科创50"),
    ("HKHSI", "HSI", "HK", "恒生指数"),
    ("HKHSCEI", "HSCEI", "HK", "国企指数"),
    ("HKHSTECH", "HSTECH", "HK", "恒生科技"),
    (".DJI", "DJI", "US", "道琼斯"),
    (".IXIC", "IXIC", "US", "纳斯达克"),
]


def _get_fd_client(tool: str) -> "FinancialDataClient | None":
    """按工具级开关获取主源 client；关闭/未配置/冷却中返回 None（调用方走 legacy）"""
    return get_financial_client() if tool_enabled(tool) else None


def _fd_price(row: dict) -> float | str | None:
    """行情价格 coalesce：盘中 close 可能为 None（港股实测）"""
    for key in ("last", "close", "previous_close"):
        val = row.get(key)
        if val is not None:
            return _safe_val(val)
    return None


def _fd_spot_record(code: str, row: dict) -> dict:
    """蚂蚁 basic(+derived) 快照行 → 既有行情契约字段"""
    rec = {
        "code": code, "name": str(row.get("name") or ""),
        "price": _fd_price(row),
        "change_pct": _safe_val(row.get("pct_chg")),
        "change_amount": _safe_val(row.get("price_change")),
        "volume": _safe_val(row.get("volume")),
        "amount": _safe_val(row.get("amount")),
        "high": _safe_val(row.get("high")),
        "low": _safe_val(row.get("low")),
        "open": _safe_val(row.get("open")),
        "prev_close": _safe_val(row.get("previous_close")),
    }
    if "pe_ttm" in row:
        turnover = _safe_val(row.get("turnover_rate"))
        rec.update({
            "pe_ratio": _safe_val(row.get("pe_ttm")),
            "pb_ratio": _safe_val(row.get("pb")),
            "market_cap": _safe_val(row.get("total_mv")),
            # 蚂蚁换手率是小数（0.0036=0.36%），对齐既有百分比口径
            "turnover_rate": round(turnover * 100, 4) if turnover is not None else None,
            "pe_lyr": _safe_val(row.get("pe_lyr")),
            "pe_fwd": _safe_val(row.get("pe_fwd")),
        })
    # 廉价合理性断言：拦截静默单位错位
    if rec["change_pct"] is not None and abs(rec["change_pct"]) > 30:
        logger.warning("financial_data suspicious pct_chg=%s for %s", rec["change_pct"], code)
    return rec


# 雪球动态 token：akshare 内置 xq_a_token 已过期（接口返回 error_code 400016），
# 改为运行时访问 xueqiu.com/hq 获取新鲜 token 并缓存
_xq_token_cache: dict[str, tuple[float, str]] = {}
_XQ_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _fetch_xq_token() -> str | None:
    """访问雪球行情页获取新鲜 xq_a_token（首页 / 不再下发，须用 /hq）"""
    import requests
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": _XQ_UA})
        s.get("https://xueqiu.com/hq", timeout=10)
        return s.cookies.get("xq_a_token")
    except Exception as e:
        logger.warning("fetch xueqiu token failed: %s", e)
        return None


async def _xq_get_token(force: bool = False, ttl: int = 1800) -> str | None:
    """带缓存的雪球 token 获取（默认 30 分钟）；获取失败时回退旧 token"""
    cached = _xq_token_cache.get("token")
    if not force and cached and time.time() - cached[0] < ttl:
        return cached[1]
    token = await asyncio.to_thread(_fetch_xq_token)
    if token:
        _xq_token_cache["token"] = (time.time(), token)
        return token
    return cached[1] if cached else None


async def _xq_spot(symbol: str) -> dict | None:
    """通过雪球查询单只标的行情（token 失效时刷新一次重试）"""
    import akshare as ak
    for attempt in range(2):
        token = await _xq_get_token(force=(attempt == 1))
        df = await _ak_call(
            ak.stock_individual_spot_xq, symbol=symbol, token=token, timeout=10, retries=1
        )
        if df is not None:
            return dict(zip(df["item"], df["value"]))
    return None


@mcp.tool(annotations={"readOnlyHint": True})
async def get_market_snapshot() -> str:
    """获取主要市场指数实时行情概览。

    返回 A 股主要指数（上证、深证、创业板、沪深300、中证500、科创50）、
    港股指数（恒生、国企、恒生科技）和美股指数（道琼斯、纳斯达克）。
    非交易时段返回最近收盘数据。主数据源：蚂蚁 financial-data，降级：雪球。
    响应含 data_source 字段：financial_data=主源 | legacy=降级链 | mixed=批量中部分标的降级。
    """
    cache_key = "market_snapshot"
    cached = _finance_get_cached(cache_key, ttl=30)
    if cached is not None:
        return cached  # 缓存的是 JSON 字符串

    results: list[dict] = []
    fd_hit = legacy_hit = 0

    # 主路径：一次批量拿全部 11 个指数（任何异常都降级，不外抛破坏 JSON 契约）
    fd = _get_fd_client("snapshot")
    snap: dict[str, dict] = {}
    if fd is not None:
        try:
            snap = await fd.basic_snapshot(
                [to_fd_symbol(code, "index") for _, code, _, _ in _SNAPSHOT_INDICES])
        except Exception as e:
            logger.warning("get_market_snapshot fallback to legacy: %s", e)

    for xq_sym, code, mkt, name in _SNAPSHOT_INDICES:
        row = snap.get(to_fd_symbol(code, "index") or "")
        if row is not None:
            rec = _fd_spot_record(code, row)
            rec["market"] = mkt
            rec["name"] = rec["name"] or name
            results.append(rec)
            fd_hit += 1
            continue
        # 逐条降级：主源缺哪个指数补哪个
        data = await _xq_spot(xq_sym)
        if data:
            legacy_hit += 1
            results.append({
                "code": code, "name": data.get("名称", name), "market": mkt,
                "price": _safe_val(data.get("现价")),
                "change_pct": _safe_val(data.get("涨幅")),
                "change_amount": _safe_val(data.get("涨跌")),
                "open": _safe_val(data.get("今开")),
                "prev_close": _safe_val(data.get("昨收")),
                "high": _safe_val(data.get("最高")),
                "low": _safe_val(data.get("最低")),
                "volume": _safe_val(data.get("成交量")),
                "amount": _safe_val(data.get("成交额")),
            })

    if not results:
        return json.dumps({"error": "行情接口暂不可用，请稍后重试"})

    data_source = ("financial_data" if not legacy_hit else "mixed") if fd_hit else "legacy"
    if legacy_hit and fd is not None:
        logger.info("get_market_snapshot degraded: fd=%d legacy=%d", fd_hit, legacy_hit)
    result_json = json.dumps(
        {"indices": results, "count": len(results), "data_source": data_source},
        ensure_ascii=False, default=str,
    )
    _finance_set_cache(cache_key, result_json)
    return result_json


_XQ_PREFIX = {"A": {"SH": "6", "SZ": "0,3"}, "HK": {}, "US": {}}


def _to_xq_symbol(code: str, market: str) -> str:
    """将代码转换为雪球 symbol 格式（交易所判定复用 financial_symbols.a_share_suffix，
    与蚂蚁 symbol 映射共享同一份规则，避免两处漂移）"""
    if market == "A":
        return f"{a_share_suffix(code)}{code}"
    return code  # HK: 00700 / US: AAPL 原样


@mcp.tool(annotations={"readOnlyHint": True})
async def get_stock_quote(
    symbols: str = "",
    keyword: str = "",
    market: str = "A",
    limit: int = 10,
) -> str:
    """查询个股实时行情。

    支持 A 股、港股、美股和加密货币。通过代码查询（推荐）或名称关键词搜索。
    主数据源：蚂蚁 financial-data（行情+估值一次拿全），降级：雪球/东方财富。
    加密货币走 CoinGecko。
    响应含 data_source 字段：financial_data=主源 | legacy=降级链 | mixed=批量中部分标的降级。

    Args:
        symbols: 代码，逗号分隔。A股 "600519,000001"；港股 "00700"；美股 "AAPL,MSFT"
        keyword: 名称关键词，如 "茅台"、"Apple"。支持 A/HK/US 三市场（实体识别解析），
            主源不可用时自动降级旧接口（仅 A 股，依赖东方财富）
        market: "A"（A股，默认）| "HK"（港股）| "US"（美股）| "crypto"（加密货币）
        limit: 最大返回条数（默认 10，上限 50）
    """
    if not symbols and not keyword:
        return json.dumps({"error": "请提供 symbols（代码）或 keyword（关键词）"})

    import akshare as ak

    market = market.upper() if market != "crypto" else "crypto"
    limit = max(1, min(limit, 50))

    try:
        # 加密货币 — CoinGecko 免费 API
        if market == "crypto":
            return await _crypto_quote(symbols, keyword, limit)

        if market not in ("A", "HK", "US"):
            return json.dumps({"error": f"不支持的市场: {market}，可选: A, HK, US, crypto"})

        fd = _get_fd_client("quote")

        # 按代码查询 — 主路径：蚂蚁批量（行情+估值一次往返），按 symbol 部分降级雪球
        if symbols:
            codes = [s.strip() for s in symbols.split(",") if s.strip()][:limit]
            fd_map: dict[str, str] = {}
            quotes: dict[str, dict] = {}
            if fd is not None:
                for code in codes:
                    fd_sym = to_fd_symbol(code, market)
                    if fd_sym is None and market == "US":
                        fd_sym = await fd.resolve_us_symbol(code)
                    if fd_sym:
                        fd_map[code] = fd_sym
                if fd_map:
                    try:
                        quotes = await fd.quote_with_valuation(list(fd_map.values()))
                    except Exception as e:
                        logger.warning("get_stock_quote fallback to legacy: %s", e)

            records = []
            fd_hit = legacy_hit = 0
            for code in codes:
                row = quotes.get(fd_map.get(code, ""))
                if row is not None:
                    records.append(_fd_spot_record(code, row))
                    fd_hit += 1
                    continue
                # 逐只降级雪球
                data = await _xq_spot(_to_xq_symbol(code, market))
                if data:
                    legacy_hit += 1
                    records.append({
                        "code": code, "name": str(data.get("名称", "")),
                        "price": _safe_val(data.get("现价")),
                        "change_pct": _safe_val(data.get("涨幅")),
                        "change_amount": _safe_val(data.get("涨跌")),
                        "volume": _safe_val(data.get("成交量")),
                        "amount": _safe_val(data.get("成交额")),
                        "high": _safe_val(data.get("最高")),
                        "low": _safe_val(data.get("最低")),
                        "open": _safe_val(data.get("今开")),
                        "prev_close": _safe_val(data.get("昨收")),
                        "pe_ratio": _safe_val(data.get("市盈率(动)")),
                        "pb_ratio": _safe_val(data.get("市净率")),
                        "market_cap": _safe_val(data.get("资产净值/总市值")),
                    })
            # 统一 schema：mixed 时主源/降级记录的键集合保持一致（缺失显式 None）
            for rec in records:
                for k in ("pe_ratio", "pb_ratio", "market_cap", "turnover_rate", "pe_lyr", "pe_fwd"):
                    rec.setdefault(k, None)
            data_source = ("financial_data" if not legacy_hit else "mixed") if fd_hit else "legacy"
            if legacy_hit and fd is not None:
                logger.info("get_stock_quote degraded: fd=%d legacy=%d", fd_hit, legacy_hit)
            return json.dumps(
                {"stocks": records, "count": len(records), "market": market, "data_source": data_source},
                ensure_ascii=False, default=str)

        # 关键词搜索 — 主路径：entity_recognition 解析名称再批量查行情
        if fd is not None:
            try:
                entities = await fd.recognize(keyword, asset_type="股票")
                suffix_ok = {"A": (".SH", ".SZ", ".BJ"), "HK": (".HK",), "US": (".O", ".N", ".A")}[market]
                syms = [e["symbol"] for e in entities
                        if str(e.get("symbol", "")).endswith(suffix_ok)][:limit]
                if syms:
                    quotes = await fd.quote_with_valuation(syms)
                    records = [_fd_spot_record(from_fd_symbol(s), quotes[s]) for s in syms if s in quotes]
                    if records:
                        return json.dumps(
                            {"stocks": records, "count": len(records), "market": market,
                             "data_source": "financial_data"},
                            ensure_ascii=False, default=str)
            except Exception as e:
                logger.warning("get_stock_quote keyword fallback to legacy: %s", e)

        # 降级：东方财富 push2 全表过滤（可能不可用）
        func_map = {"A": ak.stock_zh_a_spot_em, "HK": ak.stock_hk_spot_em, "US": ak.stock_us_spot_em}
        cache_key = f"stock_spot_{market}"
        df = _finance_get_cached(cache_key, ttl=30)
        if df is None:
            df = await _ak_call(func_map[market], timeout=30)
            if df is not None:
                _finance_set_cache(cache_key, df)
        if df is None:
            return json.dumps({"error": f"关键词搜索需要东方财富接口，当前不可用。请改用 symbols 参数直接查询代码"})
        df = df[df["名称"].str.contains(keyword, na=False)].head(limit)
        records = _df_to_records(df, _SPOT_FIELDS, _SPOT_STR)
        return json.dumps(
            {"stocks": records, "count": len(records), "market": market, "data_source": "legacy"},
            ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_stock_quote failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


_KLINE_FIELDS_TX = {
    "date": "date", "open": "open", "close": "close",
    "high": "high", "low": "low", "volume": "amount",
}

_KLINE_FIELDS_CSINDEX = {
    "date": "日期", "open": "开盘", "close": "收盘",
    "high": "最高", "low": "最低", "volume": "成交量",
    "amount": "成交金额", "change_pct": "涨跌幅",
}


@mcp.tool(annotations={"readOnlyHint": True})
async def get_kline(
    symbol: str,
    market: str = "A",
    period: str = "daily",
    count: int = 30,
    adjust: str = "qfq",
) -> str:
    """查询历史 K 线数据（OHLCV）。

    主数据源：蚂蚁 financial-data（A/HK/US/指数/ETF 全覆盖）。
    降级：A股/ETF 腾讯，指数中证官网，港股/美股新浪。
    后复权（hfq）主源不支持，自动走降级路径；港股/美股主源仅不复权。
    响应含 data_source 字段：financial_data=主源 | legacy=降级链 | mixed=批量中部分标的降级。

    Args:
        symbol: 代码。A股 "600519"；港股 "00700"；美股 "AAPL"；指数 "000300"；ETF "510050"
        market: "A"（A股，默认）| "HK"（港股）| "US"（美股）| "index"（A股指数）| "etf"
        period: "daily"（日K，默认）| "weekly"（周K）| "monthly"（月K）
        count: 返回最近 N 条（默认 30，上限 250）
        adjust: "qfq"（前复权，默认）| "hfq"（后复权）| ""（不复权）。指数无效
    """
    import akshare as ak

    valid_markets = {"A", "HK", "US", "index", "etf"}
    if market not in valid_markets:
        return json.dumps({"error": f"market 须为 {'/'.join(valid_markets)}，收到: {market}"})

    count = max(1, min(count, 250))

    # 主路径：蚂蚁 kline-batch。以下组合跳过主源、优先 legacy：
    # - hfq 后复权（主源不支持，仅腾讯有）
    # - 港/美股 + qfq（主源仅不复权，新浪支持 qfq）；legacy 失败后回主源不复权兜底
    fd = _get_fd_client("kline")
    fd_period = {"daily": "P_Day1", "weekly": "P_Week1", "monthly": "P_Month1"}.get(period)
    fd_first = (
        fd is not None and fd_period is not None and adjust != "hfq"
        and not (market in ("HK", "US") and adjust == "qfq")
    )

    async def _fd_kline() -> tuple[list[dict], str | None] | None:
        """主源 K 线，返回 (records, note)；不可用返回 None（任何异常都降级，不外抛）"""
        if fd is None or fd_period is None:
            return None
        try:
            fd_sym = to_fd_symbol(symbol, market)
            if fd_sym is None and market == "US":
                fd_sym = await fd.resolve_us_symbol(symbol)
            if fd_sym is None:
                return None
            split = "S_Before" if (market in ("A", "etf") and adjust == "qfq") else "S_Unsplit"
            rows = await fd.kline(fd_sym, fd_period, split, count)
        except Exception as e:
            logger.warning("get_kline fallback to legacy: %s", e)
            return None
        if not rows:
            return None
        records = [{
            "date": str(r.get("date") or "")[:10],  # 归一化 YYYY-MM-DD（美股带 12:00:00）
            "open": _safe_val(r.get("open")),
            "close": _safe_val(r.get("close")),
            "high": _safe_val(r.get("high")),
            "low": _safe_val(r.get("low")),
            "volume": _safe_val(r.get("volume")),
            "amount": _safe_val(r.get("amount")),
        } for r in rows]
        note = None
        if market in ("HK", "US") and adjust in ("qfq", "hfq"):
            note = "主数据源港股/美股仅提供不复权数据，本结果为不复权口径"
        return records, note

    def _fd_payload(data: list[dict], note: str | None) -> str:
        # adjust 恒回显请求值（与 legacy 契约一致）；实际口径差异通过 note 传达
        payload = {
            "symbol": symbol, "market": market, "period": period,
            "adjust": "N/A" if market == "index" else adjust,
            "data": data, "count": len(data), "data_source": "financial_data",
        }
        if note:
            payload["note"] = note
        return json.dumps(payload, ensure_ascii=False, default=str)

    if fd_first:
        fd_result = await _fd_kline()
        if fd_result is not None:
            return _fd_payload(*fd_result)
    _period_multiplier = {"daily": 2, "weekly": 10, "monthly": 45}
    days_back = count * _period_multiplier.get(period, 2)
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")

    try:
        df = None
        fields = _KLINE_FIELDS_CN

        if market == "A":
            # 腾讯数据源（不走 push2）
            tx_sym = f"sz{symbol}" if symbol.startswith("159") or symbol[0] not in "569" else f"sh{symbol}"
            tx_adjust = {"qfq": "qfq", "hfq": "hfq", "": ""}.get(adjust, "qfq")
            df = await _ak_call(
                ak.stock_zh_a_hist_tx, symbol=tx_sym, start_date=start, end_date=end,
                adjust=tx_adjust, timeout=20,
            )
            fields = _KLINE_FIELDS_TX
        elif market == "index":
            # 中证官网（不走 push2）
            df = await _ak_call(
                ak.stock_zh_index_hist_csindex, symbol=symbol,
                start_date=start, end_date=end, timeout=20,
            )
            if df is not None:
                fields = _KLINE_FIELDS_CSINDEX
            else:
                # fallback: 东方财富
                df = await _ak_call(ak.stock_zh_index_daily_em, symbol=symbol, start_date=start, timeout=20)
                fields = _KLINE_FIELDS_EN
        elif market == "HK":
            # 新浪港股日线（不走 push2）
            df = await _ak_call(ak.stock_hk_index_daily_sina, symbol=symbol, timeout=20)
            fields = _KLINE_FIELDS_EN
        elif market == "US":
            # 新浪美股日线（不走 push2）
            us_adjust = adjust if adjust in ("qfq", "hfq") else ""
            df = await _ak_call(ak.stock_us_daily, symbol=symbol, adjust=us_adjust or "qfq", timeout=20)
            fields = _KLINE_FIELDS_EN
        elif market == "etf":
            # 复用腾讯 A 股接口（ETF 和股票共用）
            tx_sym = f"sz{symbol}" if symbol.startswith("159") or symbol[0] not in "569" else f"sh{symbol}"
            tx_adjust = {"qfq": "qfq", "hfq": "hfq", "": ""}.get(adjust, "qfq")
            df = await _ak_call(
                ak.stock_zh_a_hist_tx, symbol=tx_sym, start_date=start, end_date=end,
                adjust=tx_adjust, timeout=20,
            )
            fields = _KLINE_FIELDS_TX

        if df is None:
            # legacy 也失败 → 主源不复权兜底（覆盖 hfq / 港美股 qfq 先走 legacy 的场景）
            if fd is not None and fd_period is not None and not fd_first:
                fd_result = await _fd_kline()
                if fd_result is not None:
                    data, note = fd_result
                    if adjust in ("qfq", "hfq"):
                        note = f"复权数据源不可用，本结果为主数据源不复权口径（请求 adjust={adjust}）"
                    return _fd_payload(data, note)
            return json.dumps({"error": f"未找到 {symbol} ({market}) 的数据，请检查代码和市场类型"})

        df = df.tail(count)
        data = _df_to_records(df, fields, str_fields={"date"})

        return json.dumps({
            "symbol": symbol, "market": market, "period": period,
            "adjust": adjust if market not in ("index",) else "N/A",
            "data": data, "count": len(data), "data_source": "legacy",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_kline failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": True})
async def get_macro_indicator(
    indicator: str,
    count: int = 12,
) -> str:
    """查询中国宏观经济指标最近数据。

    ppi/pmi/gdp/m2 主数据源为蚂蚁 financial-data（仅单一核心序列，见响应 series 字段；
    不含 legacy 口径下的分项/同比副字段），cpi/shibor 走 akshare（主源无同口径数据）。
    响应含 data_source 字段：financial_data=主源 | legacy=降级链 | mixed=批量中部分标的降级。

    Args:
        indicator: 指标名 — cpi | ppi | pmi | gdp | m2 | shibor
        count: 返回最近 N 条（默认 12，上限 120）
    """
    import akshare as ak

    key = indicator.lower().strip()
    if key not in _MACRO_MAP:
        available = ", ".join(_MACRO_MAP.keys())
        return json.dumps({"error": f"未知指标 '{indicator}'，可选: {available}"})

    func_name, params, date_field, value_field, label = _MACRO_MAP[key]
    count = max(1, min(count, 120))

    # 主路径：蚂蚁 macro_query（仅口径已验证的指标）
    fd = _get_fd_client("macro")
    if fd is not None and key in _MACRO_FD_SEED:
        code, days_per_point, series = _MACRO_FD_SEED[key]
        try:
            start = utcnow() - timedelta(days=count * days_per_point + 45)
            unit, rows = await fd.macro_query(code, start)
            if rows:
                data = [{
                    "date": str(r.get("end_date") or "")[:10],
                    "value": _safe_val(r.get("indicator_value")),
                    "disclosure_date": str(r.get("disclosure_date") or "")[:10] or None,
                } for r in rows[-count:]]
                result = {
                    "indicator": key, "label": label,
                    "series": series,  # 精确口径；主源仅单一核心序列，无 legacy 的分项副字段
                    "value_field": "value",
                    "data": data, "count": len(data),
                    "data_source": "financial_data",
                }
                if unit:
                    result["unit"] = unit
                return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning("get_macro_indicator fallback to legacy: %s", e)

    try:
        cache_key = f"macro_{key}"
        df = _finance_get_cached(cache_key, ttl=3600)
        if df is None:
            func = getattr(ak, func_name)
            df = await _ak_call(func, **params, timeout=20)
            if df is not None:
                _finance_set_cache(cache_key, df)

        if df is None:
            return json.dumps({"error": f"{label}: 接口暂不可用"})

        # akshare 部分指标按时间倒序排列，统一取最近 count 条
        if len(df) > 1 and date_field in df.columns:
            first_date = str(df.iloc[0][date_field])
            last_date = str(df.iloc[-1][date_field])
            if first_date > last_date:
                # 倒序（新→旧），取 head 并反转为正序
                df = df.head(count).iloc[::-1].reset_index(drop=True)
            else:
                df = df.tail(count)
        else:
            df = df.tail(count)

        data = []
        for _, row in df.iterrows():
            date_val = _safe_val(row.get(date_field), as_str=True)
            value = _safe_val(row.get(value_field))
            if date_val:
                entry = {"date": date_val, "value": value}
                for col in df.columns:
                    if col != date_field and col not in entry:
                        v = _safe_val(row.get(col))
                        if v is not None:
                            entry[col] = v
                data.append(entry)

        return json.dumps({
            "indicator": key, "label": label,
            "value_field": value_field,
            "data": data, "count": len(data),
            "data_source": "legacy",
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_macro_indicator failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
