"""Pipelines API - 流水线管理"""

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.content import ContentItem
from app.models.pipeline import PipelineExecution, PipelineStep, PipelineStatus
from app.schemas import (
    PipelineResponse, PipelineDetailResponse, PipelineStepResponse, error_response,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_pipelines(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    source_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """查询 Pipeline 执行记录"""
    query = db.query(PipelineExecution)

    if status:
        query = query.filter(PipelineExecution.status == status)
    if source_id:
        query = query.filter(PipelineExecution.source_id == source_id)

    total = query.count()
    executions = (
        query.order_by(PipelineExecution.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    data = []
    for ex in executions:
        item = PipelineResponse.model_validate(ex).model_dump()
        content = db.get(ContentItem, ex.content_id)
        item["content_title"] = content.title if content else None
        data.append(item)

    return {
        "code": 0,
        "data": data,
        "total": total,
        "page": page,
        "page_size": page_size,
        "message": "ok",
    }


@router.post("/manual")
async def manual_pipeline(
    body: dict,
    db: Session = Depends(get_db),
):
    """手动触发 Pipeline"""
    from app.models.pipeline import TriggerSource
    from app.models.content import ContentStatus
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    content_id = body.get("content_id")
    template_id = body.get("template_id")

    if not content_id:
        return error_response(400, "content_id is required")

    content = db.get(ContentItem, content_id)
    if not content:
        return error_response(404, "Content not found")

    orchestrator = PipelineOrchestrator(db)

    try:
        execution = orchestrator.trigger_for_content(
            content=content,
            template_override_id=template_id,
            trigger=TriggerSource.MANUAL,
        )
        if not execution:
            return error_response(400, "无法创建 Pipeline，请检查模板配置")

        content.status = ContentStatus.PROCESSING.value
        db.commit()

        orchestrator.start_execution(execution.id)

        return {
            "code": 0,
            "data": {"pipeline_execution_id": execution.id},
            "message": "Pipeline 已启动",
        }
    except Exception as e:
        logger.exception(f"Manual pipeline failed for content {content_id}")
        return error_response(500, f"Pipeline 创建失败: {str(e)}")


@router.post("/test-step")
async def test_step(
    body: dict,
    db: Session = Depends(get_db),
):
    """手动测试单个步骤处理器 — 同步执行，立即返回结果

    body:
        step_type: str — 步骤类型 (必填)
        content_id: str — 目标内容 ID (可选, 提供真实内容)
        step_config: dict — 步骤配置 (可选)
        test_input: dict — 模拟输入 (无 content_id 时使用)
    """
    from app.tasks.pipeline_tasks import STEP_HANDLERS

    step_type = body.get("step_type")
    content_id = body.get("content_id")
    step_config = body.get("step_config", {})
    test_input = body.get("test_input", {})

    if not step_type:
        return error_response(400, "step_type is required")

    handler = STEP_HANDLERS.get(step_type)
    if not handler:
        return error_response(400, f"Unknown step_type: {step_type}")

    # 构建 context
    context = {
        "execution_id": "__test__",
        "content_id": content_id or "__test__",
        "source_id": None,
        "template_name": "__test__",
        "content_url": None,
        "content_title": None,
        "step_type": step_type,
        "step_config": step_config,
        "previous_steps": {},
    }

    # 如果指定了真实 content_id，补充上下文
    if content_id:
        content = db.get(ContentItem, content_id)
        if not content:
            return error_response(404, f"Content not found: {content_id}")
        context["content_url"] = content.url
        context["content_title"] = content.title
        context["source_id"] = content.source_id

    # 如果提供了 test_input，设为 previous_steps
    if test_input:
        context["previous_steps"] = test_input

    start_time = time.time()
    try:
        result = handler(context)
        elapsed = round(time.time() - start_time, 2)

        return {
            "code": 0,
            "data": {
                "step_type": step_type,
                "status": "success",
                "result": result,
                "elapsed_seconds": elapsed,
            },
            "message": f"步骤 {step_type} 测试成功 ({elapsed}s)",
        }

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        logger.warning(f"[test-step] {step_type} failed: {e}")

        return {
            "code": 0,  # 不返回 HTTP 错误，将错误信息放在 data 中
            "data": {
                "step_type": step_type,
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "elapsed_seconds": elapsed,
            },
            "message": f"步骤 {step_type} 测试失败 ({elapsed}s)",
        }


# ---- 单个 Pipeline 操作（参数路径必须在字面路径之后） ----

@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str, db: Session = Depends(get_db)):
    """获取 Pipeline 详情（含步骤）"""
    execution = db.get(PipelineExecution, pipeline_id)
    if not execution:
        return error_response(404, "Pipeline execution not found")

    data = PipelineDetailResponse.model_validate(execution).model_dump()
    content = db.get(ContentItem, execution.content_id)
    data["content_title"] = content.title if content else None
    data["steps"] = [
        PipelineStepResponse.model_validate(s).model_dump()
        for s in execution.steps
    ]

    return {"code": 0, "data": data, "message": "ok"}


@router.post("/{pipeline_id}/cancel")
async def cancel_pipeline(pipeline_id: str, db: Session = Depends(get_db)):
    """取消 Pipeline 执行"""
    execution = db.get(PipelineExecution, pipeline_id)
    if not execution:
        return error_response(404, "Pipeline execution not found")

    if execution.status in (PipelineStatus.COMPLETED.value, PipelineStatus.CANCELLED.value):
        return error_response(400, f"Cannot cancel pipeline in '{execution.status}' status")

    execution.status = PipelineStatus.CANCELLED.value
    execution.completed_at = datetime.now(timezone.utc)

    # 取消所有 pending 的步骤
    for step in execution.steps:
        if step.status == "pending":
            step.status = "skipped"

    db.commit()

    logger.info(f"Pipeline cancelled: {pipeline_id}")
    return {"code": 0, "data": None, "message": "Pipeline 已取消"}


@router.post("/{pipeline_id}/retry")
async def retry_pipeline(
    pipeline_id: str,
    db: Session = Depends(get_db),
):
    """重试失败的流水线"""
    from app.models.pipeline import StepStatus
    from app.services.pipeline.orchestrator import PipelineOrchestrator

    execution = db.get(PipelineExecution, pipeline_id)
    if not execution:
        return error_response(404, "Pipeline not found")

    # 只能重试失败的流水线
    if execution.status != PipelineStatus.FAILED.value:
        return error_response(400, f"只能重试失败的流水线，当前状态: {execution.status}")

    # 重置失败的步骤
    failed_steps = db.query(PipelineStep).filter(
        PipelineStep.pipeline_id == pipeline_id,
        PipelineStep.status == StepStatus.FAILED.value,
    ).all()

    if not failed_steps:
        return error_response(400, "没有失败的步骤需要重试")

    # 重置步骤状态
    for step in failed_steps:
        step.status = StepStatus.PENDING.value
        step.error_message = None
        step.started_at = None
        step.completed_at = None

    # 重置流水线状态
    execution.status = PipelineStatus.RUNNING.value
    db.commit()

    # 重新启动流水线
    orchestrator = PipelineOrchestrator(db)
    orchestrator.advance_pipeline(pipeline_id)

    return {
        "code": 0,
        "data": {
            "pipeline_id": pipeline_id,
            "retried_steps": len(failed_steps),
        },
        "message": f"已重试 {len(failed_steps)} 个失败步骤",
    }
