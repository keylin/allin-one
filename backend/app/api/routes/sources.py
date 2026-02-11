"""Sources API - 数据源管理"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """获取数据源列表"""
    # TODO: 实现
    return {"code": 0, "data": [], "message": "ok"}


@router.post("/")
async def create_source(db: Session = Depends(get_db)):
    """创建新数据源"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{source_id}/collect")
async def trigger_collect(source_id: str, db: Session = Depends(get_db)):
    """手动触发采集"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}
