"""同步管理 API — 统一查询状态 + 触发同步 + SSE 进度 + 凭证绑定"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Path
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import ContentItem, SourceConfig
from app.models.credential import PlatformCredential
from app.models.ebook import BookAnnotation
from app.models.sync_progress import SyncTaskProgress
from app.schemas import error_response
from app.schemas.sync import (
    LinkCredentialRequest,
    SyncPluginStatus,
    SyncProgressEvent,
    SyncRunRequest,
    SyncRunResponse,
    SyncStatusResponse,
)
from app.services.sync import SYNC_FETCHERS

logger = logging.getLogger(__name__)
router = APIRouter()

# 插件注册表
SYNC_PLUGINS = [
    {
        "source_type": "sync.apple_books",
        "name": "Apple Books",
        "category": "ebook",
        "description": "从 macOS Apple Books 同步书籍与标注",
        "credential_required": False,
        "sync_mode": "script",      # 读取本地 macOS 数据库，只能通过脚本同步
    },
    {
        "source_type": "sync.wechat_read",
        "name": "微信读书",
        "category": "ebook",
        "description": "从微信读书同步书籍与标注",
        "credential_required": True,
        "sync_mode": "internal",    # Worker 内置 Fetcher
    },
    {
        "source_type": "sync.bilibili",
        "name": "Bilibili",
        "category": "video",
        "description": "从 B站同步收藏/历史/动态视频",
        "credential_required": True,
        "sync_mode": "internal",
    },
]

# 平台 → credential platform 映射
_PLATFORM_MAP = {
    "sync.bilibili": "bilibili",
    "sync.wechat_read": "wechat_read",
}


@router.get("/status")
async def get_sync_status(db: Session = Depends(get_db)):
    """返回所有 sync 插件的配置状态与统计"""
    # 一次性查出所有 sync.* 源
    sync_sources = db.query(SourceConfig).filter(
        SourceConfig.source_type.like("sync.%"),
    ).all()
    source_map = {s.source_type: s for s in sync_sources}

    plugins = []
    for plugin in SYNC_PLUGINS:
        source = source_map.get(plugin["source_type"])

        if not source:
            # 未配置，返回基础信息 + sync_options
            fetcher_cls = SYNC_FETCHERS.get(plugin["source_type"])
            sync_options = fetcher_cls.get_sync_options() if fetcher_cls else []
            plugins.append(SyncPluginStatus(**plugin, sync_options=sync_options))
            continue

        # 统计条目数
        total_items = db.query(func.count(ContentItem.id)).filter(
            ContentItem.source_id == source.id,
        ).scalar() or 0

        stats = {"total_items": total_items}

        # ebook 类额外统计标注数
        if plugin["category"] == "ebook":
            total_annotations = (
                db.query(func.count(BookAnnotation.id))
                .join(ContentItem, ContentItem.id == BookAnnotation.content_id)
                .filter(ContentItem.source_id == source.id)
                .scalar() or 0
            )
            stats["total_annotations"] = total_annotations

        last_sync = source.last_collected_at

        # 凭证信息
        credential_id = None
        credential_name = None
        credential_status = None
        if source.credential_id:
            cred = db.get(PlatformCredential, source.credential_id)
            if cred:
                credential_id = cred.id
                credential_name = cred.display_name
                credential_status = cred.status

        # 是否有正在运行的同步任务
        is_syncing = db.query(SyncTaskProgress).filter(
            SyncTaskProgress.source_id == source.id,
            SyncTaskProgress.status.in_(["pending", "running"]),
        ).first() is not None

        # Fetcher sync_options
        fetcher_cls = SYNC_FETCHERS.get(plugin["source_type"])
        sync_options = fetcher_cls.get_sync_options() if fetcher_cls else []

        plugins.append(SyncPluginStatus(
            **plugin,
            configured=True,
            source_id=source.id,
            last_sync_at=last_sync.isoformat() if last_sync else None,
            stats=stats,
            credential_id=credential_id,
            credential_name=credential_name,
            credential_status=credential_status,
            is_syncing=is_syncing,
            sync_options=sync_options,
        ))

    return {
        "code": 0,
        "data": SyncStatusResponse(plugins=plugins).model_dump(),
        "message": "ok",
    }


@router.post("/run/{source_type:path}")
async def trigger_sync(
    source_type: str = Path(...),
    body: SyncRunRequest = SyncRunRequest(),
    db: Session = Depends(get_db),
):
    """触发同步任务 — 创建进度记录 + defer Worker 任务"""
    from app.tasks.sync_tasks import run_sync
    from app.tasks.procrastinate_app import async_defer

    # 查找插件元数据
    plugin_meta = next((p for p in SYNC_PLUGINS if p["source_type"] == source_type), None)

    # script 模式不支持在线触发
    if plugin_meta and plugin_meta.get("sync_mode") == "script":
        return error_response(400, f"{plugin_meta['name']} 需要在本机运行脚本同步，不支持在线触发")

    # 查找源
    source = db.query(SourceConfig).filter(
        SourceConfig.source_type == source_type,
    ).first()
    if not source:
        return error_response(404, f"同步源 {source_type} 未初始化，请先初始化")

    # 检查凭证（部分插件不需要凭证）
    if plugin_meta and plugin_meta.get("credential_required", True):
        if not source.credential_id:
            return error_response(400, "未绑定凭证，请先绑定 Cookie")

    # 检查是否有正在运行的任务
    running = db.query(SyncTaskProgress).filter(
        SyncTaskProgress.source_id == source.id,
        SyncTaskProgress.status.in_(["pending", "running"]),
    ).first()
    if running:
        return error_response(409, "已有同步任务在进行中，请等待完成")

    # 创建进度记录
    progress = SyncTaskProgress(
        id=uuid.uuid4().hex,
        source_id=source.id,
        status="pending",
        options_json=json.dumps(body.options, ensure_ascii=False) if body.options else None,
    )
    db.add(progress)
    db.commit()

    # Defer task
    try:
        await async_defer(
            run_sync,
            source_id=source.id,
            progress_id=progress.id,
            options_json=json.dumps(body.options, ensure_ascii=False) if body.options else "{}",
        )
    except Exception as e:
        logger.error(f"Failed to defer sync task: {e}")
        progress.status = "failed"
        progress.error_message = f"任务入队失败: {e}"
        db.commit()
        return error_response(500, "任务入队失败")

    return {
        "code": 0,
        "data": SyncRunResponse(
            progress_id=progress.id,
            source_id=source.id,
        ).model_dump(),
        "message": "同步任务已创建",
    }


@router.get("/progress/{progress_id}")
async def stream_progress(
    progress_id: str = Path(...),
    db: Session = Depends(get_db),
):
    """SSE 进度流 — 轮询 SyncTaskProgress 表，1s 间隔推送变更"""
    # 验证 progress_id 存在
    progress = db.get(SyncTaskProgress, progress_id)
    if not progress:
        return error_response(404, "进度记录不存在")

    async def event_generator():
        last_updated = None
        terminal_sent = False

        while not terminal_sent:
            # 刷新 session 读取最新数据
            db.expire_all()
            p = db.get(SyncTaskProgress, progress_id)
            if not p:
                yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                break

            # 检查是否有变更
            current_updated = p.updated_at
            if current_updated != last_updated:
                last_updated = current_updated

                result_data = None
                if p.result_data:
                    try:
                        result_data = json.loads(p.result_data)
                    except (json.JSONDecodeError, TypeError):
                        pass

                event = SyncProgressEvent(
                    status=p.status,
                    phase=p.phase,
                    message=p.message,
                    current=p.current or 0,
                    total=p.total or 0,
                    result_data=result_data,
                    error_message=p.error_message,
                )

                yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

                # 终态
                if p.status in ("completed", "failed"):
                    terminal_sent = True
                    yield "data: [DONE]\n\n"
                    break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/link-credential")
async def link_credential(
    body: LinkCredentialRequest,
    db: Session = Depends(get_db),
):
    """绑定凭证到同步源"""
    source = db.query(SourceConfig).filter(
        SourceConfig.source_type == body.source_type,
    ).first()
    if not source:
        return error_response(404, f"同步源 {body.source_type} 未初始化")

    credential = db.get(PlatformCredential, body.credential_id)
    if not credential:
        return error_response(404, "凭证不存在")

    source.credential_id = credential.id
    db.commit()

    logger.info(f"Linked credential {credential.display_name} to source {source.source_type}")

    return {
        "code": 0,
        "data": {"source_id": source.id, "credential_id": credential.id},
        "message": f"已绑定凭证: {credential.display_name}",
    }
