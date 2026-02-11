"""采集器基类"""

from abc import ABC, abstractmethod
from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem


class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        """从数据源抓取新条目

        去重在 DB 层通过 (source_id, external_id) unique constraint 处理。
        返回成功插入的新 ContentItem 列表。
        """
