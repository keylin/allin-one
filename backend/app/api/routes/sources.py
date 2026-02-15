"""Sources API - 数据源管理"""

import json
import logging
from fastapi import APIRouter, Depends, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
import xml.etree.ElementTree as ET

from app.core.config import settings
from app.core.database import get_db
from app.core.time import utcnow
from app.models.content import SourceConfig, ContentItem, CollectionRecord, SourceType, MediaItem
from app.models.finance import FinanceDataPoint
from app.models.pipeline import PipelineTemplate, PipelineExecution, PipelineStep
from app.schemas import (
    SourceCreate, SourceUpdate, SourceResponse, CollectionRecordResponse, ContentBatchDelete, error_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---- RSS 辅助 ----

_RSS_TYPES = {"rss.standard", "rss.hub"}


def _resolve_rss_feed_url(source_type: str, url: str | None, config: dict) -> str:
    """根据源类型解析出实际的 RSS feed URL"""
    if source_type == "rss.hub":
        rsshub_route = config.get("rsshub_route") or url or ""
        return f"{settings.RSSHUB_URL.rstrip('/')}{rsshub_route}"
    # rss.standard → 直接用 url
    return url or ""


def _source_to_response(source: SourceConfig, db: Session) -> dict:
    """将 ORM 对象转为响应 dict，解析 pipeline_template_name 和 content_count"""
    data = SourceResponse.model_validate(source).model_dump()
    if source.pipeline_template_id:
        tpl = db.get(PipelineTemplate, source.pipeline_template_id)
        data["pipeline_template_name"] = tpl.name if tpl else None
    data["content_count"] = db.query(func.count(ContentItem.id)).filter(
        ContentItem.source_id == source.id
    ).scalar()

    # next_collection_at 已由系统计算并存储在数据库，直接使用
    # 由 SchedulingService.update_next_collection_time() 维护
    return data


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

    return {
        "code": 0,
        "data": [_source_to_response(s, db) for s in sources],
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

    # 校验 pipeline_template_id
    if body.pipeline_template_id:
        tpl = db.get(PipelineTemplate, body.pipeline_template_id)
        if not tpl:
            return error_response(400, f"Pipeline template '{body.pipeline_template_id}' not found")

    data = body.model_dump()

    source = SourceConfig(**data)
    db.add(source)
    db.commit()
    db.refresh(source)

    logger.info(f"Source created: {source.id} ({source.name}, type={source.source_type})")
    return {"code": 0, "data": _source_to_response(source, db), "message": "ok"}


@router.get("/options")
async def list_source_options(db: Session = Depends(get_db)):
    """轻量级来源列表，供下拉框使用"""
    sources = db.query(SourceConfig.id, SourceConfig.name)\
        .filter(SourceConfig.is_active == True)\
        .order_by(SourceConfig.name).all()
    return {"code": 0, "data": [{"id": s.id, "name": s.name} for s in sources], "message": "ok"}


# ---- OPML 导入导出 ----

@router.post("/import")
async def import_opml(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """导入 OPML 文件批量创建 RSS 源"""
    try:
        # 读取文件内容
        content = await file.read()
        xml_text = content.decode("utf-8")

        # 解析 OPML XML
        root = ET.fromstring(xml_text)

        # OPML 格式: <opml><body><outline ... /></body></opml>
        outlines = root.findall(".//outline[@type='rss']") or root.findall(".//outline[@xmlUrl]")

        if not outlines:
            return error_response(400, "未找到有效的 RSS 订阅源")

        created = 0
        skipped = 0
        errors = []

        for outline in outlines:
            try:
                # 提取属性
                title = outline.get("title") or outline.get("text", "Untitled")
                xml_url = outline.get("xmlUrl")
                html_url = outline.get("htmlUrl")
                description = outline.get("description", "")

                if not xml_url:
                    skipped += 1
                    continue

                # 检查是否已存在
                existing = db.query(SourceConfig).filter(SourceConfig.url == xml_url).first()
                if existing:
                    skipped += 1
                    continue

                # 创建数据源
                source = SourceConfig(
                    name=title[:200],
                    source_type=SourceType.RSS_STANDARD.value,
                    url=xml_url,
                    description=description[:500] if description else None,
                    schedule_enabled=True,
                    schedule_mode="auto",  # 智能调度
                    is_active=True,
                )
                db.add(source)
                created += 1

            except Exception as e:
                errors.append(f"{title}: {str(e)}")
                continue

        db.commit()

        logger.info(f"OPML imported: created={created}, skipped={skipped}, errors={len(errors)}")
        return {
            "code": 0,
            "data": {
                "created": created,
                "skipped": skipped,
                "errors": errors,
            },
            "message": f"导入完成: 新增 {created} 个源，跳过 {skipped} 个",
        }

    except ET.ParseError as e:
        return error_response(400, f"OPML 解析失败: {str(e)}")
    except Exception as e:
        return error_response(500, f"导入失败: {str(e)}")


@router.get("/export")
async def export_opml(
    db: Session = Depends(get_db),
):
    """导出 RSS 源为 OPML 文件"""
    sources = db.query(SourceConfig).filter(
        SourceConfig.source_type.in_([
            SourceType.RSS_HUB.value,
            SourceType.RSS_STANDARD.value,
        ])
    ).all()

    # 构建 OPML XML
    opml = ET.Element("opml", version="2.0")

    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "Allin-One RSS Subscriptions"
    ET.SubElement(head, "dateCreated").text = utcnow().isoformat()

    body = ET.SubElement(opml, "body")

    for source in sources:
        outline = ET.SubElement(
            body,
            "outline",
            type="rss",
            text=source.name,
            title=source.name,
            xmlUrl=source.url or "",
        )
        if source.description:
            outline.set("description", source.description)

    # 转为 XML 字符串
    xml_string = ET.tostring(opml, encoding="utf-8", method="xml")
    xml_declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    opml_content = xml_declaration + xml_string

    return Response(
        content=opml_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="allin-one-feeds-{datetime.now().strftime("%Y%m%d")}.opml"'
        },
    )


# ---- 单个数据源操作（参数路径必须在字面路径之后） ----

@router.get("/{source_id}")
async def get_source(source_id: str, db: Session = Depends(get_db)):
    """获取单个数据源详情"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")
    return {"code": 0, "data": _source_to_response(source, db), "message": "ok"}


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

    # 校验 pipeline_template_id
    if "pipeline_template_id" in update_data and update_data["pipeline_template_id"]:
        tpl = db.get(PipelineTemplate, update_data["pipeline_template_id"])
        if not tpl:
            return error_response(400, f"Pipeline template '{update_data['pipeline_template_id']}' not found")

    for key, value in update_data.items():
        setattr(source, key, value)

    source.updated_at = utcnow()
    db.commit()
    db.refresh(source)

    logger.info(f"Source updated: {source_id} (fields={list(update_data.keys())})")
    return {"code": 0, "data": _source_to_response(source, db), "message": "ok"}


@router.post("/batch-collect")
async def batch_collect_all(db: Session = Depends(get_db)):
    """一键采集所有启用的数据源"""
    from app.services.collectors import collect_source
    from app.services.pipeline.orchestrator import PipelineOrchestrator
    from app.services.scheduling_service import SchedulingService
    from app.models.pipeline import TriggerSource

    active_sources = db.query(SourceConfig).filter(SourceConfig.is_active == True).all()
    if not active_sources:
        return {
            "code": 0,
            "data": {"sources_collected": 0, "total_items_new": 0, "pipelines_started": 0, "errors": []},
            "message": "没有启用的数据源",
        }

    orchestrator = PipelineOrchestrator(db)
    sources_collected = 0
    total_items_new = 0
    pipelines_started = 0
    errors = []

    for source in active_sources:
        try:
            new_items = await collect_source(source, db)
            sources_collected += 1
            total_items_new += len(new_items)

            source.last_collected_at = utcnow()
            source.consecutive_failures = 0

            # ✨ 更新智能调度时间
            SchedulingService.update_next_collection_time(source, db)

            db.flush()

            for item in new_items:
                execution = orchestrator.trigger_for_content(
                    content=item,
                    trigger=TriggerSource.MANUAL,
                )
                if execution:
                    await orchestrator.async_start_execution(execution.id)
                    pipelines_started += 1
        except Exception as e:
            logger.warning(f"Batch collect failed for source {source.id} ({source.name}): {e}")
            errors.append(f"{source.name}: {str(e)}")

    db.commit()

    return {
        "code": 0,
        "data": {
            "sources_collected": sources_collected,
            "total_items_new": total_items_new,
            "pipelines_started": pipelines_started,
            "errors": errors,
        },
        "message": f"采集完成: {sources_collected} 个源，{total_items_new} 条新内容",
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

    content_count = db.query(func.count(ContentItem.id)).filter(
        ContentItem.source_id.in_(source_ids)
    ).scalar()

    if cascade and content_count > 0:
        # 级联删除关联数据
        content_ids = [
            cid for (cid,) in db.query(ContentItem.id)
            .filter(ContentItem.source_id.in_(source_ids)).all()
        ]
        execution_ids = [
            eid for (eid,) in db.query(PipelineExecution.id)
            .filter(PipelineExecution.content_id.in_(content_ids)).all()
        ]
        if execution_ids:
            db.query(PipelineStep).filter(
                PipelineStep.pipeline_id.in_(execution_ids)
            ).delete(synchronize_session=False)
            db.query(PipelineExecution).filter(
                PipelineExecution.id.in_(execution_ids)
            ).delete(synchronize_session=False)
        db.query(MediaItem).filter(
            MediaItem.content_id.in_(content_ids)
        ).delete(synchronize_session=False)
        db.query(ContentItem).filter(
            ContentItem.source_id.in_(source_ids)
        ).delete(synchronize_session=False)
    elif content_count > 0:
        # 保留内容，断开关联
        db.query(ContentItem).filter(
            ContentItem.source_id.in_(source_ids)
        ).update({"source_id": None}, synchronize_session=False)

    # 清理 CollectionRecord 和 FinanceDataPoint
    db.query(CollectionRecord).filter(
        CollectionRecord.source_id.in_(source_ids)
    ).delete(synchronize_session=False)
    db.query(FinanceDataPoint).filter(
        FinanceDataPoint.source_id.in_(source_ids)
    ).delete(synchronize_session=False)

    # 清理以 source_id 关联的 pipeline_executions
    orphan_exec_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.source_id.in_(source_ids)).all()
    ]
    if orphan_exec_ids:
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)

    deleted = db.query(SourceConfig).filter(
        SourceConfig.id.in_(source_ids)
    ).delete(synchronize_session=False)
    db.commit()

    logger.info(f"Batch deleted {deleted} sources (cascade={cascade}, content_kept={content_count if not cascade else 0})")
    return {"code": 0, "data": {"deleted": deleted, "content_count": content_count, "content_deleted": cascade}, "message": "ok"}


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

    content_count = db.query(func.count(ContentItem.id)).filter(ContentItem.source_id == source_id).scalar()

    if cascade and content_count > 0:
        # 级联删除: pipeline_steps → pipeline_executions → content_items
        content_ids = [
            cid for (cid,) in db.query(ContentItem.id)
            .filter(ContentItem.source_id == source_id).all()
        ]
        execution_ids = [
            eid for (eid,) in db.query(PipelineExecution.id)
            .filter(PipelineExecution.content_id.in_(content_ids)).all()
        ]
        if execution_ids:
            db.query(PipelineStep).filter(
                PipelineStep.pipeline_id.in_(execution_ids)
            ).delete(synchronize_session=False)
            db.query(PipelineExecution).filter(
                PipelineExecution.id.in_(execution_ids)
            ).delete(synchronize_session=False)
        db.query(MediaItem).filter(
            MediaItem.content_id.in_(content_ids)
        ).delete(synchronize_session=False)
        db.query(ContentItem).filter(
            ContentItem.source_id == source_id
        ).delete(synchronize_session=False)
    elif content_count > 0:
        # 保留内容，断开关联
        db.query(ContentItem).filter(
            ContentItem.source_id == source_id
        ).update({"source_id": None}, synchronize_session=False)

    # 清理 CollectionRecord 和 FinanceDataPoint
    db.query(CollectionRecord).filter(
        CollectionRecord.source_id == source_id
    ).delete(synchronize_session=False)
    db.query(FinanceDataPoint).filter(
        FinanceDataPoint.source_id == source_id
    ).delete(synchronize_session=False)

    # 清理以 source_id 关联的 pipeline_executions
    orphan_exec_ids = [
        eid for (eid,) in db.query(PipelineExecution.id)
        .filter(PipelineExecution.source_id == source_id).all()
    ]
    if orphan_exec_ids:
        db.query(PipelineStep).filter(
            PipelineStep.pipeline_id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)
        db.query(PipelineExecution).filter(
            PipelineExecution.id.in_(orphan_exec_ids)
        ).delete(synchronize_session=False)

    db.delete(source)
    db.commit()

    logger.info(f"Source deleted: {source_id} (cascade={cascade}, content_kept={content_count if not cascade else 0})")
    return {"code": 0, "data": {"content_count": content_count, "content_deleted": cascade}, "message": "ok"}


# ---- 手动采集 ----

@router.post("/{source_id}/collect")
async def trigger_collect(source_id: str, db: Session = Depends(get_db)):
    """手动触发采集"""
    source = db.get(SourceConfig, source_id)
    if not source:
        return error_response(404, "Source not found")

    from app.services.collectors import collect_source
    from app.services.pipeline.orchestrator import PipelineOrchestrator
    from app.services.scheduling_service import SchedulingService
    from app.models.pipeline import TriggerSource

    try:
        new_items = await collect_source(source, db)

        # 更新采集时间 (与 scheduled_tasks 保持一致)
        source.last_collected_at = utcnow()
        source.consecutive_failures = 0

        # ✨ 更新智能调度时间
        SchedulingService.update_next_collection_time(source, db)

        db.flush()

        # 对新内容触发关联流水线
        orchestrator = PipelineOrchestrator(db)
        pipelines_started = 0
        for item in new_items:
            execution = orchestrator.trigger_for_content(
                content=item,
                trigger=TriggerSource.MANUAL,
            )
            if execution:
                await orchestrator.async_start_execution(execution.id)
                pipelines_started += 1

        # 获取最近一条 CollectionRecord 用于响应
        record = (
            db.query(CollectionRecord)
            .filter(CollectionRecord.source_id == source_id)
            .order_by(CollectionRecord.started_at.desc())
            .first()
        )

        return {
            "code": 0,
            "data": {
                "record": CollectionRecordResponse.model_validate(record).model_dump() if record else None,
                "items_found": len(new_items),
                "items_new": len(new_items),
                "pipelines_started": pipelines_started,
            },
            "message": f"采集完成: 发现 {len(new_items)} 条新内容",
        }
    except Exception as e:
        logger.exception(f"Manual collect failed for source {source_id}")
        return error_response(500, f"采集失败: {str(e)}")


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
