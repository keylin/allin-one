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
 ├── /g-pack ──────────────── (独立，Fountain 桌面端发布)  │
 │   (sonnet, 打包发布)                                  │
 │                                                      │
 ├── /bug-report ──────┬── product-designer agent ──────┤
 │   (opus, 诊断报告)  └── architect-designer agent ───┤
 │                                                      │
 ├── /design-expert        (独立，无 agent)              │
 ├── /mobile-expert        (独立，无 agent)              │
 ├── /review-design        (独立，无 agent)              │
 │                                                      │
 ├── /new-api                                            │
 ├── /new-collector        4 个脚手架 skill              │
 ├── /new-step-handler     (独立，代码模板引导)          │
 └── /new-vue-page                                      │
```

### 运维/质量 Skill（6 个，与主线联动）

```
/g-develop ──→ /g-accept ──→ /g-ship
    │  │            │            │
    │  │            │            ├── /health-check (部署后验证)
    │  │            │            └── /env-setup (配置变更时)
    │  ├── /db-migrate (schema 变更时)
    │  └── /test-gen (实现完成后)
    │
/bug-report ──→ /worker-debug (结论涉及 Worker 时)

/cleanup ──── 独立定期调用，或由 /health-check 建议触发
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

### 二、支撑工具（4 个，按需调用）

| Skill | 模型 | 定位 |
|-------|------|------|
| `/bug-report` | opus | Bug 诊断报告（诊断+专家评审+结论） |
| `/design-expert` | sonnet | UI/UX 视觉设计（Vue 3 + Tailwind） |
| `/mobile-expert` | sonnet | 移动端技术方案（PWA/跨平台/原生） |
| `/review-design` | sonnet | 代码 vs 设计文档合规审查 |

### 三、运维/质量（6 个，与主线联动）

| Skill | 模型 | 定位 | 联动 |
|-------|------|------|------|
| `/db-migrate` | sonnet | 数据库迁移管理（检测→生成→安全分析→测试） | `/g-develop` 触发，`/g-ship` 识别 |
| `/worker-debug` | sonnet | Worker 任务调试（状态查询→日志→诊断→建议） | `/bug-report` 路由 |
| `/test-gen` | sonnet | 自动测试生成（分析→生成 pytest/Vitest→运行） | `/g-develop` 衔接，`/g-accept` 建议 |
| `/health-check` | sonnet | 系统健康检查（容器→DB→队列→磁盘→错误） | `/g-ship` 部署后验证 |
| `/cleanup` | sonnet | 数据清理（分析→检测孤立→dry-run→执行） | `/health-check` 建议触发 |
| `/env-setup` | sonnet | 环境配置管理（扫描→校验→模板生成） | `/g-develop` `/g-ship` 配置守卫 |

### 四、Fountain 桌面端（1 个）

| Skill | 模型 | 阶段 | 典型场景 |
|-------|------|------|---------|
| `/g-pack` | sonnet | 版本管理 → 构建打包 → DMG → Git 标签 | 发布 Fountain 桌面版 |

### 五、脚手架（4 个，代码生成模板）

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
| `code-tester` | sonnet | /g-develop, /g-accept | 代码质量：静态分析、接口契约、缺陷 |
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
                   │  │
                   │  ├── /db-migrate (如涉及 model 变更)
                   │  └── /test-gen (实现完成后补充测试)
                   │
                   ▼
                /g-accept ──→ 全面验收 + 自动 commit
                      │
                      ▼
                /g-ship ──→ 部署上线 + 版本标签
                   │
                   └── /health-check (部署后验证)
```

### 流程 2: Bug 修复

```
问题现象 ──→ /bug-report ──→ 诊断结论
                                │
                     ┌──────────┼──────────┐
                     ▼          ▼          ▼
              /g-develop    /g-design   /worker-debug
              (简单修复)   (架构调整)   (Worker问题)
                     │          │          │
                     └──────────┼──────────┘
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

### 流程 4: 运维日常

```
定期检查 ──→ /health-check ──→ 健康报告
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              /worker-debug   /cleanup    直接处理
              (Worker异常)   (磁盘不足)   (容器重启)

环境变更 ──→ /env-setup validate ──→ 配置完整性报告
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
| 发布 Fountain 桌面版 | `/g-pack` | `/g-ship`（那是服务端部署） |
| 创建新的采集器/步骤/API/页面 | `/new-*` 系列 | `/g-develop`（缺少模板引导） |
| 修改数据库 schema | `/db-migrate` | 手动跑 alembic（缺安全分析） |
| Worker 任务出问题 | `/worker-debug` | `/bug-report`（后者更通用，前者专治 Worker） |
| 补充测试覆盖 | `/test-gen` | 手写（自动生成更快更规范） |
| 检查系统是否正常 | `/health-check` | 逐个 docker ps + psql（太零散） |
| 清理过期数据 | `/cleanup` | 手动 DELETE（缺 dry-run 保护） |
| 新环境配置 | `/env-setup` | 手动对照代码（容易遗漏） |

## MCP 工具集成

| MCP Server | 用途 | 配置位置 |
|------------|------|---------|
| `dbhub` | PostgreSQL 直连查询 | `.mcp.json` |
| `allin-one` | 项目内容/数据源查询 | 全局 MCP 配置 |

`dbhub` 为 `/worker-debug`、`/health-check`、`/cleanup` 提供数据库直查能力，替代手写 psql 命令。

## 模型分配策略

| 模型 | 用于 | 原则 |
|------|------|------|
| **opus** | /g-spec, /bug-report, architect-designer, product-designer | 需要深度推理、复杂方案设计、根因分析 |
| **sonnet** | 其余所有 skill 和 agent | 编排调度、代码实现、审查测试 |

编排型 skill 统一用 sonnet（重活委托给 opus agent），避免编排层消耗 opus tokens。例外: `/g-spec` 和 `/bug-report` 用 opus，因为需求分析和根因分析需要深度推理。

## 维护原则

1. **代码模板引用不硬编码**：脚手架 skill 中的可变内容改为引导读取源文件
2. **skill 和 agent 不重复内容**：编排型 skill 只做调度+合并，具体工作流写在 agent 里
3. **跨文件代码示例去重**：develop skill 引用 `/new-api` 模板，不自带后端路由示例
4. **agent 职责边界清晰**：product-designer（事前方案）vs product-reviewer（事后验收），design-expert（UI 视觉）vs product-designer（产品方案）
5. **Gate 有判定标准**：每个 Gate 都有 判定 + 自动动作
6. **运维 skill 独立可用**：6 个运维/质量 skill 既可独立调用，也可被主线 skill 引用触发
