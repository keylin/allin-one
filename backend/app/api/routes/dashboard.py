"""Dashboard API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter()


@router.get("/stats")
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取仪表盘统计数据"""
    # TODO: 实现统计查询
    return {
        "code": 0,
        "data": {
            "sources_count": 0,
            "contents_today": 0,
            "pipelines_running": 0,
            "pipelines_failed": 0,
        },
        "message": "ok",
    }
