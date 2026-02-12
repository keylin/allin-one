---
name: glossary
description: 查询业务术语、枚举值、流水线模板、数据源组合等项目概念
argument-hint: <术语> (如 SourceType, StepType, ContentStatus, 流水线模板)
model: haiku
allowed-tools: Read, Grep, Glob
---

# 术语查询

查询以下内容相关的信息: $ARGUMENTS

## 数据来源（以这些文件为准，不要凭记忆回答）

1. `docs/business_glossary.md` — 完整术语表、组合示例
2. `backend/app/models/content.py` — SourceType, MediaType, ContentStatus 枚举
3. `backend/app/models/pipeline.py` — StepType, PipelineStatus, StepStatus, TriggerSource 枚举
4. `backend/app/models/prompt_template.py` — TemplateType 枚举
5. `backend/app/services/pipeline/registry.py` — STEP_DEFINITIONS 和 BUILTIN_TEMPLATES

## 关键设计规则

- 没有 `fetch_content` 步骤 — 抓取由 Collector 完成，不是流水线步骤
- 没有 `video_bilibili` / `video_youtube` 数据源 — 视频通过 rsshub + download_video 步骤
- 数据源和流水线通过 FK 解耦，没有硬编码映射

## 执行指令

先读取上述源文件，再搜索 "$ARGUMENTS"，展示:
- 枚举值及其说明
- 相关概念及关联关系
- 定义该术语的代码文件路径
- 使用示例
