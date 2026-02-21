"""Settings API - 系统设置"""

import logging
import re
from datetime import timedelta
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
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
        # 跳过掩码值，避免覆盖真实密钥（掩码格式: *** 或 ***xxxx）
        if value and re.match(r'^\*{3}\w{0,4}$', value):
            continue
        existing = db.get(SystemSetting, key)
        if existing:
            existing.value = value
            existing.updated_at = utcnow()
        else:
            db.add(SystemSetting(key=key, value=value))
    db.commit()
    logger.info(f"Settings updated: {list(body.settings.keys())}")
    return {"code": 0, "data": None, "message": "ok"}


_MASK_PATTERN = re.compile(r'^\*{3}\w{0,4}$')


@router.post("/test-llm")
async def test_llm_connection(body: LLMTestRequest, db: Session = Depends(get_db)):
    """测试 LLM API 连接"""
    from openai import AsyncOpenAI

    if not body.api_key or not body.base_url or not body.model:
        return error_response(400, "请填写完整的 API Key、Base URL 和模型名称")

    # 如果前端传来的是掩码值，从 DB 读取真实 key
    api_key = body.api_key
    if _MASK_PATTERN.match(api_key):
        row = db.get(SystemSetting, "llm_api_key")
        if row and row.value:
            api_key = row.value
        else:
            return error_response(400, "未找到已保存的 API Key，请输入真实值")

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=body.base_url, timeout=15)
        resp = await client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "Hi, reply with OK"}],
            max_tokens=5,
        )
        model_used = resp.model or body.model
        return {"code": 0, "data": {"model": model_used}, "message": "连接成功"}
    except Exception as e:
        return error_response(400, f"连接失败: {str(e)}")


class ClearRecordsRequest(BaseModel):
    before_days: Optional[int] = None  # 清理 N 天前的记录；不传则清理全部已终态记录


@router.post("/clear-executions")
async def clear_executions(body: ClearRecordsRequest = ClearRecordsRequest(), db: Session = Depends(get_db)):
    """手动清理执行记录 — 删除已终态的 PipelineExecution 及其 Steps"""
    from app.models.pipeline import PipelineExecution, PipelineStep, PipelineStatus

    terminal_statuses = [
        PipelineStatus.COMPLETED.value,
        PipelineStatus.FAILED.value,
        PipelineStatus.CANCELLED.value,
    ]

    query = db.query(PipelineExecution).filter(
        PipelineExecution.status.in_(terminal_statuses)
    )
    if body.before_days is not None and body.before_days > 0:
        cutoff = utcnow() - timedelta(days=body.before_days)
        query = query.filter(PipelineExecution.created_at < cutoff)

    execution_ids = [eid for (eid,) in query.with_entities(PipelineExecution.id).all()]
    if not execution_ids:
        return {"code": 0, "data": {"deleted": 0}, "message": "没有需要清理的执行记录"}

    # 先删 steps，再删 executions
    db.query(PipelineStep).filter(
        PipelineStep.pipeline_id.in_(execution_ids)
    ).delete(synchronize_session=False)
    deleted = db.query(PipelineExecution).filter(
        PipelineExecution.id.in_(execution_ids)
    ).delete(synchronize_session=False)
    db.commit()

    logger.info(f"Manual cleanup: deleted {deleted} executions")
    return {"code": 0, "data": {"deleted": deleted}, "message": f"已清理 {deleted} 条执行记录"}


@router.post("/clear-collections")
async def clear_collections(body: ClearRecordsRequest = ClearRecordsRequest(), db: Session = Depends(get_db)):
    """手动清理采集记录 — 删除已终态的 CollectionRecord"""
    from app.models.content import CollectionRecord

    terminal_statuses = ["completed", "failed"]

    query = db.query(CollectionRecord).filter(
        CollectionRecord.status.in_(terminal_statuses)
    )
    if body.before_days is not None and body.before_days > 0:
        cutoff = utcnow() - timedelta(days=body.before_days)
        query = query.filter(CollectionRecord.started_at < cutoff)

    deleted = query.delete(synchronize_session=False)
    db.commit()

    logger.info(f"Manual cleanup: deleted {deleted} collection records")
    return {"code": 0, "data": {"deleted": deleted}, "message": f"已清理 {deleted} 条采集记录"}


@router.post("/preview-cleanup")
async def preview_cleanup(db: Session = Depends(get_db)):
    """预览清理影响 — 计算将要删除的记录数量，不实际删除"""
    from app.models.content import ContentItem, CollectionRecord, SourceConfig
    from app.models.pipeline import PipelineExecution, PipelineStatus
    from app.models.system_setting import SystemSetting

    def get_setting(key: str, default: int) -> int:
        row = db.get(SystemSetting, key)
        if row and row.value:
            try:
                return int(row.value)
            except ValueError:
                pass
        return default

    now = utcnow()

    # ---- 预览内容清理 ----
    default_retention = get_setting("default_retention_days", 30)
    content_count = 0

    if default_retention > 0:
        sources = db.query(SourceConfig).all()

        for source in sources:
            retention = source.retention_days if source.retention_days and source.retention_days > 0 else default_retention
            cutoff = now - timedelta(days=retention)

            count = db.query(ContentItem).filter(
                ContentItem.source_id == source.id,
                ContentItem.collected_at < cutoff,
                ContentItem.is_favorited == False,
                ContentItem.user_note.is_(None),
            ).count()
            content_count += count

    # ---- 预览执行记录清理 ----
    exec_retention_days = get_setting("execution_retention_days", 30)
    exec_max_count = get_setting("execution_max_count", 0)
    exec_count = 0

    exec_terminal = [
        PipelineStatus.COMPLETED.value,
        PipelineStatus.FAILED.value,
        PipelineStatus.CANCELLED.value,
    ]

    # 按天数
    if exec_retention_days > 0:
        cutoff = now - timedelta(days=exec_retention_days)
        exec_count += db.query(PipelineExecution).filter(
            PipelineExecution.status.in_(exec_terminal),
            PipelineExecution.created_at < cutoff,
        ).count()

    # 按数量
    if exec_max_count > 0:
        total_terminal = db.query(PipelineExecution).filter(
            PipelineExecution.status.in_(exec_terminal),
        ).count()
        exec_count = max(exec_count, total_terminal - exec_max_count)

    # ---- 预览采集记录清理 ----
    coll_retention_days = get_setting("collection_retention_days", 90)
    coll_min_keep = get_setting("collection_min_keep", 10)
    coll_count = 0

    coll_terminal = ["completed", "failed"]

    if coll_retention_days > 0:
        cutoff = now - timedelta(days=coll_retention_days)
        sources = db.query(SourceConfig).all()

        for source in sources:
            all_records = db.query(CollectionRecord).filter(
                CollectionRecord.source_id == source.id,
                CollectionRecord.status.in_(coll_terminal),
            ).order_by(CollectionRecord.started_at.desc()).all()

            if len(all_records) <= coll_min_keep:
                continue

            deletable = [
                r for r in all_records[coll_min_keep:]
                if r.started_at < cutoff
            ]
            coll_count += len(deletable)

    return {
        "code": 0,
        "data": {
            "content_items": content_count,
            "executions": exec_count,
            "collection_records": coll_count,
        },
        "message": "ok"
    }


@router.post("/manual-cleanup")
async def manual_cleanup(db: Session = Depends(get_db)):
    """立即执行清理（无需等待定时任务）"""
    from app.tasks.scheduled_tasks import cleanup_expired_content, cleanup_records

    try:
        await cleanup_expired_content()
        await cleanup_records()
        return {"code": 0, "data": None, "message": "清理完成"}
    except Exception as e:
        logger.error(f"Manual cleanup failed: {e}")
        return {"code": 500, "data": None, "message": f"清理失败: {str(e)}"}
