"""视频同步 API — 接收外置脚本推送的视频数据（支持 B站等平台）"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import ContentItem, SourceConfig, SourceType
from app.models.source_types import push_types_for_domain
from app.schemas import error_response
from app.schemas.video_sync import (
    VideoSyncRequest,
    VideoSyncResponse,
    VideoSyncStatus,
)
from app.services.sync.upsert import upsert_videos

logger = logging.getLogger(__name__)
router = APIRouter()

# 平台名称映射（source_type value → 显示名称）
_PLATFORM_NAMES = {
    SourceType.SYNC_BILIBILI.value: "Bilibili",
}


def _platform_name(source_type: str) -> str:
    return _PLATFORM_NAMES.get(source_type, source_type.split(".")[-1].replace("_", " ").title())


# ─── Setup ────────────────────────────────────────────────────────────────────

@router.post("/sync/setup")
def setup_video_sync(
    source_type: str = Query(SourceType.SYNC_BILIBILI.value),
    db: Session = Depends(get_db),
):
    """首次设置 — 自动创建 sync.* 类型的 SourceConfig"""
    # 只接受本领域、已实现、接受外部推送的数据源类型（由源类型注册表决定）
    if source_type not in push_types_for_domain("video"):
        return error_response(400, f"{source_type} 不是可用的视频同步源类型")

    existing = db.query(SourceConfig).filter(
        SourceConfig.source_type == source_type,
    ).first()
    if existing:
        return {
            "code": 0,
            "data": {"source_id": existing.id},
            "message": f"已存在 {_platform_name(source_type)} 同步源",
        }

    name = _platform_name(source_type)
    source = SourceConfig(
        id=uuid.uuid4().hex,
        name=name,
        source_type=source_type,
        schedule_enabled=False,
        schedule_mode="manual",
        is_active=True,
    )
    db.add(source)
    db.commit()

    logger.info(f"Created video sync source: {source.id} ({source_type})")
    return {
        "code": 0,
        "data": {"source_id": source.id},
        "message": f"{name} 同步源创建成功",
    }


# ─── Sync Status ──────────────────────────────────────────────────────────────

@router.get("/sync/status")
def get_sync_status(
    source_id: str = Query(...),
    db: Session = Depends(get_db),
):
    """同步状态 — 返回最后同步时间、视频总数"""
    source = db.get(SourceConfig, source_id)
    if not source or not source.source_type.startswith("sync."):
        return {"code": 0, "data": VideoSyncStatus().model_dump(), "message": "ok"}

    total_videos = db.query(func.count(ContentItem.id)).filter(
        ContentItem.source_id == source.id,
    ).scalar() or 0

    last_sync = source.last_collected_at

    return {
        "code": 0,
        "data": VideoSyncStatus(
            source_id=source.id,
            last_sync_at=last_sync.isoformat() if last_sync else None,
            total_videos=total_videos,
        ).model_dump(),
        "message": "ok",
    }


# ─── Full Sync ────────────────────────────────────────────────────────────────

@router.post("/sync")
def sync_videos(
    body: VideoSyncRequest,
    db: Session = Depends(get_db),
):
    """全量/增量同步 — 接收视频元数据、播放进度"""
    source = db.get(SourceConfig, body.source_id)
    if not source or source.source_type not in push_types_for_domain("video"):
        return error_response(404, "同步源不存在，或不属于视频领域")

    # 将 Pydantic 模型转为 dict 列表
    videos_dicts = [v.model_dump(by_alias=False) for v in body.videos]
    stats = upsert_videos(db, source, videos_dicts)

    platform = _platform_name(source.source_type)
    logger.info(
        f"{platform} video sync completed: "
        f"{stats['new_videos']} new, {stats['updated_videos']} updated"
    )

    return {
        "code": 0,
        "data": stats,
        "message": "同步完成",
    }
