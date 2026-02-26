"""同步 Fetcher 基类 — 平台抓取 + DB upsert 的公共抽象"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from sqlalchemy.orm import Session


@dataclass
class SyncProgress:
    """进度回调数据"""
    phase: str = ""        # e.g. "fetching", "syncing", "done"
    message: str = ""
    current: int = 0
    total: int = 0


# 回调签名: async (SyncProgress) -> None
ProgressCallback = Callable[[SyncProgress], Awaitable[None]]


@dataclass
class SyncResult:
    """同步最终结果"""
    success: bool = True
    stats: dict = field(default_factory=dict)
    error: str | None = None


class BaseSyncFetcher(ABC):
    """平台同步 Fetcher 抽象基类

    子类实现:
      - validate_credential(credential_data) → tuple[bool, str]
      - fetch_and_sync(db, source, credential_data, options, on_progress) → SyncResult
    """

    @abstractmethod
    async def validate_credential(self, credential_data: str) -> tuple[bool, str]:
        """验证凭证是否有效

        Returns:
            (valid, reason) — reason 为空字符串表示成功,
            否则为失败原因: "missing_fields", "expired", "error"
        """
        ...

    @abstractmethod
    async def fetch_and_sync(
        self,
        db: Session,
        source: Any,
        credential_data: str,
        options: dict,
        on_progress: ProgressCallback | None = None,
    ) -> SyncResult:
        """抓取平台数据并写入 DB

        Args:
            db: 数据库 Session
            source: SourceConfig 实例
            credential_data: 凭证原始数据（Cookie 字符串等）
            options: 平台特定选项（如 sync_type, media_id）
            on_progress: 进度回调
        """
        ...

    @staticmethod
    def get_sync_options() -> list[dict]:
        """返回该平台支持的同步选项定义（供前端渲染表单）

        Returns:
            [{"key": "sync_type", "label": "同步类型", "type": "select",
              "options": [...], "default": "favorites"}, ...]
        """
        return []
