"""Sources API - 数据源管理"""

import json
import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig, ContentItem, CollectionRecord, SourceType, SourceCategory, get_source_category
from app.models.pipeline import PipelineTemplate
from app.schemas import (
    SourceCreate, SourceUpdate, SourceResponse, CollectionRecordResponse, ContentBatchDelete, error_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _source_to_response(source: SourceConfig, content_counts: dict, template_names: dict) -> dict:
    """将 ORM 对象转为响应 dict（使用预加载的批量数据避免 N+1）"""
    data = SourceResponse.model_validate(source).model_dump()
    data["category"] = get_source_category(source.source_type).value
    data["pipeline_template_name"] = template_names.get(source.pipeline_template_id) if source.pipeline_template_id else None
    data["content_count"] = content_counts.get(source.id, 0)
    return data


def _batch_load_source_extras(sources: list[SourceConfig], db: Session) -> tuple[dict, dict]:
    """批量预加载 content_count 和 template_name，避免 N+1 查询"""
    source_ids = [s.id for s in sources]

    # 一次查询所有 content count
    content_counts = dict(
        db.query(ContentItem.source_id, func.count(ContentItem.id))
        .filter(ContentItem.source_id.in_(source_ids))
        .group_by(ContentItem.source_id)
        .all()
    ) if source_ids else {}

    # 一次查询所有 template name
    template_ids = {s.pipeline_template_id for s in sources if s.pipeline_template_id}
    template_names = dict(
        db.query(PipelineTemplate.id, PipelineTemplate.name)
        .filter(PipelineTemplate.id.in_(template_ids))
        .all()
    ) if template_ids else {}

    return content_counts, template_names


def _validate_source_type(source_type: str) -> str | None:
    """校验 source_type 是否合法，返回错误信息或 None"""
    valid = {e.value for e in SourceType}
    if source_type not in valid:
        return f"Invalid source_type '{source_type}'. Valid: {sorted(valid)}"
    return None


# ---- CRUD ----

@router.get("")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_type: str | None = Query(None),
    category: str | None = Query(None, description="分类筛选: network/user"),
    is_active: bool | None = Query(None),
    q: str | None = Query(None, description="搜索名称或描述"),
    sort_by: str = Query("created_at", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向: asc/desc"),
    db: Session = Depends(get_db),
):
    """获取数据源列表（分页、筛选、排序）"""
    query = db.query(SourceConfig)

    if source_type is not None:
        query = query.filter(SourceConfig.source_type == source_type)
    if category is not None:
        # 根据分类推导出该分类下的所有 source_type 前缀
        category_types = [
            st.value for st in SourceType
            if get_source_category(st.value).value == category
        ]
        if category_types:
            query = query.filter(SourceConfig.source_type.in_(category_types))
    if is_active is not None:
        query = query.filter(SourceConfig.is_active == is_active)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (SourceConfig.name.ilike(pattern)) | (SourceConfig.description.ilike(pattern))
        )

    # 排序字段映射（仅允许白名单字段）
    sort_mapping = {
        "name": SourceConfig.name,
        "created_at": SourceConfig.created_at,
        "last_collected_at": SourceConfig.last_collected_at,
        "next_collection_at": SourceConfig.next_collection_at,
        "calculated_interval": SourceConfig.calculated_interval,
    }

    sort_column = sort_mapping.get(sort_by, SourceConfig.created_at)
    if sort_order.lower() == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    total = query.count()
    sources = query.offset((page - 1) * page_size).limit(page_size).all()

    content_counts, template_names = _batch_load_source_extras(sources, db)
    return {
        "code": 0,
        "data": [_source_to_response(s, content_counts, template_names) for s in sources],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.post("")
async def create_source(body: SourceCreate, db: Session = Depends(get_db)):
    """创建数据源"""
    # 校验 source_type
    err = _validate_source_type(body.source_type)
    if err:
        return error_response(400, err)

    # 验证 RSSHub 源必须有 rsshub_route
    if body.source_type == "rss.hub":
        config = json.loads(body.config_json) if body.config_json else {}
        if not config.get("rsshub_route"):
            return error_response(400, "RSSHub 数据源必须在配置中提供 rsshub_route 字段")

    # 验证标准 RSS 源必须有 url
    elif body.source_type == "rss.standard":
        if not body.url:
            return error_response(400, "RSS/Atom 数据源必须提供 url 字段")

    # 验证 Apple Podcasts 源必须有 apple_podcast_url 或 podcast_id
    elif body.source_type == "podcast.apple":
        config = json.loads(body.config_json) if body.config_json else {}
        if not config.get("apple_podcast_url") and not config.get("podcast_id"):
            return error_response(400, "Apple Podcasts 数据源必须提供 apple_podcast_url 或 podcast_id")

    # 校验 pipeline_template_id
    if body.pipeline_template_id:
        tpl = db.get(PipelineTemplate, body.pipeline_template_id)
        if not tpl:
            return error_response(400, f"Pipeline template '{body.pipeline_template_id}' not found")

    # 名称唯一性校验
    existing = db.query(SourceConfig).filter(SourceConfig.name == body.name.strip()).first()
    if existing:
        return error_response(400, f"数据源「{body.name}」已存在，请使用不同名称")

    data = body.model_dump()

    # 用户类型源自动禁用调度
    if get_source_category(body.source_type) == SourceCategory.USER:
        data["schedule_enabled"] = False

    source = SourceConfig(**data)
    db.add(source)
    db.commit()
    db.refresh(source)

    logger.info(f"Source created: {source.id} ({source.name}, type={source.source_type})")
    content_counts, template_names = _batch_load_source_extras([source], db)
    return {"code": 0, "data": _source_to_response(source, content_counts, template_names), "message": "ok"}


@router.get("/options")
async def list_source_options(db: Session = Depends(get_db)):
    """轻量级来源列表，供下拉框使用"""
    sources = db.query(SourceConfig.id, SourceConfig.name)\
        .filter(SourceConfig.is_active == True)\
        .order_by(SourceConfig.name).all()
    return {"code": 0, "data": [{"id": s.id, "name": s.name} for s in sources], "message": "ok"}



@router.post("/cleanup-duplicates")
async def cleanup_duplicate_sources(db: Session = Depends(get_db)):
    """自动清理同名重复数据源：保留内容最多的（tie-break：最早创建），其余删除"""
    from collections import defaultdict
    from app.models.content import ContentItem
    from app.services.source_cleanup import cascade_delete_source

    # 1. 找出有重复名称的所有源
    dup_name_subq = (
        db.query(SourceConfig.name)
        .group_by(SourceConfig.name)
        .having(func.count(SourceConfig.id) > 1)
        .subquery()
    )
    dup_sources = (
        db.query(SourceConfig)
        .filter(SourceConfig.name.in_(db.query(dup_name_subq.c.name)))
        .order_by(SourceConfig.name, SourceConfig.created_at)
        .all()
    )

    if not dup_sources:
        return {"code": 0, "data": {"groups_cleaned": 0, "sources_deleted": 0, "content_reassigned": 0}, "message": "无重复数据源"}

    # 2. 按名称分组
    groups: dict[str, list] = defaultdict(list)
    for s in dup_sources:
        groups[s.name].append(s)

    groups_cleaned = 0
    sources_deleted = 0
    content_reassigned = 0

    for name, members in groups.items():
        # 3. 选 winner：content_count 最多，tie-break 最早创建
        def sort_key(s):
            cnt = db.query(func.count(ContentItem.id)).filter(ContentItem.source_id == s.id).scalar()
            return (-cnt, s.created_at)
        members.sort(key=sort_key)
        winner = members[0]
        losers = members[1:]
        loser_ids = [s.id for s in losers]

        # 4. 重新归属 loser 的 ContentItem 到 winner
        reassigned = db.query(ContentItem).filter(
            ContentItem.source_id.in_(loser_ids)
        ).update({"source_id": winner.id}, synchronize_session=False)
        content_reassigned += reassigned

        # 5. 删除 losers（内容已迁移，无孤儿内容）
        cascade_delete_source(loser_ids, db, cascade=False)
        sources_deleted += len(loser_ids)
        groups_cleaned += 1

    db.commit()
    logger.info(f"Cleanup duplicates: {groups_cleaned} groups, {sources_deleted} sources deleted, {content_reassigned} items reassigned")
    return {
        "code": 0,
        "data": {"groups_cleaned": groups_cleaned, "sources_deleted": sources_deleted, "content_reassigned": content_reassigned},
        "message": f"清理完成：{groups_cleaned} 组重复，删除 {sources_deleted} 个源，迁移 {content_reassigned} 条内容",
    }


# ---- 单个数据源操作（参数路径必须在字面路径之后） ----

@router.get("/{source_id}")
async def get_source(source_id: str, db: Session = Depends(get_db)):
    """获取单个数据源详情"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")
    content_counts, template_names = _batch_load_source_extras([source], db)
    return {"code": 0, "data": _source_to_response(source, content_counts, template_names), "message": "ok"}


@router.put("/{source_id}")
async def update_source(source_id: str, body: SourceUpdate, db: Session = Depends(get_db)):
    """部分更新数据源"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")

    update_data = body.model_dump(exclude_unset=True)

    # 校验 source_type
    if "source_type" in update_data:
        err = _validate_source_type(update_data["source_type"])
        if err:
            return error_response(400, err)

    # 更新后的 source_type（如果未更新则用现有值）
    final_source_type = update_data.get("source_type", source.source_type)

    # 验证 RSSHub 源必须有 rsshub_route
    if final_source_type == "rss.hub":
        # 如果更新了 config_json，检查新配置；否则检查现有配置
        if "config_json" in update_data:
            config = json.loads(update_data["config_json"]) if update_data["config_json"] else {}
        else:
            config = json.loads(source.config_json) if source.config_json else {}
        if not config.get("rsshub_route"):
            return error_response(400, "RSSHub 数据源必须在配置中提供 rsshub_route 字段")

    # 验证标准 RSS 源必须有 url
    elif final_source_type == "rss.standard":
        final_url = update_data.get("url", source.url)
        if not final_url:
            return error_response(400, "RSS/Atom 数据源必须提供 url 字段")

    # 校验 pipeline_template_id
    if "pipeline_template_id" in update_data and update_data["pipeline_template_id"]:
        tpl = db.get(PipelineTemplate, update_data["pipeline_template_id"])
        if not tpl:
            return error_response(400, f"Pipeline template '{update_data['pipeline_template_id']}' not found")

    # 名称唯一性校验（排除自身）
    if "name" in update_data and update_data["name"].strip() != source.name:
        conflict = db.query(SourceConfig).filter(
            SourceConfig.name == update_data["name"].strip(),
            SourceConfig.id != source_id,
        ).first()
        if conflict:
            return error_response(400, f"数据源「{update_data['name']}」已存在，请使用不同名称")

    for key, value in update_data.items():
        setattr(source, key, value)

    source.updated_at = utcnow()
    db.commit()
    db.refresh(source)

    logger.info(f"Source updated: {source_id} (fields={list(update_data.keys())})")
    content_counts, template_names = _batch_load_source_extras([source], db)
    return {"code": 0, "data": _source_to_response(source, content_counts, template_names), "message": "ok"}


@router.post("/batch-collect")
async def batch_collect_all(db: Session = Depends(get_db)):
    """一键采集所有启用的数据源 — 异步入队"""
    from app.tasks.collection_tasks import collect_single_source
    from app.tasks.procrastinate_app import async_defer

    active_sources = db.query(SourceConfig).filter(SourceConfig.is_active == True).all()
    if not active_sources:
        return {
            "code": 0,
            "data": {"sources_queued": 0, "sources_skipped": 0},
            "message": "没有启用的数据源",
        }

    sources_queued = 0
    sources_skipped = 0

    for source in active_sources:
        try:
            await async_defer(
                collect_single_source,
                queueing_lock=f"collect_{source.id}",
                source_id=source.id,
                trigger="manual",
                use_retry=False,
            )
            sources_queued += 1
        except Exception as e:
            # queueing_lock 冲突时 Procrastinate 会抛 UniqueViolation
            logger.debug(f"Batch collect: source {source.name} already queued or defer failed: {e}")
            sources_skipped += 1

    return {
        "code": 0,
        "data": {
            "sources_queued": sources_queued,
            "sources_skipped": sources_skipped,
        },
        "message": f"{sources_queued} 个采集任务已提交",
    }


@router.post("/batch-delete")
async def batch_delete_sources(
    body: ContentBatchDelete,
    cascade: bool = Query(False, description="是否同时删除关联内容"),
    db: Session = Depends(get_db),
):
    """批量删除数据源

    cascade=false (默认): 仅删除数据源，保留关联内容（source_id 置空）
    cascade=true: 同时删除关联内容及处理记录
    """
    sources = db.query(SourceConfig).filter(SourceConfig.id.in_(body.ids)).all()
    if not sources:
        return {"code": 0, "data": {"deleted": 0}, "message": "ok"}

    source_ids = [s.id for s in sources]

    from app.services.source_cleanup import cascade_delete_source
    result = cascade_delete_source(source_ids, db, cascade)
    db.commit()

    logger.info(f"Batch deleted {result['deleted']} sources (cascade={cascade})")
    return {"code": 0, "data": result, "message": "ok"}


@router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    cascade: bool = Query(False, description="是否同时删除关联内容"),
    db: Session = Depends(get_db),
):
    """删除数据源

    cascade=false (默认): 仅删除数据源，保留关联内容（source_id 置空）
    cascade=true: 同时删除关联内容及处理记录
    """
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")

    from app.services.source_cleanup import cascade_delete_source
    result = cascade_delete_source([source_id], db, cascade)
    db.commit()

    logger.info(f"Source deleted: {source_id} (cascade={cascade})")
    return {"code": 0, "data": result, "message": "ok"}


# ---- 手动采集 ----

@router.post("/{source_id}/collect")
async def trigger_collect(source_id: str, db: Session = Depends(get_db)):
    """手动触发采集 — 异步入队"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")

    from app.tasks.collection_tasks import collect_single_source
    from app.tasks.procrastinate_app import async_defer

    try:
        await async_defer(
            collect_single_source,
            queueing_lock=f"collect_{source.id}",
            source_id=source.id,
            trigger="manual",
            use_retry=False,
        )
        return {
            "code": 0,
            "data": {"status": "queued"},
            "message": "采集任务已提交",
        }
    except Exception as e:
        logger.debug(f"Manual collect: source {source.name} already queued: {e}")
        return {
            "code": 0,
            "data": {"status": "already_queued"},
            "message": "采集任务已在队列中",
        }


# ---- 采集历史 ----

@router.get("/{source_id}/history")
async def get_collection_history(
    source_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查看采集历史"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")

    query = db.query(CollectionRecord).filter(CollectionRecord.source_id == source_id)
    total = query.count()
    records = query.order_by(CollectionRecord.started_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "code": 0,
        "data": [CollectionRecordResponse.model_validate(r).model_dump() for r in records],
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }
