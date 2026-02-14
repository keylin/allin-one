"""Pipeline 编排器

流程:
  定时器 → CollectionService.collect(source) → N 条新 ContentItem
    → 对每条调用 Orchestrator.trigger_for_content(content) → 创建 PipelineExecution

流水线分两阶段:
  1. 预处理 (自动): 基于内容检测自动执行，让内容变得"可分析"
     - 文本量不足 → enrich_content (抓取全文)
     - 始终 → localize_media (媒体检测+下载+URL改写)
  2. 后置处理 (用户模板): analyze / translate / publish 等, 由用户配置
"""

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.content import SourceConfig, ContentItem, ContentStatus
from app.models.pipeline import (
    PipelineTemplate, PipelineExecution, PipelineStep,
    PipelineStatus, TriggerSource,
)

logger = logging.getLogger(__name__)

# 预处理步骤类型 — 由系统自动注入, 从用户模板中去重
PREPROCESSING_STEP_TYPES = {"enrich_content", "localize_media"}

# 全文判定阈值 (纯文本字符数)
_FULL_TEXT_THRESHOLD = 500


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

    # ---- 自动预处理 ----

    @staticmethod
    def _strip_html(html: str) -> str:
        """去除 HTML 标签, 返回纯文本"""
        text = re.sub(r"<[^>]+>", "", html)
        return text.strip()

    @staticmethod
    def _extract_raw_text(raw_data_json: str | None) -> str:
        """从 raw_data JSON 提取最长的文本内容"""
        if not raw_data_json:
            return ""
        try:
            raw = json.loads(raw_data_json)
        except (json.JSONDecodeError, TypeError):
            return ""
        # 优先 content[0].value (RSS <content:encoded>, 通常是全文 HTML)
        contents = raw.get("content", [])
        if isinstance(contents, list) and contents:
            value = contents[0].get("value", "")
            if value:
                return value
        # 回退 summary
        return raw.get("summary", "")

    @classmethod
    def _has_full_text(cls, raw_data_json: str | None) -> bool:
        """判断 raw_data 是否已包含足够正文 (≥500 字纯文本)"""
        text = cls._extract_raw_text(raw_data_json)
        if not text:
            return False
        return len(cls._strip_html(text)) >= _FULL_TEXT_THRESHOLD

    def _compute_preprocessing_steps(self, content: ContentItem) -> list[dict]:
        """基于内容检测计算自动预处理步骤"""
        steps = []

        # 1. 全文检测
        # 如果 processed_content 已有充足文本（如 Miniflux 来源），跳过 enrich
        if content.processed_content and len(self._strip_html(content.processed_content)) >= _FULL_TEXT_THRESHOLD:
            logger.info(f"processed_content already sufficient for content {content.id}, skip enrich")
        elif not self._has_full_text(content.raw_data):
            steps.append({"step_type": "enrich_content", "is_critical": False,
                          "config": {"scrape_level": "auto"}})
        else:
            # 已有全文 → 直接填充 processed_content
            if not content.processed_content:
                content.processed_content = self._extract_raw_text(content.raw_data)
                self.db.flush()
                logger.info(f"Full text populated from raw_data for content {content.id}")

        # 2. 媒体本地化: 始终添加（步骤内部检测是否有媒体需处理）
        #    纯数据源 (api.akshare) 跳过
        source = self.db.query(SourceConfig).get(content.source_id)
        if source and source.source_type != "api.akshare":
            steps.append({"step_type": "localize_media", "is_critical": False, "config": {}})

        return steps

    @staticmethod
    def _build_steps(pre_steps: list[dict], template_steps: list[dict]) -> list[dict]:
        """合并预处理步骤 + 模板步骤 (去重: 模板中的预处理步骤被跳过)"""
        post_steps = [s for s in template_steps if s["step_type"] not in PREPROCESSING_STEP_TYPES]
        return pre_steps + post_steps

    # ---- 触发 ----

    def trigger_for_content(
        self,
        content: ContentItem,
        template_override_id: str = None,
        trigger: TriggerSource = TriggerSource.SCHEDULED,
    ) -> PipelineExecution | None:
        """为一条已存在的 ContentItem 创建并启动流水线

        自动注入预处理步骤 (基于内容检测), 然后拼接用户模板的后置步骤。
        无模板时仍执行预处理; 无预处理也无模板则标记 READY。

        Args:
            content: 已经由 Collector 创建的内容项
            template_override_id: 显式指定模板 (手动触发时使用, 覆盖源绑定)
            trigger: 触发来源
        """
        # 1. 计算预处理步骤
        pre_steps = self._compute_preprocessing_steps(content)

        # 2. 确定用户模板
        template = None
        template_steps = []
        if template_override_id:
            template = self.db.query(PipelineTemplate).get(template_override_id)
            if not template:
                raise ValueError(f"Template not found: {template_override_id}")
        else:
            source = self.db.query(SourceConfig).get(content.source_id)
            if not source:
                raise ValueError(f"Source not found: {content.source_id}")
            template = self.get_template_for_source(source)

        if template:
            template_steps = json.loads(template.steps_config) or []

        # 3. 合并: 预处理 + 后置处理 (去重)
        all_steps = self._build_steps(pre_steps, template_steps)
        if not all_steps:
            # 无预处理也无后置处理 — 标记为终态，避免补偿循环反复扫描
            if content.status == ContentStatus.PENDING.value:
                content.status = ContentStatus.READY.value
                self.db.flush()
            return None

        # 4. 创建执行记录
        execution = PipelineExecution(
            content_id=content.id,
            source_id=content.source_id,
            template_id=template.id if template else None,
            template_name=template.name if template else "自动预处理",
            status=PipelineStatus.PENDING.value,
            total_steps=len(all_steps),
            trigger_source=trigger.value,
        )
        self.db.add(execution)
        self.db.flush()

        # 5. 创建步骤实例
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
            f"(template={template.name if template else 'auto'}, "
            f"pre={len(pre_steps)}, post={len(all_steps) - len(pre_steps)}, "
            f"content={content.id})"
        )
        return execution

    def start_execution(self, execution_id: str) -> None:
        """启动执行 (入队第一个步骤)"""
        execution = self.db.get(PipelineExecution, execution_id)
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")

        execution.status = PipelineStatus.RUNNING.value
        execution.started_at = datetime.now(timezone.utc)
        execution.current_step = 0
        self.db.commit()

        logger.info(f"Pipeline started: {execution_id}")
        from app.tasks.pipeline_tasks import execute_pipeline_step
        execute_pipeline_step(execution_id, 0)


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
