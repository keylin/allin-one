"""同步任务 — Procrastinate Worker 中执行平台数据抓取 + DB upsert"""

import json
import logging

from app.tasks.procrastinate_app import proc_app

logger = logging.getLogger(__name__)


@proc_app.task(queue="scheduled")
async def run_sync(source_id: str, progress_id: str, options_json: str = "{}"):
    """执行同步任务

    由 POST /api/sync/run 触发，Worker 异步执行。
    通过更新 SyncTaskProgress 行传递进度信息。

    Args:
        source_id: SourceConfig.id
        progress_id: SyncTaskProgress.id
        options_json: JSON 字符串，平台特定选项
    """
    from app.core.database import SessionLocal
    from app.core.time import utcnow
    from app.models.content import SourceConfig
    from app.models.credential import PlatformCredential
    from app.models.sync_progress import SyncTaskProgress
    from app.services.sync import SYNC_FETCHERS
    from app.services.sync.base import SyncProgress

    options = json.loads(options_json) if options_json else {}

    with SessionLocal() as db:
        # 加载进度记录
        progress = db.get(SyncTaskProgress, progress_id)
        if not progress:
            logger.error(f"SyncTaskProgress not found: {progress_id}")
            return

        # 标记 running
        progress.status = "running"
        progress.started_at = utcnow()
        progress.phase = "initializing"
        progress.message = "正在初始化同步任务..."
        db.commit()

        try:
            # 加载 SourceConfig
            source = db.get(SourceConfig, source_id)
            if not source:
                progress.status = "failed"
                progress.error_message = "同步源不存在"
                progress.completed_at = utcnow()
                db.commit()
                return

            # 查找 Fetcher
            fetcher_cls = SYNC_FETCHERS.get(source.source_type)
            if not fetcher_cls:
                progress.status = "failed"
                progress.error_message = f"不支持的同步类型: {source.source_type}"
                progress.completed_at = utcnow()
                db.commit()
                return

            # 读取凭证
            if not source.credential_id:
                progress.status = "failed"
                progress.error_message = "未绑定凭证，请先绑定 Cookie"
                progress.completed_at = utcnow()
                db.commit()
                return

            credential = db.get(PlatformCredential, source.credential_id)
            if not credential:
                progress.status = "failed"
                progress.error_message = "凭证不存在"
                progress.completed_at = utcnow()
                db.commit()
                return

            if credential.status == "expired":
                progress.status = "failed"
                progress.error_message = "凭证已过期，请更新"
                progress.completed_at = utcnow()
                db.commit()
                return

            # 进度回调
            async def on_progress(p: SyncProgress):
                progress.phase = p.phase
                progress.message = p.message
                progress.current = p.current
                progress.total = p.total
                progress.updated_at = utcnow()
                db.commit()

            # 执行同步
            fetcher = fetcher_cls()
            result = await fetcher.fetch_and_sync(
                db=db,
                source=source,
                credential_data=credential.credential_data,
                options=options,
                on_progress=on_progress,
            )

            # 写入结果
            if result.success:
                progress.status = "completed"
                progress.phase = "done"
                progress.result_data = json.dumps(result.stats, ensure_ascii=False)
                progress.message = result.stats.get("message", "同步完成")
            else:
                progress.status = "failed"
                progress.error_message = result.error

            progress.completed_at = utcnow()
            db.commit()

            logger.info(
                f"Sync task {progress_id} completed: "
                f"source={source_id}, status={progress.status}"
            )

        except Exception as e:
            logger.exception(f"Sync task {progress_id} failed with exception")
            progress.status = "failed"
            progress.error_message = str(e)
            progress.completed_at = utcnow()
            db.commit()
