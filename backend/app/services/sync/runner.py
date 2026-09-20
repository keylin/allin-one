"""同步任务的发起与回收 —— 手动触发（/api/sync/run）与定时自动同步共用

发起 = 建进度行 (sync_task_progress) + 把 run_sync 入队。
"""

import json
import logging
import uuid
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.content import SourceConfig
from app.models.source_types import get_spec
from app.models.sync_progress import SyncTaskProgress

logger = logging.getLogger(__name__)

# 进度行超过这么久没有任何更新，就认定执行它的 worker 已经不在了（重启 / 被杀）
STALE_AFTER = timedelta(minutes=15)


class SyncStartError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def expire_stale_progress(db: Session) -> int:
    """把僵死的同步任务标记为失败

    run_sync 每推进一步都会更新进度行（updated_at 随之刷新）。worker 在执行途中被杀时，
    进度行会永远停在 pending/running，而发起同步时遇到这两种状态一律拒绝 ——
    该数据源从此无法再同步（审计 §4 🔴-5）。查询状态与发起同步前先做一次回收。
    """
    cutoff = utcnow() - STALE_AFTER
    stale = db.query(SyncTaskProgress).filter(
        SyncTaskProgress.status.in_(["pending", "running"]),
        func.coalesce(SyncTaskProgress.updated_at, SyncTaskProgress.created_at) < cutoff,
    ).all()
    for row in stale:
        row.status = "failed"
        row.phase = "done"
        row.error_message = "同步任务中断（执行它的 worker 已重启或退出），请重新触发"
        row.completed_at = utcnow()
    if stale:
        db.commit()
        logger.warning(f"[sync] 回收 {len(stale)} 个僵死的同步任务: {[r.id for r in stale]}")
    return len(stale)


async def start_sync(db: Session, source: SourceConfig, options: dict | None = None,
                     trigger: str = "manual") -> SyncTaskProgress:
    """为一个内置同步型数据源发起一次同步，返回进度行

    Raises:
        SyncStartError: 类型不支持在线同步 / 未绑定凭证 / 已有任务在跑 / 入队失败
    """
    from app.tasks.procrastinate_app import async_defer
    from app.tasks.sync_tasks import run_sync

    spec = get_spec(source.source_type)
    if spec and spec.panel and spec.panel.sync_mode == "script":
        raise SyncStartError(400, f"{spec.panel.name} 需要在本机运行脚本同步，不支持在线触发")
    if spec and spec.credential_required and not source.credential_id:
        raise SyncStartError(400, "未绑定凭证，请先绑定")

    expire_stale_progress(db)
    running = db.query(SyncTaskProgress).filter(
        SyncTaskProgress.source_id == source.id,
        SyncTaskProgress.status.in_(["pending", "running"]),
    ).first()
    if running:
        raise SyncStartError(409, "已有同步任务在进行中，请等待完成")

    progress = SyncTaskProgress(
        id=uuid.uuid4().hex,
        source_id=source.id,
        status="pending",
        options_json={**(options or {}), "_trigger": trigger},
    )
    db.add(progress)
    db.commit()

    try:
        await async_defer(
            run_sync,
            source_id=source.id,
            progress_id=progress.id,
            # options_str 是 JSON 字符串（Procrastinate 任务参数），区别于同名 JSONB 列
            options_str=json.dumps(options, ensure_ascii=False) if options else "{}",
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to defer sync task: {e}")
        progress.status = "failed"
        progress.error_message = f"任务入队失败: {e}"
        progress.completed_at = utcnow()
        db.commit()
        raise SyncStartError(500, "任务入队失败") from e

    return progress


def run_push_sync(db: Session, source: SourceConfig, upsert, items: list[dict]) -> dict:
    """执行一次外部推送的落库，并留下运行记录

    外部脚本 / Fountain 客户端经推送 API 写入时，此前不留任何痕迹：成功与否、何时同步过、
    写了多少，服务端都查不到（审计 §3-C，18 条入口路径里 9 条无痕）。这里与内置同步共用
    sync_task_progress，options_json._trigger = "push" 以示区分。
    """
    started = utcnow()
    progress = SyncTaskProgress(
        id=uuid.uuid4().hex,
        source_id=source.id,
        status="running",
        phase="syncing",
        total=len(items),
        started_at=started,
        options_json={"_trigger": "push"},
    )
    db.add(progress)
    db.commit()
    progress_id, source_id = progress.id, source.id

    try:
        stats = upsert(db, source, items)
    except Exception as e:
        db.rollback()
        row = db.get(SyncTaskProgress, progress_id)
        if row:
            row.status = "failed"
            row.phase = "done"
            row.error_message = str(e)[:2000]
            row.completed_at = utcnow()
            db.commit()
        logger.error(f"[sync] 推送落库失败 source={source_id}: {e}")
        raise

    row = db.get(SyncTaskProgress, progress_id)
    row.status = "completed"
    row.phase = "done"
    row.current = len(items)
    row.result_data = stats
    row.message = f"推送同步完成: {len(items)} 条"
    row.completed_at = utcnow()
    db.commit()
    return stats
