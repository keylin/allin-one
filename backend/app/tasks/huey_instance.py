"""Huey 任务队列实例"""

from huey import SqliteHuey

huey = SqliteHuey(
    filename="data/db/huey.db",
    immediate=False,
)

# 导入 task 模块，确保 @huey.task() 装饰的函数注册到 TaskRegistry
import app.tasks.pipeline_tasks  # noqa: F401, E402
