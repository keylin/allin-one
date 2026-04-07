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


@mcp.tool(annotations={"readOnlyHint": True})
async def get_market_snapshot() -> str:
    """获取主要市场指数实时行情概览。

    返回 A 股主要指数（上证、深证、创业板、沪深300、中证500、科创50）
    以及港股主要指数（恒生指数等）的最新价和涨跌幅。
    非交易时段返回最近收盘数据。
    """
    import akshare as ak

    results: list[dict] = []

    # A 股指数 — 三个系列合并后按代码筛选
    a_codes = {"000001", "399001", "399006", "000300", "000905", "000688"}
    for series in ["上证系列指数", "深证系列指数", "沪深重要指数"]:
        cache_key = f"index_spot_{series}"
        df = _finance_get_cached(cache_key, ttl=30)
        if df is None:
            df = await _ak_call(ak.stock_zh_index_spot_em, symbol=series, timeout=30)
            if df is not None:
                _finance_set_cache(cache_key, df)
        if df is not None:
            matched = df[df["代码"].isin(a_codes)]
            for rec in _df_to_records(matched, _INDEX_SPOT_FIELDS, _SPOT_STR):
                if not any(r["code"] == rec["code"] for r in results):
                    rec["market"] = "A"
                    results.append(rec)

    # 港股指数
    hk_df = _finance_get_cached("hk_index_spot", ttl=30)
    if hk_df is None:
        hk_df = await _ak_call(ak.stock_hk_index_spot_em, timeout=30)
        if hk_df is not None:
            _finance_set_cache("hk_index_spot", hk_df)
    if hk_df is not None:
        hk_codes = {"HSI", "HSCEI", "HSCCI", "HSTECH"}
        hk_matched = hk_df[hk_df["代码"].isin(hk_codes)] if "代码" in hk_df.columns else hk_df.head(4)
        for rec in _df_to_records(hk_matched, _INDEX_SPOT_FIELDS, _SPOT_STR):
            rec["market"] = "HK"
            results.append(rec)

    if not results:
        return json.dumps({"error": "行情接口暂不可用，请稍后重试"})

    return json.dumps({"indices": results, "count": len(results)}, ensure_ascii=False, default=str)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_stock_quote(
    symbols: str = "",
    keyword: str = "",
    market: str = "A",
    limit: int = 10,
) -> str:
    """查询个股实时行情。

    支持 A 股、港股、美股和加密货币。通过代码精确查询或名称关键词搜索。

    Args:
        symbols: 代码，逗号分隔。A股如 "600519,000001"；港股如 "00700"；美股如 "105.MSFT"
        keyword: 名称关键词，如 "茅台"、"银行"、"腾讯"
        market: "A"（A股，默认）| "HK"（港股）| "US"（美股）| "crypto"（加密货币）
        limit: 最大返回条数（默认 10，上限 50）
    """
    if not symbols and not keyword:
        return json.dumps({"error": "请提供 symbols（代码）或 keyword（关键词）"})

    import akshare as ak

    market = market.upper() if market != "crypto" else "crypto"
    limit = max(1, min(limit, 50))

    try:
        # 获取行情数据
        if market == "crypto":
            cache_key = "crypto_spot"
            ttl = 60
            df = _finance_get_cached(cache_key, ttl=ttl)
            if df is None:
                df = await _ak_call(ak.crypto_js_spot)
                if df is not None:
                    _finance_set_cache(cache_key, df)
            if df is None:
                return json.dumps({"error": "加密货币行情接口暂不可用"})
            # 搜索
            if symbols:
                keys = [s.strip().upper() for s in symbols.split(",") if s.strip()]
                # 加密货币交易品种是交易对（如 BTCUSD），用 contains 模糊匹配
                mask = df["交易品种"].str.upper().apply(
                    lambda x: any(k in x for k in keys)
                )
                df = df[mask]
            elif keyword:
                df = df[df["交易品种"].str.contains(keyword, case=False, na=False)]
            df = df.head(limit)
            records = _df_to_records(df, _CRYPTO_FIELDS, {"name", "market", "updated_at"})
            return json.dumps({"stocks": records, "count": len(records), "market": "crypto"},
                              ensure_ascii=False, default=str)

        # 股票市场 (A/HK/US)
        func_map = {"A": ak.stock_zh_a_spot_em, "HK": ak.stock_hk_spot_em, "US": ak.stock_us_spot_em}
        func = func_map.get(market)
        if not func:
            return json.dumps({"error": f"不支持的市场: {market}，可选: A, HK, US, crypto"})

        cache_key = f"stock_spot_{market}"
        df = _finance_get_cached(cache_key, ttl=30)
        if df is None:
            df = await _ak_call(func, timeout=30)
            if df is not None:
                _finance_set_cache(cache_key, df)
        if df is None:
            return json.dumps({"error": f"{market} 股行情接口暂不可用，请稍后重试"})

        if symbols:
            codes = [s.strip() for s in symbols.split(",") if s.strip()]
            df = df[df["代码"].isin(codes)]
        elif keyword:
            df = df[df["名称"].str.contains(keyword, na=False)]

        df = df.head(limit)
        records = _df_to_records(df, _SPOT_FIELDS, _SPOT_STR)
        return json.dumps({"stocks": records, "count": len(records), "market": market},
                          ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("get_stock_quote failed: %s", e, exc_info=True)
        return json.dumps({"error": str(e)})


@mcp.tool(annotations={"readOnlyHint": True})
async def get_kline(
    symbol: str,
    market: str = "A",
    period: str = "daily",
    count: int = 30,
    adjust: str = "qfq",
) -> str:
    """查询历史 K 线数据（OHLCV）。

    Args:
        symbol: 代码。A股 "600519"；港股 "00700"；美股 "105.MSFT"；指数 "000300"；ETF "510050"
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
    _period_multiplier = {"daily": 2, "weekly": 10, "monthly": 45}
    days_back = count * _period_multiplier.get(period, 2)
    start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    try:
        if market == "index":
            df = await _ak_call(ak.stock_zh_index_daily_em, symbol=symbol, start_date=start, timeout=20)
            fields = _KLINE_FIELDS_EN
        elif market == "HK":
            df = await _ak_call(ak.stock_hk_hist, symbol=symbol, period=period, start_date=start, adjust=adjust, timeout=20)
            fields = _KLINE_FIELDS_CN
        elif market == "US":
            df = await _ak_call(ak.stock_us_hist, symbol=symbol, period=period, start_date=start, adjust=adjust, timeout=20)
            fields = _KLINE_FIELDS_CN
        elif market == "etf":
            df = await _ak_call(ak.fund_etf_hist_em, symbol=symbol, period=period, start_date=start, adjust=adjust, timeout=20)
            fields = _KLINE_FIELDS_CN
        else:  # A
            df = await _ak_call(ak.stock_zh_a_hist, symbol=symbol, period=period, start_date=start, adjust=adjust, timeout=20)
            fields = _KLINE_FIELDS_CN

        if df is None:
            return json.dumps({"error": f"未找到 {symbol} ({market}) 的数据，请检查代码和市场类型"})

        df = df.tail(count)
        data = _df_to_records(df, fields, str_fields={"date"})

        return json.dumps({
            "symbol": symbol, "market": market, "period": period,
            "adjust": adjust if market not in ("index",) else "N/A",
            "data": data, "count": len(data),
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
