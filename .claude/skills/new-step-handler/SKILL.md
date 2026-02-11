---
name: new-step-handler
description: 引导创建新的流水线步骤处理器（原子操作）
argument-hint: <步骤类型> (如 summarize_content, extract_keywords)
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# 创建新的流水线步骤处理器

你正在创建新的步骤处理器: **$ARGUMENTS**

## 开始之前

阅读现有模式:
1. `backend/app/tasks/pipeline_tasks.py` — 已有的 7 个处理器 + STEP_HANDLERS 字典
2. `backend/app/services/pipeline/registry.py` — STEP_DEFINITIONS + StepDefinition 数据类
3. `backend/app/services/pipeline/executor.py` — context 如何构建、步骤如何推进
4. `backend/app/models/pipeline.py` — StepType 枚举、PipelineStep 模型

## 架构规则（必须遵守）

- 步骤处理器只处理已存在的 ContentItem，绝不从外部抓取新内容。
- 处理器接收一个 `context` 字典，包含 content_id、step_config、previous_steps 输出。
- 处理器返回一个字典，成为 `step.output_data`（供下游步骤使用）。
- 如果需要更新 ContentItem 字段（processed_content、analysis_result），必须打开独立的 DB session。
- 处理器是**同步**函数，由 Huey worker 线程调用（不是 async）。

## 第 1 步: 添加到 StepType 枚举

在 `backend/app/models/pipeline.py` 中添加:
```python
class StepType(str, Enum):
    # ... 已有的值 ...
    $ARGUMENTS = "$ARGUMENTS"
```

## 第 2 步: 注册步骤定义

在 `backend/app/services/pipeline/registry.py` 的 STEP_DEFINITIONS 中添加:
```python
"$ARGUMENTS": StepDefinition(
    step_type="$ARGUMENTS",
    display_name="<中文显示名>",
    description="<这个步骤做什么>",
    is_critical_default=False,
    max_retries=3,
    retry_delay=30,
    config_schema={
        "type": "object",
        "properties": {
            # 在这里定义可配置参数
            # 例如: "model": {"type": "string", "default": "deepseek-chat"}
        },
    },
),
```

## 第 3 步: 实现处理器函数

在 `backend/app/tasks/pipeline_tasks.py` 中添加:

```python
def _handle_$ARGUMENTS(context: dict) -> dict:
    """<描述这个步骤做什么>

    Args:
        context: 步骤执行上下文，包含 content_id、step_config、previous_steps。

    Returns:
        包含步骤输出数据的字典，供下游步骤使用。
    """
    config = context["step_config"]
    content_id = context["content_id"]
    previous = context["previous_steps"]

    # 如需读取上游步骤的输出:
    # enriched_text = previous.get("enrich_content", {}).get("full_text", "")
    # translated_text = previous.get("translate_content", {}).get("translated_text", "")

    # 如需更新 ContentItem 字段，打开独立的 DB session:
    # from app.core.database import SessionLocal
    # from app.models.content import ContentItem
    # with SessionLocal() as db:
    #     content = db.query(ContentItem).get(content_id)
    #     content.processed_content = result_text  # 或 analysis_result
    #     db.commit()

    # 返回输出供下游步骤使用:
    return {"status": "completed", "key": "value"}
```

## 第 4 步: 注册到 STEP_HANDLERS

在 `backend/app/tasks/pipeline_tasks.py` 底部的字典中添加:
```python
STEP_HANDLERS = {
    # ... 已有的处理器 ...
    "$ARGUMENTS": _handle_$ARGUMENTS,
}
```

## 第 5 步: 创建或更新流水线模板（可选）

如果这个步骤需要加入内置模板，更新 `registry.py` 中的 BUILTIN_TEMPLATES。
如果修改了已有模板，还需要创建 Alembic 迁移来更新数据库。

## Context 对象参考

```python
context = {
    "execution_id": "abc123",
    "content_id": "def456",         # 始终存在
    "source_id": "ghi789",
    "template_name": "文章分析",
    "content_url": "https://...",
    "content_title": "文章标题",
    "step_type": "$ARGUMENTS",
    "step_config": {"key": "value"},  # 来自模板定义
    "previous_steps": {
        "enrich_content": {"full_text": "...", "word_count": 1200},
        "translate_content": {"translated_text": "..."},
    }
}
```

## 关键步骤 vs 非关键步骤

- 设置 `is_critical_default=True`: 该步骤失败则整条流水线停止
- 设置 `is_critical_default=False`: 该步骤失败则标记为 skipped，流水线继续
- 惯例: 模板中第一个处理步骤设为关键，后续步骤设为非关键

## 自查清单

- [ ] `models/pipeline.py` 中的 StepType 枚举已更新
- [ ] `registry.py` 的 STEP_DEFINITIONS 中已注册 StepDefinition
- [ ] `pipeline_tasks.py` 中已实现处理器函数
- [ ] 处理器已注册到 STEP_HANDLERS 字典
- [ ] 处理器返回字典（不是 None）
- [ ] 处理器是同步函数（不是 async）
- [ ] 所有 DB 更新使用独立的 `SessionLocal()` 上下文管理器
- [ ] 如果 StepType 枚举变更影响数据库，已创建 Alembic 迁移
