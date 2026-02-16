"""Pipeline 编排器

流程:
  定时器 → CollectionService.collect(source) → N 条新 ContentItem
    → 对每条调用 Orchestrator.trigger_for_content(content) → 创建 PipelineExecution

流水线不自动预处理:
  - 采集完成后不做预处理，直接保存 ContentItem，状态为 pending
  - 有模板才创建流水线，无模板时直接标记 READY
  - processed_content 填充改为 extract_content 步骤，由用户在模板中显式添加
"""

import json
import logging

from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, ContentStatus
from app.models.pipeline import (
    PipelineTemplate, PipelineExecution, PipelineStep,
    PipelineStatus, TriggerSource,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:

    def __init__(self, db: Session):
        self.db = db

    # ---- 模板解析 ----

    def get_template_for_source(self, source: SourceConfig) -> PipelineTemplate | None:
        """获取数据源绑定的流水线模板, 未绑定返回 None"""
        if not source.pipeline_template_id:
            return None
        template = self.db.query(PipelineTemplate).get(source.pipeline_template_id)
        if template and template.is_active:
            return template
        return None

    # ---- 触发 ----

    def trigger_for_content(
        self,
        content: ContentItem,
        template_override_id: str = None,
        trigger: TriggerSource = TriggerSource.SCHEDULED,
    ) -> PipelineExecution | None:
        """为一条已存在的 ContentItem 创建并启动流水线

        有模板才创建流水线，无模板直接标记 READY。
        步骤完全来自模板（包含 extract_content、localize_media 等），不再自动注入。

        Args:
            content: 已经由 Collector 创建的内容项
            template_override_id: 显式指定模板 (手动触发时使用, 覆盖源绑定)
            trigger: 触发来源
        """
        # 1. 确定模板
        template = None
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
            # 无模板 → 标记 READY，不创建流水线
            if content.status == ContentStatus.PENDING.value:
                content.status = ContentStatus.READY.value
                self.db.flush()
            return None

        # 2. 直接使用模板步骤
        all_steps = json.loads(template.steps_config) or []
        if not all_steps:
            content.status = ContentStatus.READY.value
            self.db.flush()
            return None

        # 3. 创建执行记录
        execution = PipelineExecution(
            content_id=content.id,
            source_id=content.source_id,
            template_id=template.id,
            template_name=template.name,
            status=PipelineStatus.PENDING.value,
            total_steps=len(all_steps),
            trigger_source=trigger.value,
        )
        self.db.add(execution)
        self.db.flush()

        # 4. 创建步骤实例
        for index, step_def in enumerate(all_steps):
            step = PipelineStep(
                pipeline_id=execution.id,
                step_index=index,
                step_type=step_def["step_type"],
                step_config=json.dumps(step_def.get("config", {}), ensure_ascii=False),
                is_critical=step_def.get("is_critical", False),
            )
            self.db.add(step)

        self.db.commit()
        logger.info(
            f"Pipeline created: {execution.id} "
            f"(template={template.name}, steps={len(all_steps)}, "
            f"content={content.id})"
        )
        return execution

    def start_execution(self, execution_id: str) -> None:
        """入队第一个步骤 (同步版本, 仅供 executor.py 同步 worker 线程使用)"""
        execution = self.db.get(PipelineExecution, execution_id)
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")

        self.db.commit()

        logger.info(f"Pipeline queued: {execution_id}")
        from app.tasks.pipeline_tasks import execute_pipeline_step
        from app.tasks.procrastinate_app import sync_defer
        sync_defer(execute_pipeline_step, execution_id=execution_id, step_index=0)

    async def async_start_execution(self, execution_id: str) -> None:
        """入队第一个步骤 (异步版本, 供 FastAPI handlers 和 periodic tasks 使用)"""
        execution = self.db.get(PipelineExecution, execution_id)
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")

        self.db.commit()

        logger.info(f"Pipeline queued: {execution_id}")
        from app.tasks.pipeline_tasks import execute_pipeline_step
        from app.tasks.procrastinate_app import async_defer
        await async_defer(execute_pipeline_step, execution_id=execution_id, step_index=0)


def seed_builtin_templates(db: Session) -> None:
    """将内置模板写入数据库 (首次启动时调用), 并更新已有内置模板的步骤配置"""
    from app.services.pipeline.registry import BUILTIN_TEMPLATES

    created = 0
    updated = 0
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
            created += 1
        elif existing.is_builtin and existing.steps_config != tmpl_data["steps_config"]:
            existing.steps_config = tmpl_data["steps_config"]
            existing.description = tmpl_data.get("description", existing.description)
            updated += 1

    db.commit()
    if created or updated:
        logger.info(f"Seeded {created} new, updated {updated} builtin pipeline templates")

    # Seed builtin prompt templates
    from app.models.prompt_template import PromptTemplate

    BUILTIN_PROMPTS = [
        {
            "name": "金融数据分析",
            "template_type": "news_analysis",
            "system_prompt": (
                "你是一位专业的金融数据分析师。分析用户提供的金融数据，给出简洁的趋势判断和解读。\n"
                "要求:\n"
                "1. 识别数据的变化趋势（上升/下降/震荡）\n"
                "2. 对比历史水平，判断当前值是否异常\n"
                "3. 给出简要的市场解读或可能的影响\n"
                "4. 使用中文回答，语言简练专业"
            ),
            "user_prompt": "请分析以下金融数据:\n\n{content}",
            "output_format": "json",
        },
    ]

    prompt_created = 0
    for pt_data in BUILTIN_PROMPTS:
        existing = (
            db.query(PromptTemplate)
            .filter(PromptTemplate.name == pt_data["name"])
            .first()
        )
        if not existing:
            pt = PromptTemplate(
                name=pt_data["name"],
                template_type=pt_data.get("template_type", "custom"),
                system_prompt=pt_data.get("system_prompt", ""),
                user_prompt=pt_data["user_prompt"],
                output_format=pt_data.get("output_format", "json"),
                is_default=False,
            )
            db.add(pt)
            prompt_created += 1

    if prompt_created:
        db.commit()
        logger.info(f"Seeded {prompt_created} builtin prompt templates")
