"""Video API - 视频管理"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()


@router.post("/download")
async def download_video(db: Session = Depends(get_db)):
    """提交视频下载任务"""
    # TODO: 实现
    return {"code": 0, "data": None, "message": "ok"}


@router.get("/downloads")
async def list_downloads(db: Session = Depends(get_db)):
    """获取下载任务列表"""
    # TODO: 实现
    return {"code": 0, "data": [], "message": "ok"}
