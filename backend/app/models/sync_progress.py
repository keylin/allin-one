"""同步任务进度模型 — Worker → API 的进度通信桥梁"""

import uuid

from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, Index

from app.core.database import Base
from app.core.time import utcnow


def _uuid():
    return uuid.uuid4().hex


class SyncTaskProgress(Base):
    """同步任务进度记录

    Worker 执行同步任务时更新此表，API 轮询此表推送 SSE 事件。
    """
    __tablename__ = "sync_task_progress"

    id = Column(String, primary_key=True, default=_uuid)
    source_id = Column(String, ForeignKey("source_configs.id", ondelete="CASCADE"), nullable=False)

    # 状态
    status = Column(String, default="pending")      # pending / running / completed / failed

    # 进度信息（Worker 逐步更新）
    phase = Column(String, nullable=True)            # fetching / syncing / done
    message = Column(String, nullable=True)
    current = Column(Integer, default=0)
    total = Column(Integer, default=0)

    # 结果
    result_data = Column(Text, nullable=True)        # JSON: 同步统计数据
    error_message = Column(Text, nullable=True)

    # 同步选项（JSON，记录触发时的参数）
    options_json = Column(Text, nullable=True)

    # 时间戳
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_sync_progress_source_status", "source_id", "status"),
        Index("ix_sync_progress_created", "created_at"),
    )
