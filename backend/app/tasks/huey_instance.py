"""Huey 任务队列实例"""

from huey import SqliteHuey

huey = SqliteHuey(
    filename="data/db/huey.db",
    immediate=False,
)
