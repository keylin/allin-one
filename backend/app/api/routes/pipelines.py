"""Pipelines API - 流水线管理"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def list_pipelines(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    """查询 Pipeline 执行记录"""
    # TODO: 实现
    return {"code": 0, "data": [], "message": "ok"}


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)):
    """获取 Pipeline 详情"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}


@router.post("/manual")
async def manual_pipeline(db: Session = Depends(get_db)):
    """手动 URL 触发 Pipeline"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}
