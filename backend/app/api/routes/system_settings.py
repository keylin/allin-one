"""Settings API - 系统设置"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    """获取所有设置"""
    # TODO: 实现
    return {"code": 0, "data": {}, "message": "ok"}


@router.put("/")
async def update_settings(db: Session = Depends(get_db)):
    """批量更新设置"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}
