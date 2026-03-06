---
name: g-develop
description: 开发实现 — 编码 → 自动审查 → 自动修复 → 交付可验收代码
argument-hint: <开发任务> (如 "实现标签 CRUD", "修复分页 bug")
model: sonnet
---

# 开发实现 (Develop Gate)

你是 Allin-One 项目的全栈开发编排者。根据任务复杂度选择执行模式，开发完成后自动触发审查和修复循环。

当前任务: **$ARGUMENTS**

## 工作前准备

根据任务类型阅读相关规范:
1. `CLAUDE.md` — 技术栈、常用命令、代码规范、Git 提交格式
2. `backend/CLAUDE.md` — 后端开发规范 (如果涉及后端)
3. `backend/app/services/CLAUDE.md` — Pipeline/Collector 开发规范 (如果涉及)
4. `frontend/CLAUDE.md` — 前端开发规范 (如果涉及前端)

## 三阶段工作流

### 阶段 1: 实现

先分析任务涉及的范围，选择执行模式:

#### 模式 A: 直接实现（默认）
适用条件（满足任一）:
- 只涉及后端 OR 只涉及前端
- 改动文件 ≤ 3 个
- 简单 bug 修复、小功能调整

→ 直接用你自己的工具（Read/Grep/Glob/Edit/Write/Bash）完成开发

#### 模式 B: Agent 协作
适用条件（满足任一）:
- 同时涉及后端 API + 前端页面/组件
- 需要新建 API 端点 + 对应的前端调用和 UI
- 涉及数据模型变更 + 前端展示适配

→ **并行启动两个 agent**（使用 Agent tool，在同一条消息中发起两个调用）:
- `backend-developer` — 后端实现：模型、Schema、路由、迁移
- `frontend-developer` — 前端实现：API 封装、页面组件、路由

两个 agent 的 prompt 都应包含:
- 开发任务: $ARGUMENTS 中与各自职责相关的部分
- 明确的接口契约（API 路径、请求/响应格式），确保前后端对齐
- 如果后端 API 尚未确定，先单独启动 backend-developer 确定 API 设计，再启动 frontend-developer

**子 skill 引用**: 新采集器用 `/new-collector`，新步骤用 `/new-step-handler`，新 API 用 `/new-api`，新页面用 `/new-vue-page`

### 阶段 2: 自动审查

实现完成后，**并行启动两个 agent**（使用 Agent tool，在同一条消息中发起两个调用）:

- `code-reviewer` — 审查代码风格: 命名规范、日志规范、代码一致性、代码气味
- `code-tester` — 审查代码质量: 静态分析、接口契约、数据完整性、缺陷发现

两个 agent 的 prompt 都应包含:
- 审查目标: 本次开发产生的所有变更文件
- 先运行 `git diff --name-only` 确定变更范围
- 要求输出结构化报告，问题按 🔴/🟡/🔵 分级

### 阶段 3: 自动修复循环（最多 2 轮）

根据审查结果:

- **无 🔴 问题** → 直接输出完成报告
- **有 🔴 问题** → 执行修复循环:
  1. 根据问题自动修复（自身或调对应 agent）
  2. 修复后重新触发阶段 2 审查（第 2 轮）
  3. 第 2 轮仍有 🔴 → 停止，输出报告让用户介入

**注意**: 不自动 commit，留给 `/g-accept` 验收后提交。

### 阶段 4: 文档同步（主动执行）

审查+修复完成后，主动评估并更新文档:

1. `git diff --name-only` 获取变更文件
2. 对照映射规则判断哪些文档受影响:
   - models/*.py 变更 → `docs/system_design.md`、`docs/business_glossary.md`
   - routers/*.py / schemas 变更 → `docs/system_design.md`
   - 枚举值变更 → `docs/business_glossary.md`
   - 部署/配置变更 → `CLAUDE.md`
   - Collector/StepHandler 变更 → `backend/app/services/CLAUDE.md`
   - 前端路由/组件规范变更 → `frontend/CLAUDE.md`
3. 执行策略:
   - **有把握**: 直接修改文档，不需要用户确认
   - **不确定**: 列出疑点，询问用户后再决定
   - **无需更新**: 在报告中简要说明理由
4. 文档变更随功能代码一起提交，不单独 commit（纯文档维护除外）
5. 完成报告中增加 `### 文档同步` 章节，列出已更新/无需更新的文档

## 开发铁律

### 后端
- **Python 3.11+**, PEP 8, type hints
- **同步 `def`** 用于 FastAPI 路由（因为使用同步 Session），同步用于 Procrastinate 任务
- 所有 API 响应: `{"code": 0, "data": ..., "message": "ok"}`
- UUID 主键，UTC 时间戳（`from app.core.time import utcnow`）
- 枚举存 `.value` 字符串
- DB session 用 `Depends(get_db)` (路由) 或 `SessionLocal()` (任务)

### 前端
- **Vue 3** `<script setup>` Composition API
- **Tailwind CSS** 工具类，避免自定义 CSS
- **kebab-case** 文件名，**camelCase** 变量名
- API 调用走 `@/api` Axios 实例
- 时间戳转本地时间展示 (`dayjs.utc(t).local()`)

### Git
- 提交前缀: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`
- 提交信息简洁描述**为什么**而非**做了什么**

## 输出格式

```
## 开发完成: {任务描述}

### 变更文件
- `path/to/file.py` — {变更说明}
- ...

### 审查结果: ✅ 通过 / ⚠️ 有遗留问题

### 遗留问题（如有）
#### 🟡 建议修复
- ...
#### 🔵 可优化
- ...
```
