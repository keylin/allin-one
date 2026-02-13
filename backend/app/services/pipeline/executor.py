"""Pipeline 执行器 — 执行单个步骤并推进流水线

流水线的每个步骤都基于一条已存在的 ContentItem 工作。
context 中 content_id 总是存在的。
"""

import json
import logging
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.pipeline import (
    PipelineExecution, PipelineStep,
    PipelineStatus, StepStatus,
)

logger = logging.getLogger(__name__)


class PipelineExecutor:

    def prepare_step(self, execution_id: str, step_index: int) -> dict:
        """标记步骤为运行中并返回执行上下文（单事务）

        返回:
        - content_id: 被处理的内容 (必有)
        - source_id: 来源
        - step_type / step_config: 当前步骤信息
        - previous_steps: 之前步骤的 output_data
        """
        with SessionLocal() as db:
            execution = db.get(PipelineExecution, execution_id)
            if not execution:
                raise ValueError(f"Execution not found: {execution_id}")

            current_step = None
            previous_outputs = {}
            for step in execution.steps:
                if step.step_index == step_index:
                    current_step = step
                elif step.step_index < step_index and step.output_data:
                    previous_outputs[step.step_type] = json.loads(step.output_data)

            if not current_step:
                raise ValueError(f"Step not found: execution={execution_id}, index={step_index}")

            # 标记运行中
            current_step.status = StepStatus.RUNNING.value
            current_step.started_at = datetime.now(timezone.utc)

            step_config = {}
            if current_step.step_config:
                step_config = json.loads(current_step.step_config)

            # 读取 content 的 url 供步骤使用
            from app.models.content import ContentItem
            content = db.get(ContentItem, execution.content_id)

            db.commit()

            return {
                "execution_id": execution_id,
                "content_id": execution.content_id,
                "source_id": execution.source_id,
                "template_name": execution.template_name,
                "content_url": content.url if content else None,
                "content_title": content.title if content else None,
                "step_type": current_step.step_type,
                "step_config": step_config,
                "previous_steps": previous_outputs,
            }

    def finish_step(
        self,
        execution_id: str,
        step_index: int,
        output_data: dict = None,
        error: str = None,
    ) -> None:
        """完成或失败步骤，并推进流水线（单事务）"""
        with SessionLocal() as db:
            step = db.query(PipelineStep).filter(
                PipelineStep.pipeline_id == execution_id,
                PipelineStep.step_index == step_index,
            ).first()
            if not step:
                return

            now = datetime.now(timezone.utc)
            step.completed_at = now

            if error:
                # ---- 失败处理 ----
                step.error_message = error
                if step.is_critical:
                    step.status = StepStatus.FAILED.value
                    execution = db.get(PipelineExecution, execution_id)
                    if execution:
                        execution.status = PipelineStatus.FAILED.value
                        execution.error_message = f"关键步骤 '{step.step_type}' 失败: {error}"
                        execution.completed_at = now
                    logger.error(f"Pipeline {execution_id} 在关键步骤 {step.step_type} 失败")
                    db.commit()
                    return  # 关键步骤失败，不推进
                else:
                    step.status = StepStatus.SKIPPED.value
                    logger.warning(f"非关键步骤 {step.step_type} 失败, 跳过继续")
            else:
                # ---- 成功处理 ----
                step.status = StepStatus.COMPLETED.value
                if output_data:
                    step.output_data = json.dumps(output_data, ensure_ascii=False)

            # ---- 推进流水线 ----
            execution = db.get(PipelineExecution, execution_id)
            if not execution or execution.status == PipelineStatus.FAILED.value:
                db.commit()
                return

            next_index = execution.current_step + 1

            if next_index >= execution.total_steps:
                execution.status = PipelineStatus.COMPLETED.value
                execution.current_step = execution.total_steps
                execution.completed_at = now

                # 更新内容状态为已分析
                from app.models.content import ContentItem, ContentStatus
                content = db.get(ContentItem, execution.content_id)
                if content:
                    content.status = ContentStatus.ANALYZED.value

                db.commit()
                logger.info(f"Pipeline {execution_id} ({execution.template_name}) 完成")
                return

            execution.current_step = next_index
            db.commit()

            logger.info(f"Pipeline {execution_id} advancing to step {next_index}")
            from app.tasks.pipeline_tasks import execute_pipeline_step
            execute_pipeline_step(execution_id, next_index)
