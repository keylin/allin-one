"""Pipeline 异步任务

每个步骤处理函数接收 context, 其中:
- content_id: 必有, 被处理的 ContentItem
- content_url: 内容原始链接
- step_config: 该步骤的操作配置
- previous_steps: 之前步骤的输出

注意: 没有 fetch_content 处理函数。
数据抓取由 CollectionService + 定时器完成, 不是流水线步骤。
"""

import logging

import procrastinate

from app.tasks.procrastinate_app import proc_app
import app.models  # noqa: F401 — 确保所有 ORM 模型注册，避免 relationship 解析失败
from app.services.pipeline.executor import PipelineExecutor

# 向后兼容再导出 — 外部模块可继续使用 from app.tasks.pipeline_tasks import STEP_HANDLERS
from app.services.pipeline.steps import STEP_HANDLERS  # noqa: F401

logger = logging.getLogger(__name__)
executor = PipelineExecutor()


@proc_app.task(
    retry=procrastinate.RetryStrategy(max_attempts=4, wait=30),
    queue="pipeline",
)
def execute_pipeline_step(execution_id: str, step_index: int):
    """通用步骤执行入口 — 内联循环执行所有后续步骤

    一条流水线在同一个 worker slot 内跑完所有步骤，
    避免每步之间经过 PG 队列往返带来的 1-5 秒延迟。
    每步仍更新 DB 状态，保留进度可见性和错误追踪。
    """
    current_index = step_index

    while current_index is not None:
        try:
            context = executor.prepare_step(execution_id, current_index)
        except ValueError as e:
            logger.error(str(e))
            return

        step_type = context["step_type"]
        logger.info(f"Step [{current_index}] {step_type} starting (pipeline={execution_id})")

        try:
            handler = STEP_HANDLERS.get(step_type)
            if not handler:
                raise ValueError(f"Unknown step_type: {step_type}")

            result = handler(context)

            next_index = executor.finish_step(execution_id, current_index, output_data=result)
            logger.info(f"Step [{current_index}] {step_type} completed (pipeline={execution_id})")
            current_index = next_index

        except Exception as e:
            logger.exception(f"Step [{current_index}] {step_type} failed (pipeline={execution_id}): {e}")
            next_index = executor.finish_step(execution_id, current_index, error=str(e))
            current_index = next_index
