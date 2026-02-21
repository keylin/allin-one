"""Dashboard API"""

from datetime import datetime, timedelta
import sqlalchemy
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, Integer as SAInteger, literal_column, case

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
    """获取最近 N 天每日采集数量趋势（含成功率）"""
    # 计算起始边界（容器时区的 N 天前 00:00）
    start_date = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    start_utc, _ = get_local_day_boundaries(start_date)

    # 获取容器时区名称（用于 SQL 层时区转换）
    tz_name = get_container_timezone_name()

    # 1. 内容数量趋势
    content_rows = (
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
    content_map = {str(row.day): row.count for row in content_rows}

    # 2. 采集记录统计（成功率）
    collection_rows = (
        db.query(
            func.date(
                func.timezone(
                    literal_column(f"'{tz_name}'"),
                    func.timezone('UTC', CollectionRecord.started_at)
                )
            ).label("day"),
            func.count(CollectionRecord.id).label("total"),
            func.sum(func.cast(CollectionRecord.status == 'completed', sqlalchemy.Integer)).label("success"),
            func.sum(func.coalesce(CollectionRecord.items_new, 0)).label("items_new"),
        )
        .filter(CollectionRecord.started_at >= start_utc)
        .group_by("day")
        .all()
    )
    collection_map = {
        str(row.day): {
            "total": row.total,
            "success": row.success or 0,
            "items_new": row.items_new or 0,
        }
        for row in collection_rows
    }

    # 3. 合并数据，补全缺失天数
    trend = []
    for i in range(days):
        day = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        col_data = collection_map.get(day, {"total": 0, "success": 0, "items_new": 0})
        total = col_data["total"]
        success = col_data["success"]
        success_rate = round(success / total * 100, 1) if total > 0 else 0

        trend.append({
            "date": day,
            "count": content_map.get(day, 0),
            "collection_total": total,
            "collection_success": success,
            "success_rate": success_rate,
            "items_new": col_data["items_new"],
        })

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

    # SQL 聚合统计（避免加载全部记录到内存）
    day_filter = [
        CollectionRecord.started_at >= day_start,
        CollectionRecord.started_at < day_end,
    ]
    agg = db.query(
        func.count(CollectionRecord.id).label("total"),
        func.sum(case((CollectionRecord.status == "completed", 1), else_=0)).label("success"),
        func.sum(case((CollectionRecord.status == "failed", 1), else_=0)).label("failed"),
        func.coalesce(func.sum(CollectionRecord.items_found), 0).label("items_found"),
        func.coalesce(func.sum(CollectionRecord.items_new), 0).label("items_new"),
    ).filter(*day_filter).one()

    collection_total = agg.total
    collection_success = agg.success
    collection_failed = agg.failed
    items_found = agg.items_found
    items_new = agg.items_new
    success_rate = round(collection_success / collection_total * 100, 1) if collection_total > 0 else 0

    # 按数据源分组 Top 10（SQL 聚合）
    top_source_rows = (
        db.query(
            CollectionRecord.source_id,
            func.coalesce(func.sum(CollectionRecord.items_new), 0).label("items_new"),
            func.count(CollectionRecord.id).label("collection_count"),
        )
        .filter(*day_filter)
        .group_by(CollectionRecord.source_id)
        .order_by(func.coalesce(func.sum(CollectionRecord.items_new), 0).desc())
        .limit(10)
        .all()
    )

    # 批量查询数据源名称
    source_ids = [r.source_id for r in top_source_rows]
    sources = db.query(SourceConfig.id, SourceConfig.name).filter(SourceConfig.id.in_(source_ids)).all()
    source_name_map = {s.id: s.name for s in sources}

    top_sources = [
        {
            "source_id": r.source_id,
            "source_name": source_name_map.get(r.source_id, "未知数据源"),
            "items_new": r.items_new,
            "collection_count": r.collection_count,
        }
        for r in top_source_rows
    ]

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


@router.get("/content-status-distribution")
async def get_content_status_distribution(db: Session = Depends(get_db)):
    """获取内容状态分布统计"""
    # 按 status 分组计数
    status_counts = dict(
        db.query(ContentItem.status, func.count(ContentItem.id))
        .group_by(ContentItem.status)
        .all()
    )

    total = sum(status_counts.values())

    return {
        "code": 0,
        "data": {
            "pending": status_counts.get("pending", 0),
            "processing": status_counts.get("processing", 0),
            "ready": status_counts.get("ready", 0),
            "analyzed": status_counts.get("analyzed", 0),
            "failed": status_counts.get("failed", 0),
            "total": total,
        },
        "message": "ok",
    }


@router.get("/storage-stats")
async def get_storage_stats(db: Session = Depends(get_db)):
    """获取存储空间统计"""
    import os
    from app.core.config import settings

    # 统计媒体目录大小
    media_dir = settings.MEDIA_DIR
    video_bytes = 0
    image_bytes = 0
    audio_bytes = 0
    other_bytes = 0

    from app.core.constants import VIDEO_EXTENSIONS, IMAGE_EXTENSIONS, AUDIO_EXTENSIONS
    if os.path.exists(media_dir):
        for root, dirs, files in os.walk(media_dir):
            for f in files:
                path = os.path.join(root, f)
                try:
                    size = os.path.getsize(path)
                    ext = os.path.splitext(f)[1].lower()
                    if ext in VIDEO_EXTENSIONS:
                        video_bytes += size
                    elif ext in IMAGE_EXTENSIONS:
                        image_bytes += size
                    elif ext in AUDIO_EXTENSIONS:
                        audio_bytes += size
                    else:
                        other_bytes += size
                except OSError:
                    pass

    # 统计数据库大小（PostgreSQL）
    db_size = 0
    try:
        result = db.execute(sqlalchemy.text(
            "SELECT pg_database_size(current_database())"
        )).scalar()
        db_size = result or 0
    except Exception:
        pass

    total_bytes = video_bytes + image_bytes + audio_bytes + other_bytes + db_size

    return {
        "code": 0,
        "data": {
            "media": {
                "video_bytes": video_bytes,
                "image_bytes": image_bytes,
                "audio_bytes": audio_bytes,
                "other_bytes": other_bytes,
            },
            "database_bytes": db_size,
            "total_bytes": total_bytes,
        },
        "message": "ok",
    }


@router.get("/today-summary")
async def get_today_summary(db: Session = Depends(get_db)):
    """获取今日摘要（高频数据合并接口）"""
    # 今日边界
    today_start, today_end = get_local_day_boundaries()

    # 1. 今日采集统计（SQL 聚合，避免加载全部记录）
    today_agg = db.query(
        func.count(CollectionRecord.id).label("total"),
        func.sum(case((CollectionRecord.status == "completed", 1), else_=0)).label("success"),
        func.coalesce(func.sum(CollectionRecord.items_new), 0).label("items_new"),
    ).filter(
        CollectionRecord.started_at >= today_start,
        CollectionRecord.started_at < today_end,
    ).one()

    collection_total = today_agg.total
    collection_success = today_agg.success
    collection_success_rate = round(collection_success / collection_total * 100, 1) if collection_total > 0 else 0
    items_new_today = today_agg.items_new

    # 2. 内容状态分布
    status_counts = dict(
        db.query(ContentItem.status, func.count(ContentItem.id))
        .group_by(ContentItem.status)
        .all()
    )

    # 3. 失败任务数
    failed_pipelines = db.query(func.count(PipelineExecution.id)).filter(
        PipelineExecution.status == PipelineStatus.FAILED.value
    ).scalar()

    # 4. 运行中任务数
    running_pipelines = db.query(func.count(PipelineExecution.id)).filter(
        PipelineExecution.status == PipelineStatus.RUNNING.value
    ).scalar()

    return {
        "code": 0,
        "data": {
            "collection_success_rate": collection_success_rate,
            "items_new_today": items_new_today,
            "content_status": {
                "pending": status_counts.get("pending", 0),
                "ready": status_counts.get("ready", 0),
                "analyzed": status_counts.get("analyzed", 0),
                "failed": status_counts.get("failed", 0),
            },
            "failed_pipelines": failed_pipelines,
            "running_pipelines": running_pipelines,
        },
        "message": "ok",
    }


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
