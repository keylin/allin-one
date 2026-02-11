"""Templates API - 模版管理"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.get("/")
async def list_templates(db: Session = Depends(get_db)):
    """获取模版列表"""
    # TODO: 实现
    return {"code": 0, "data": [], "message": "ok"}
