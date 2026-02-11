"""Content API - 内容管理"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def list_content(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: str = Query(None),
    status: str = Query(None),
    media_type: str = Query(None),
    db: Session = Depends(get_db),
):
    """分页查询内容列表"""
    # TODO: 实现
    return {"code": 0, "data": [], "message": "ok"}


@router.get("/{content_id}")
async def get_content(content_id: str, db: Session = Depends(get_db)):
    """获取内容详情"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}


@router.post("/{content_id}/analyze")
async def analyze_content(content_id: str, db: Session = Depends(get_db)):
    """手动触发 LLM 分析"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}
