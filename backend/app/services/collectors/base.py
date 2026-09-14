"""采集器基类"""

from abc import ABC, abstractmethod
from contextvars import ContextVar
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem

# 本次 collect() 在源端看到的条目总数（含已存在的）。
# 采集器在 collect() 内调用 report_found()，调度层在 collect() 返回后用 take_found() 读取。
# ContextVar 按 asyncio task 隔离，模块级单例采集器并发采集互不串扰。
_found_count: ContextVar[int | None] = ContextVar("collector_found_count", default=None)


def report_found(count: int) -> None:
    """采集器上报本次在源端发现的条目总数（新旧都算）"""
    _found_count.set(count)


def take_found(default: int) -> int:
    """读取并清空本次上报的发现数；采集器未上报时回退 default（新增数）"""
    value = _found_count.get()
    _found_count.set(None)
    return default if value is None else value


class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        """从数据源抓取新条目

        去重在 DB 层通过 (source_id, external_id) unique constraint 处理。
        返回成功插入的新 ContentItem 列表。
        """
