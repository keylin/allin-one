"""Pipeline 编排器

流程:
  定时器 → CollectionService.collect(source) → N 条新 ContentItem
    → 对每条调用 Orchestrator.trigger_for_content(content) → 创建 PipelineExecution

流水线的输入永远是一条已存在的 ContentItem。
"""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem
from app.models.pipeline import (
    PipelineTemplate, PipelineExecution, PipelineStep,
    PipelineStatus, TriggerSource,
)


class PipelineOrchestrator:

    def __init__(self, db: Session):
        self.db = db

    def get_template_for_source(self, source: SourceConfig) -> PipelineTemplate | None:
        """获取数据源绑定的流水线模版, 未绑定返回 None (不处理)"""
        if not source.pipeline_template_id:
            return None
        template = self.db.query(PipelineTemplate).get(source.pipeline_template_id)
        if template and template.is_active:
            return template
        return None

    def trigger_for_content(
        self,
        content: ContentItem,
        template_override_id: str = None,
        trigger: TriggerSource = TriggerSource.SCHEDULED,
    ) -> PipelineExecution | None:
        """为一条已存在的 ContentItem 创建并启动流水线

        Args:
            content: 已经由 Collector 创建的内容项
            template_override_id: 显式指定模版 (手动触发时使用, 覆盖源绑定)
            trigger: 触发来源

        Returns:
            创建的 PipelineExecution, 若源未绑定模版则返回 None
        """
        # 确定模版
        if template_override_id:
            template = self.db.query(PipelineTemplate).get(template_override_id)
            if not template:
                raise ValueError(f"Template not found: {template_override_id}")
        else:
            source = self.db.query(SourceConfig).get(content.source_id)
            if not source:
                raise ValueError(f"Source not found: {content.source_id}")
            template = self.get_template_for_source(source)
            if not template:
                return None  # 源未绑定流水线, 不处理 (纯采集场景)

        steps_config = json.loads(template.steps_config)
        if not steps_config:
            return None

        # 创建执行记录
        execution = PipelineExecution(
            content_id=content.id,
            source_id=content.source_id,
            template_id=template.id,
            template_name=template.name,
            status=PipelineStatus.PENDING.value,
            total_steps=len(steps_config),
            trigger_source=trigger.value,
        )
        self.db.add(execution)
        self.db.flush()

        # 从模版创建步骤实例
        for index, step_def in enumerate(steps_config):
            step = PipelineStep(
                pipeline_id=execution.id,
                step_index=index,
                step_type=step_def["step_type"],
                step_config=json.dumps(step_def.get("config", {}), ensure_ascii=False),
                is_critical=step_def.get("is_critical", False),
            )
            self.db.add(step)

        self.db.commit()
        return execution

    def start_execution(self, execution_id: str) -> None:
        """启动执行 (入队第一个步骤)"""
        execution = self.db.query(PipelineExecution).get(execution_id)
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")

        execution.status = PipelineStatus.RUNNING.value
        execution.started_at = datetime.now(timezone.utc)
        execution.current_step = 0
        self.db.commit()

        from app.tasks.pipeline_tasks import execute_pipeline_step
        execute_pipeline_step(execution_id, 0)


def seed_builtin_templates(db: Session) -> None:
    """将内置模版写入数据库 (首次启动时调用)"""
    from app.services.pipeline.registry import BUILTIN_TEMPLATES

    for tmpl_data in BUILTIN_TEMPLATES:
        existing = (
            db.query(PipelineTemplate)
            .filter(PipelineTemplate.name == tmpl_data["name"])
            .first()
        )
        if not existing:
            template = PipelineTemplate(
                name=tmpl_data["name"],
                description=tmpl_data.get("description", ""),
                steps_config=tmpl_data["steps_config"],
                is_builtin=True,
                is_active=True,
            )
            db.add(template)

    db.commit()
