---
name: review-design
description: 审查代码是否符合项目设计文档和架构规范
argument-hint: [文件或目录] (可选，默认审查最近 git 变更)
model: sonnet
allowed-tools: Read, Grep, Glob, Bash
---

# 设计合规审查

审查 `$ARGUMENTS` 处的代码（如果未提供参数则审查最近的 git 变更），检查是否符合项目设计文档。

## 工作流程

### 1. 加载最新规范（每次必做）

先阅读以下文档，提取当前有效的规范作为审查基准:

| 文档 | 提取内容 |
|------|---------|
| `CLAUDE.md` | 核心架构约束、技术栈、代码规范、关键决策 |
| `backend/CLAUDE.md` | 后端开发规范、时间戳用法、ORM 规则、数据库规范 |
| `backend/app/services/CLAUDE.md` | Pipeline/Collector 架构规则 |
| `frontend/CLAUDE.md` | 前端开发规范、组件约定 |
| `docs/system_design.md` | 架构设计、数据库 schema、API 规范 |
| `docs/business_glossary.md` | 枚举值定义、术语 |

**关键**: 以文档中的当前内容为准，不依赖任何预置的枚举值列表或代码片段。

### 2. 确定审查范围

如果未提供参数，运行 `git diff --name-only` 和 `git diff --cached --name-only` 查找最近变更的文件。

### 3. 逐维度审查

对变更的代码，按以下维度与规范文档对照检查:

#### 维度 A: 架构约束合规
- 数据源与流水线是否正确解耦（对照 CLAUDE.md 架构约束章节）
- SourceType 值是否在 `docs/business_glossary.md` 定义的枚举范围内
- Collector 是否只做抓取，Pipeline 是否只做处理
- 模块间依赖方向是否正确

#### 维度 B: 数据库规范
- 时间戳用法是否符合 `backend/CLAUDE.md` 中的时间戳规范
- 主键类型、枚举存储方式是否符合 ORM 规范
- Schema 变更是否有 Alembic 迁移
- JSONB 查询写法是否正确

#### 维度 C: API 规范
- 响应格式是否符合 `docs/system_design.md` 中的 API 规范
- 分页参数、路由命名、HTTP 方法是否一致
- 路由 handler 是否使用与数据库会话匹配的同步模式（同步 Session 用 `def`，不用 `async def`）
- Pydantic schema 是否校验请求体

#### 维度 D: 流水线引擎
- 步骤处理器返回值、注册方式是否符合 `backend/app/services/CLAUDE.md`
- 关键/非关键步骤的失败处理是否正确
- context 键名是否与引擎约定一致

#### 维度 E: 前端规范
- 组件语法、文件命名是否符合 `frontend/CLAUDE.md`
- 时间戳展示是否正确转换
- API 调用方式是否规范

## 输出格式

对发现的每个问题，报告:
1. **文件和行号**: 问题所在位置
2. **违反的规则**: 引用具体文档和章节（如 "CLAUDE.md > 核心架构约束 > 数据源与流水线解耦"）
3. **期望**: 按文档规范应该是什么样
4. **实际**: 当前代码是什么样
5. **严重程度**: 严重 / 警告 / 建议
