"""Dashboard API"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.content import SourceConfig, ContentItem
from app.models.pipeline import PipelineExecution, PipelineStatus

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    sources_count = db.query(func.count(SourceConfig.id)).scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    contents_today = (
        db.query(func.count(ContentItem.id))
        .filter(ContentItem.collected_at >= today_start)
        .scalar()
    )

    pipelines_running = (
        db.query(func.count(PipelineExecution.id))
        .filter(PipelineExecution.status == PipelineStatus.RUNNING.value)
        .scalar()
    )

    pipelines_failed = (
        db.query(func.count(PipelineExecution.id))
        .filter(PipelineExecution.status == PipelineStatus.FAILED.value)
        .scalar()
    )

    return {
        "code": 0,
        "data": {
            "sources_count": sources_count,
            "contents_today": contents_today,
            "pipelines_running": pipelines_running,
            "pipelines_failed": pipelines_failed,
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

    data = []
    for ex in executions:
        content = db.get(ContentItem, ex.content_id)
        data.append({
            "id": ex.id,
            "content_id": ex.content_id,
            "content_title": content.title if content else None,
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
