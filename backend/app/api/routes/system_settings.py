"""Settings API - 系统设置"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.system_setting import SystemSetting
from app.schemas import SettingsUpdate, SettingItem, error_response

logger = logging.getLogger(__name__)
router = APIRouter()

# 包含这些关键词的 setting key 会在 GET 响应中掩码
_SENSITIVE_KEYWORDS = ("password", "api_key", "token", "secret")


def _mask_value(value: str) -> str:
    """对敏感值掩码，只显示末 4 位"""
    if not value or len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


class LLMTestRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


@router.get("")
async def get_settings(db: Session = Depends(get_db)):
    """获取所有设置"""
    rows = db.query(SystemSetting).all()
    data = {}
    for row in rows:
        value = row.value
        if value and any(kw in row.key.lower() for kw in _SENSITIVE_KEYWORDS):
            value = _mask_value(value)
        data[row.key] = SettingItem(value=value, description=row.description).model_dump()
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


@router.post("/test-llm")
async def test_llm_connection(body: LLMTestRequest):
    """测试 LLM API 连接"""
    from openai import AsyncOpenAI

    if not body.api_key or not body.base_url or not body.model:
        return error_response(400, "请填写完整的 API Key、Base URL 和模型名称")

    try:
        client = AsyncOpenAI(api_key=body.api_key, base_url=body.base_url, timeout=15)
        resp = await client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "Hi, reply with OK"}],
            max_tokens=5,
        )
        model_used = resp.model or body.model
        return {"code": 0, "data": {"model": model_used}, "message": "连接成功"}
    except Exception as e:
        return error_response(400, f"连接失败: {str(e)}")
