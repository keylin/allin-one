"""Dashboard API"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, literal_column

from app.core.database import get_db
from app.core.time import utcnow
from app.core.timezone_utils import get_local_day_boundaries, get_container_timezone_name
from app.models.content import SourceConfig, ContentItem, CollectionRecord
from app.models.pipeline import PipelineExecution, PipelineStatus

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    sources_count = db.query(func.count(SourceConfig.id)).scalar()

    # 计算今日边界（容器时区）
    today_start, today_end = get_local_day_boundaries()
    contents_today = (
        db.query(func.count(ContentItem.id))
        .filter(
            ContentItem.collected_at >= today_start,
            ContentItem.collected_at < today_end
        )
        .scalar()
    )

    # 计算昨日边界
    yesterday_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_start, yesterday_end = get_local_day_boundaries(yesterday_date)
    contents_yesterday = (
        db.query(func.count(ContentItem.id))
        .filter(
            ContentItem.collected_at >= yesterday_start,
            ContentItem.collected_at < yesterday_end
        )
        .scalar()
    )

    # 单次查询聚合所有 pipeline 状态计数，避免 3 次独立 COUNT
    pipeline_counts = dict(
        db.query(PipelineExecution.status, func.count(PipelineExecution.id))
        .group_by(PipelineExecution.status)
        .all()
    )

    # 总内容数
    contents_total = db.query(func.count(ContentItem.id)).scalar()

    return {
        "code": 0,
        "data": {
            "sources_count": sources_count,
            "contents_today": contents_today,
            "contents_yesterday": contents_yesterday,
            "contents_total": contents_total,
            "pipelines_running": pipeline_counts.get(PipelineStatus.RUNNING.value, 0),
            "pipelines_failed": pipeline_counts.get(PipelineStatus.FAILED.value, 0),
            "pipelines_pending": pipeline_counts.get(PipelineStatus.PENDING.value, 0),
        },
        "message": "ok",
    }


@router.get("/collection-trend")
async def get_collection_trend(
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """获取最近 N 天每日采集数量趋势"""
    # 计算起始边界（容器时区的 N 天前 00:00）
    start_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    start_utc, _ = get_local_day_boundaries(start_date)

    # 获取容器时区名称（用于 SQL 层时区转换）
    tz_name = get_container_timezone_name()

    # 使用 AT TIME ZONE 在数据库层按容器时区分组
    # 将 UTC 时间转为容器时区后提取日期，避免拉取全量数据到 Python 处理
    rows = (
        db.query(
            func.date(
                func.timezone(
                    literal_column(f"'{tz_name}'"),
                    func.timezone('UTC', ContentItem.collected_at)
                )
            ).label("day"),
            func.count(ContentItem.id).label("count"),
        )
        .filter(ContentItem.collected_at >= start_utc)
        .group_by("day")
        .all()
    )

    count_map = {str(row.day): row.count for row in rows}

    # 补全缺失天数（使用容器本地时间日期）
    trend = []
    for i in range(days):
        day = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        trend.append({"date": day, "count": count_map.get(day, 0)})

    return {"code": 0, "data": trend, "message": "ok"}


@router.get("/daily-stats")
async def get_daily_stats(
    date: str = Query(None, description="日期 YYYY-MM-DD，默认今天（容器时区）"),
    db: Session = Depends(get_db),
):
    """获取指定日期的采集详细统计"""
    # 如果未传日期，使用容器本地时间的今天
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    # 计算日期边界（容器时区）
    try:
        day_start, day_end = get_local_day_boundaries(date)
    except ValueError:
        return {"code": -1, "data": None, "message": "日期格式错误，需要 YYYY-MM-DD"}

    # 筛选当天的采集记录（使用时区边界）
    records = (
        db.query(CollectionRecord)
        .filter(
            CollectionRecord.started_at >= day_start,
            CollectionRecord.started_at < day_end
        )
        .all()
    )

    # 聚合统计
    collection_total = len(records)
    collection_success = sum(1 for r in records if r.status == "completed")
    collection_failed = sum(1 for r in records if r.status == "failed")
    items_found = sum(r.items_found or 0 for r in records)
    items_new = sum(r.items_new or 0 for r in records)
    success_rate = round(collection_success / collection_total * 100, 1) if collection_total > 0 else 0

    # 按数据源分组统计
    source_stats = {}
    for r in records:
        if r.source_id not in source_stats:
            source_stats[r.source_id] = {
                "source_id": r.source_id,
                "items_new": 0,
                "collection_count": 0
            }
        source_stats[r.source_id]["items_new"] += r.items_new or 0
        source_stats[r.source_id]["collection_count"] += 1

    # 取 Top 10 数据源（按 items_new 降序）
    top_source_ids = sorted(
        source_stats.values(),
        key=lambda x: x["items_new"],
        reverse=True
    )[:10]

    # 批量查询数据源名称
    source_ids = [s["source_id"] for s in top_source_ids]
    sources = db.query(SourceConfig.id, SourceConfig.name).filter(SourceConfig.id.in_(source_ids)).all()
    source_name_map = {s.id: s.name for s in sources}

    # 填充数据源名称
    top_sources = []
    for s in top_source_ids:
        top_sources.append({
            "source_id": s["source_id"],
            "source_name": source_name_map.get(s["source_id"], "未知数据源"),
            "items_new": s["items_new"],
            "collection_count": s["collection_count"]
        })

    return {
        "code": 0,
        "data": {
            "date": date,
            "collection_total": collection_total,
            "collection_success": collection_success,
            "collection_failed": collection_failed,
            "success_rate": success_rate,
            "items_found": items_found,
            "items_new": items_new,
            "top_sources": top_sources,
        },
        "message": "ok",
    }


@router.get("/source-health")
async def get_source_health(db: Session = Depends(get_db)):
    """获取数据源健康状态概览"""
    sources = (
        db.query(SourceConfig)
        .order_by(SourceConfig.consecutive_failures.desc(), SourceConfig.name)
        .all()
    )

    data = []
    for s in sources:
        if not s.is_active:
            health = "disabled"
        elif s.consecutive_failures >= 3:
            health = "error"
        elif s.consecutive_failures >= 1:
            health = "warning"
        else:
            health = "healthy"

        data.append({
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type,
            "health": health,
            "consecutive_failures": s.consecutive_failures,
            "last_collected_at": s.last_collected_at.isoformat() if s.last_collected_at else None,
            "is_active": s.is_active,
        })

    return {"code": 0, "data": data, "message": "ok"}


@router.get("/recent-content")
async def get_recent_content(
    limit: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """获取最近采集的内容"""
    items = (
        db.query(ContentItem)
        .order_by(ContentItem.collected_at.desc())
        .limit(limit)
        .all()
    )

    # 批量加载关联的 source 名称，避免 N+1
    source_ids = {item.source_id for item in items}
    sources = db.query(SourceConfig.id, SourceConfig.name).filter(SourceConfig.id.in_(source_ids)).all()
    source_map = {s.id: s.name for s in sources}

    data = []
    for item in items:
        data.append({
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "status": item.status,
            "source_name": source_map.get(item.source_id),
            "collected_at": item.collected_at.isoformat() if item.collected_at else None,
        })

    return {"code": 0, "data": data, "message": "ok"}


@router.get("/recent-activity")
async def get_recent_activity(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """获取最近 pipeline 执行活动"""
    executions = (
        db.query(PipelineExecution)
        .order_by(PipelineExecution.created_at.desc())
        .limit(limit)
        .all()
    )

    # 批量加载关联的 content 标题，避免 N+1
    content_ids = {ex.content_id for ex in executions}
    contents = db.query(ContentItem.id, ContentItem.title).filter(ContentItem.id.in_(content_ids)).all()
    content_map = {c.id: c.title for c in contents}

    data = []
    for ex in executions:
        data.append({
            "id": ex.id,
            "content_id": ex.content_id,
            "content_title": content_map.get(ex.content_id),
            "template_name": ex.template_name,
            "status": ex.status,
            "trigger_source": ex.trigger_source,
            "current_step": ex.current_step,
            "total_steps": ex.total_steps,
            "started_at": ex.started_at.isoformat() if ex.started_at else None,
            "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
            "created_at": ex.created_at.isoformat() if ex.created_at else None,
        })

    return {"code": 0, "data": data, "message": "ok"}
