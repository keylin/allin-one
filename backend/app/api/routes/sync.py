"""同步管理 API — 统一查询状态 + 触发同步 + SSE 进度 + 凭证绑定"""

import asyncio
import json
import logging

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
from app.models.source_types import sync_panel_plugins
from app.services.sync import SYNC_FETCHERS
from app.services.sync.runner import SyncStartError, expire_stale_progress, start_sync

logger = logging.getLogger(__name__)
router = APIRouter()

# 同步面板的插件清单由源类型注册表派生（app/models/source_types.py），这里不再维护第二份
SYNC_PLUGINS = sync_panel_plugins()


@router.get("/status")
def get_sync_status(db: Session = Depends(get_db)):
    """返回所有 sync 插件的配置状态与统计"""
    expire_stale_progress(db)

    # 一次性查出所有 sync.* 源
    sync_sources = db.query(SourceConfig).filter(
        SourceConfig.source_type.like("sync.%"),
    ).all()
    source_map = {s.source_type: s for s in sync_sources}

    # 「最后同步」取 sync_task_progress 里最近一次成功的同步，而不是 source.last_collected_at：
    # 后者由定时采集器写入，从未同步过的源也会有值，曾让人误判同步已经跑过（2026-09-20）
    last_sync_map = dict(
        db.query(
            SyncTaskProgress.source_id,
            func.max(func.coalesce(SyncTaskProgress.completed_at, SyncTaskProgress.created_at)),
        )
        .filter(SyncTaskProgress.status == "completed")
        .group_by(SyncTaskProgress.source_id)
        .all()
    )

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

        # film 类：统计仍在 Emby 库内的条目数（含手工添加后被 Emby 同步命中的记录）
        if plugin["category"] == "film":
            from app.services.film_library import IS_FILM
            in_emby = (
                db.query(func.count(ContentItem.id))
                .filter(
                    IS_FILM,
                    ContentItem.raw_data["emby"]["in_library"].astext == "true",
                )
                .scalar() or 0
            )
            stats["in_emby"] = in_emby

        # 内置同步与外部推送现在都写 sync_task_progress。script 模式在补记录之前的历史同步
        # 没有进度行，这种情况才退回 last_collected_at
        last_sync = last_sync_map.get(source.id)
        if last_sync is None and plugin["sync_mode"] == "script":
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
    source = db.query(SourceConfig).filter(
        SourceConfig.source_type == source_type,
    ).first()
    if not source:
        return error_response(404, f"同步源 {source_type} 未初始化，请先初始化")

    try:
        progress = await start_sync(db, source, body.options or None, trigger="manual")
    except SyncStartError as e:
        return error_response(e.code, e.message)

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

                result_data = p.result_data if isinstance(p.result_data, (dict, list)) else None

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
def link_credential(
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
