"""Settings API - 系统设置"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.system_setting import SystemSetting
from app.schemas import SettingsUpdate, SettingItem, error_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def get_settings(db: Session = Depends(get_db)):
    """获取所有设置"""
    rows = db.query(SystemSetting).all()
    data = {}
    for row in rows:
        data[row.key] = SettingItem(value=row.value, description=row.description).model_dump()
    return {"code": 0, "data": data, "message": "ok"}


@router.put("")
async def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    """批量 upsert 设置"""
    for key, value in body.settings.items():
        existing = db.get(SystemSetting, key)
        if existing:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
        else:
            db.add(SystemSetting(key=key, value=value))
    db.commit()
    logger.info(f"Settings updated: {list(body.settings.keys())}")
    return {"code": 0, "data": None, "message": "ok"}
