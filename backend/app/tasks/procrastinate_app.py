"""Procrastinate 任务队列实例 — PostgreSQL backed

架构说明:
- proc_app: PsycopgConnector (异步), 供 Worker CLI 使用
- _defer_app: SyncPsycopgConnector (同步), 供 sync_defer() 从同步代码提交任务
- 任务通过 @proc_app.task / @proc_app.periodic 注册在 proc_app 上
- sync_defer 通过 _defer_app.configure_task(name) 以同步方式入队
"""

import procrastinate
from app.core.config import settings
from app.core.logging_config import setup_logging

setup_logging("worker")

# 主 App — 异步连接器, Worker CLI 使用
proc_app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=settings.DATABASE_URL),
    import_paths=["app.tasks.pipeline_tasks", "app.tasks.scheduled_tasks"],
)

import app.models  # noqa: F401 — 确保所有 ORM 模型注册
import app.tasks.pipeline_tasks  # noqa: F401, E402
import app.tasks.scheduled_tasks  # noqa: F401, E402

# 同步 defer 专用 App — SyncPsycopgConnector, 惰性初始化
_defer_app: procrastinate.App | None = None


def _get_defer_app() -> procrastinate.App:
    global _defer_app
    if _defer_app is None:
        _defer_app = procrastinate.App(
            connector=procrastinate.SyncPsycopgConnector(conninfo=settings.DATABASE_URL),
        )
        _defer_app.open()
    return _defer_app


def sync_defer(task, queueing_lock: str | None = None, **kwargs):
    """在同步上下文中提交任务到 Procrastinate

    通过独立的 SyncPsycopgConnector 入队, 不依赖异步事件循环。
    仅供 executor.py 等同步 worker 线程使用。

    Args:
        task: Procrastinate task (decorated function)
        queueing_lock: 可选的排队锁，防止同一锁的任务并发执行
        **kwargs: Task arguments

    Returns:
        Job ID
    """
    app = _get_defer_app()
    queue = task.queue or "default"
    config_kwargs = {"queue": queue}
    if queueing_lock:
        config_kwargs["queueing_lock"] = queueing_lock
    return app.configure_task(task.name, **config_kwargs).defer(**kwargs)


async def async_defer(task, queueing_lock: str | None = None, **kwargs):
    """在异步上下文中提交任务到 Procrastinate

    通过 proc_app (PsycopgConnector) 的异步 API 入队。
    供 async periodic tasks、async FastAPI handlers 使用。

    Args:
        task: Procrastinate task (decorated function)
        queueing_lock: 可选的排队锁，防止同一锁的任务并发执行
        **kwargs: Task arguments

    Returns:
        Job ID
    """
    queue = task.queue or "default"
    config_kwargs = {"queue": queue}
    if queueing_lock:
        config_kwargs["queueing_lock"] = queueing_lock
    return await proc_app.configure_task(task.name, **config_kwargs).defer_async(**kwargs)
