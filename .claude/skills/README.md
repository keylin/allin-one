# Agent / Skill 组织架构

## 设计理念

**Skill = 用户入口**（`/slash-command`），**Agent = 可组合的能力单元**。

Skill 面向**场景**设计（"我要做什么"），Agent 面向**能力**设计（"我能做什么"）。Skill 通过 Agent tool 编排一个或多个 Agent 并行协作，最终合并输出。

## 5-Gate 研发主线

```
/g-spec → /g-design → /g-develop → /g-accept → /g-ship
需求定稿    方案定稿    开发实现    统一验收    发布上线
```

每个 Gate 都有: **准入 → 审查 → 判定 → 自动动作**。

## 架构总览

```
用户
 │
 ├── /g-spec ─────────────┬── architect-designer agent ──┐
 │   (opus, 需求定稿)    └── product-designer agent ────┤
 │                                                      │
 ├── /g-design ─────────┬── architect-designer agent ──┤
 │   (sonnet, 方案定稿)  └── product-reviewer agent ───┤
 │                                                      │
 ├── /g-develop ──────────┬── backend-developer agent ───┤
 │   (sonnet, 开发+审查) ├── frontend-developer agent ──┤
 │                       ├── code-reviewer agent ───────┤
 │                       └── code-tester agent ─────────┤
 │                                                      │
 ├── /g-accept ───────────┬── product-reviewer agent ────┤
 │   (sonnet, 统一验收)  ├── code-reviewer agent ───────┤
 │                       ├── code-tester agent ─────────┤
 │                       └── doc-maintainer agent ──────┤
 │                                                      │
 ├── /g-ship ──────────────── (独立，纯运维部署)           │
 │   (sonnet, 发布上线)                                  │
 │                                                      │
 ├── /bug-report ──────┬── product-designer agent ──────┤
 │   (sonnet, 诊断报告) └── architect-designer agent ───┤
 │                                                      │
 ├── /design-expert        (独立，无 agent)              │
 ├── /mobile-expert        (独立，无 agent)              │
 ├── /review-design        (独立，无 agent)              │
 ├── /glossary             (独立，haiku)                 │
 │                                                      │
 ├── /new-api                                            │
 ├── /new-collector        4 个脚手架 skill              │
 ├── /new-step-handler     (独立，代码模板引导)          │
 └── /new-vue-page                                      │
```

## Skill 分类

### 一、工作流 Gate（5 个，研发主线）

| Skill | 模型 | 阶段 | 典型场景 |
|-------|------|------|---------|
| `/g-spec` | opus | 需求挑战（发散）→ 用户讨论 → 方案收敛 → 写入 PRD | 新功能需求定稿 |
| `/g-design` | sonnet | 架构设计 → 产品挑战 → 判定写入设计文档 | 技术方案定稿 |
| `/g-develop` | sonnet | 编码(A/B模式) → 自动审查 → 自动修复 | 功能开发实现 |
| `/g-accept` | sonnet | 并行审查+功能测试 → 文档同步 → 自动 commit | 上线前全面验收 |
| `/g-ship` | sonnet | 预检 → 判定 → 部署+打标签 | 发布上线 |

### 二、支撑工具（5 个，按需调用）

| Skill | 模型 | 定位 |
|-------|------|------|
| `/bug-report` | sonnet | Bug 诊断报告（诊断+专家评审+结论） |
| `/glossary` | haiku | 业务术语和枚举值查询 |
| `/design-expert` | sonnet | UI/UX 视觉设计（Vue 3 + Tailwind） |
| `/mobile-expert` | sonnet | 移动端技术方案（PWA/跨平台/原生） |
| `/review-design` | sonnet | 代码 vs 设计文档合规审查 |

### 三、脚手架（4 个，代码生成模板）

| Skill | 用途 | 产出 |
|-------|------|------|
| `/new-api` | 新 API 端点 | Schema + Route + 注册 |
| `/new-collector` | 新数据采集器 | Collector 类 + 注册 + 采集记录 |
| `/new-step-handler` | 新流水线步骤 | StepType + 定义 + Handler + 注册 |
| `/new-vue-page` | 新 Vue 页面 | 页面组件 + API 对接 + 路由 |

## Agent 清单

8 个 agent，全部保留，按职能域分组：

### 产品域

| Agent | 模型 | 被谁调用 | 职责 |
|-------|------|---------|------|
| `product-designer` | opus | /g-spec, /bug-report | 事前方案设计（需求→功能规格→实施路线） |
| `product-reviewer` | sonnet | /g-accept, /g-design | 事后产品验收/方案挑战（用户视角审查） |

> `product-designer` 做产品方案设计，`/design-expert` 做 UI 视觉设计，两者互补不重叠。

### 架构域

| Agent | 模型 | 被谁调用 | 职责 |
|-------|------|---------|------|
| `architect-designer` | opus | /g-spec, /g-design, /bug-report | 技术方案、数据建模、API 设计、架构评审 |

### 开发域

| Agent | 模型 | 被谁调用 | 职责边界 |
|-------|------|---------|---------|
| `backend-developer` | sonnet | /g-develop | `backend/` + `fountain/src-tauri/`，不碰前端 |
| `frontend-developer` | sonnet | /g-develop | `frontend/src/` + `fountain/src/`，不碰后端 |

### 质量域

| Agent | 模型 | 被谁调用 | 职责 |
|-------|------|---------|------|
| `code-reviewer` | sonnet | /g-develop, /g-accept | 代码风格：命名、日志、一致性 |
| `code-tester` | sonnet | /g-develop, /g-accept, /g-ship | 代码质量：静态分析、接口契约、缺陷 |
| `doc-maintainer` | sonnet | /g-accept | 文档同步：评估变更影响→确认后更新 |

## 典型工作流

### 流程 1: 新功能全生命周期

```
需求 ──→ /g-spec ──→ PRD 定稿
                      │
                      ▼
                /g-design ──→ 设计文档定稿
                      │
                      ▼
                /g-develop ──→ 代码实现（含自动审查+修复）
                      │
                      ▼
                /g-accept ──→ 全面验收 + 自动 commit
                      │
                      ▼
                /g-ship ──→ 部署上线 + 版本标签
```

### 流程 2: Bug 修复

```
问题现象 ──→ /bug-report ──→ 诊断结论
                                │
                                ▼
                          /g-develop 或 /g-design ──→ 修复实现
                                │
                                ▼
                          /g-accept ──→ 验收 + commit
                                │
                                ▼
                          /g-ship ──→ 上线
```

### 流程 3: 新模块脚手架

```
新采集器 ──→ /new-collector ──┐
新步骤   ──→ /new-step-handler ├──→ /g-develop (填充业务逻辑)
新 API   ──→ /new-api ────────┤
新页面   ──→ /new-vue-page ───┘
```

## Skill 选择指南

| 我想... | 用 | 而不是 |
|---------|------|--------|
| 分析一个新需求，产出完整方案 | `/g-spec` | `/g-design`（只做技术面） |
| 做技术方案设计或架构评审 | `/g-design` | `/review-design`（是审查代码合规的） |
| 开发一个功能（写代码） | `/g-develop` | `/g-design`（不写代码） |
| 上线前全面验收 | `/g-accept` | `/g-develop`（审查是开发内置的快速检查） |
| 部署上线 | `/g-ship` | 手动跑 deploy 脚本 |
| 线上出 bug 了要修 | `/bug-report` | `/g-develop`（没有诊断流程） |
| 检查代码是否符合设计文档 | `/review-design` | `/g-develop`（看实现，不对照文档） |
| 设计好看的 UI | `/design-expert` | `/mobile-expert`（侧重技术方案） |
| 评估移动端技术方案 | `/mobile-expert` | `/design-expert`（侧重视觉设计） |
| 查项目术语/枚举值 | `/glossary` | 直接搜代码（glossary 更快更准） |
| 创建新的采集器/步骤/API/页面 | `/new-*` 系列 | `/g-develop`（缺少模板引导） |

## 模型分配策略

| 模型 | 用于 | 原则 |
|------|------|------|
| **opus** | /g-spec, /bug-report, architect-designer, product-designer | 需要深度推理、复杂方案设计、根因分析 |
| **sonnet** | 其余所有 skill 和 agent | 编排调度、代码实现、审查测试 |
| **haiku** | /glossary | 简单查询，成本最低 |

编排型 skill 统一用 sonnet（重活委托给 opus agent），避免编排层消耗 opus tokens。唯一例外: `/g-spec` 用 opus，因为需求分析本身需要深度推理。

## 维护原则

1. **代码模板引用不硬编码**：脚手架 skill 中的可变内容改为引导读取源文件
2. **skill 和 agent 不重复内容**：编排型 skill 只做调度+合并，具体工作流写在 agent 里
3. **跨文件代码示例去重**：develop skill 引用 `/new-api` 模板，不自带后端路由示例
4. **agent 职责边界清晰**：product-designer（事前方案）vs product-reviewer（事后验收），design-expert（UI 视觉）vs product-designer（产品方案）
5. **Gate 有判定标准**：每个 Gate 都有 ✅/⚠️/❌ 三级判定 + 自动动作
