"""Dashboard API"""

from datetime import timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig, ContentItem
from app.models.pipeline import PipelineExecution, PipelineStatus

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    sources_count = db.query(func.count(SourceConfig.id)).scalar()

    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    contents_today = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.collected_at >= today_start)
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
    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # 按天聚合
    rows = (
        db.query(
            func.date(ContentItem.collected_at).label("day"),
            func.count(ContentItem.id).label("count"),
        )
        .filter(ContentItem.collected_at >= start)
        .group_by(func.date(ContentItem.collected_at))
        .all()
    )

    count_map = {str(row.day): row.count for row in rows}

    # 补全缺失的天
    trend = []
    for i in range(days):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        trend.append({"date": day, "count": count_map.get(day, 0)})

    return {"code": 0, "data": trend, "message": "ok"}


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
