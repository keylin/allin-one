---
name: review-design
description: 审查代码是否符合项目设计文档和架构规范
argument-hint: [文件或目录] (可选，默认审查最近的 git 变更)
model: sonnet
allowed-tools: Read, Grep, Glob, Bash
---

# 设计合规审查

审查 `$ARGUMENTS` 处的代码（如果未提供参数则审查最近的 git 变更），检查是否符合项目设计文档。

## 审查依据

先阅读以下设计文档:
1. `docs/system_design.md` — 架构设计、数据库 schema、API 规范
2. `docs/product_spec.md` — 功能需求、UI 设计
3. `docs/business_glossary.md` — 枚举值、术语、模板定义
4. `CLAUDE.md` — 开发规范

如果未提供参数，运行 `git diff --name-only` 和 `git diff --cached --name-only` 查找最近变更的文件。

## 检查清单

### 1. 数据源-流水线解耦（最关键）
- [ ] 不存在 `video_bilibili`、`video_youtube` 等混合数据源类型
- [ ] SourceType 枚举仅包含: rsshub, rss_std, akshare, scraper, file_upload, account_bilibili, account_other, user_note, user_message
- [ ] 流水线中不存在 `fetch_content` 步骤类型
- [ ] steps_config 中不包含任何抓取/采集步骤
- [ ] Collector 没有直接调用流水线代码
- [ ] 数据源仅通过 `pipeline_template_id` 外键关联流水线

### 2. 数据库规范
- [ ] 所有主键为 UUID 字符串（非自增）
- [ ] 所有时间戳使用 UTC（`datetime.now(timezone.utc)`）
- [ ] 没有 naive datetime 对象
- [ ] 枚举字段存储 `.value` 字符串，而非枚举对象本身
- [ ] Schema 变更有对应的 Alembic 迁移

### 3. API 规范
- [ ] 所有响应使用 `{"code": 0, "data": ..., "message": "ok"}` 格式
- [ ] 分页使用 `page` 和 `page_size` 参数
- [ ] 路由路径使用复数名词
- [ ] 路由 handler 使用 `async def`
- [ ] 请求体使用 Pydantic schema 校验

### 4. 流水线引擎
- [ ] 步骤处理器返回 dict（非 None）
- [ ] 步骤处理器已注册到 STEP_HANDLERS 字典
- [ ] 关键步骤失败则流水线停止；非关键步骤失败则跳过
- [ ] PipelineExecution 始终设置了 `content_id`
- [ ] 步骤上下文使用正确的键名（step_config, previous_steps 等）

### 5. 前端规范
- [ ] Vue 组件使用 `<script setup>`
- [ ] 时间戳已转换为本地时间展示
- [ ] API 调用使用 `@/api` Axios 实例
- [ ] 使用 TailwindCSS 样式，尽量不写自定义 CSS
- [ ] 文件使用 kebab-case 命名

## 输出格式

对发现的每个问题，报告:
1. **文件和行号**: 问题所在位置
2. **违反的规则**: 对应检查清单中的哪条规则
3. **期望**: 按设计文档应该是什么样
4. **实际**: 当前代码是什么样
5. **严重程度**: 严重 / 警告 / 建议
