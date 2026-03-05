---
name: g-ship
description: 发布上线 — 自动分析变更 → 选择部署策略 → 部署 → 验证
argument-hint: [可选: build|quick|sync-db|sync-media|sync-all] (默认自动判断)
model: sonnet
---

# 发布上线 (Ship Gate)

执行部署上线流程。用户指定模式: **$ARGUMENTS**（默认自动判断）。

## 工作流

### 阶段 1: 变更分析

#### 1. Git 状态检查
- 运行 `git status` 检查工作区是否干净
- **有未 commit 的变更 → 拒绝部署**，提示先提交或用 `/g-accept` 验收

#### 2. 变更内容分析
- 运行 `git diff <上一个版本tag>...HEAD --name-only` 获取自上次部署以来的所有变更文件
- 如果没有版本 tag，则与远程 `origin/main` 对比
- 分类变更文件:

| 分类 | 文件匹配规则 | 含义 |
|------|-------------|------|
| 基础设施变更 | `Dockerfile`, `docker-compose*.yml`, `requirements.txt`, `package.json`, `package-lock.json` | 需要 build 模式 |
| 后端代码变更 | `backend/**/*.py` (排除 alembic) | quick 模式可处理（已 bind mount） |
| 前端代码变更 | `frontend/src/**` | quick 模式需本地编译 |
| 数据库迁移 | `backend/alembic/versions/*.py` 新增文件 | 部署脚本已自动执行 migration，但需提醒用户 |
| 配置/文档 | `.claude/**`, `docs/**`, `scripts/**`, `*.md` | 不影响部署 |

#### 3. 自动决策部署模式

根据分析结果自动选择:

**build 模式**（需要重建镜像）:
- `Dockerfile` 有变更
- `docker-compose.remote.yml` 有变更
- `requirements.txt` 有变更（Python 依赖变化）
- `package.json` 有变更（前端依赖变化）

**quick 模式**（快速部署，默认）:
- 只有 `backend/app/**` 和/或 `frontend/src/**` 变更
- 配置/文档/脚本变更

**无需部署**:
- 只有 `.claude/**`、`docs/**`、`*.md` 等非运行时文件变更

如果用户显式指定了模式（$ARGUMENTS），以用户指定为准。

#### 4. 数据同步判断

数据同步（`sync-db`/`sync-media`/`sync-all`）是独立操作，不属于常规代码部署。仅在以下情况触发:
- 用户显式指定 `sync-db`、`sync-media` 或 `sync-all`
- 不自动触发数据同步——这是从本地覆盖远程的危险操作

### 阶段 2: 确认并执行

#### 1. 展示部署计划

```
## 部署计划

### 变更分析
- 自上次部署 (v{tag}) 以来共 {N} 个 commit
- 后端变更: {列出关键文件}
- 前端变更: {列出关键文件}
- 基础设施变更: {有/无}
- 数据库迁移: {有/无，列出新增 migration}

### 部署策略
- 模式: build / quick（原因: {为什么选这个模式}）
- 数据同步: 无 / {类型}
```

#### 2. 用户确认
- 使用 AskUserQuestion 确认是否执行
- 如果自动判断的模式有不确定性（如边界情况），在确认时说明并让用户选择

#### 3. 执行部署
- 运行 `./deploy-remote.sh [build|quick]`
- 如果有数据同步，在部署完成后执行 `scripts/migration/sync-data.sh [db|media|all]`

#### 4. 部署验证
- 等待部署脚本完成，展示输出结果
- 确认所有服务正常运行

#### 5. 版本标签
- 部署成功后打版本标签: `git tag v{YYYY-MM-DD}`（如 `v2026-03-05`）
- 如果当天已有标签，追加序号: `v2026-03-05.2`
- push tag 到远程: `git push origin v{tag}`

### 阶段 3: 部署报告

```
## 部署报告

### 变更概要
- 涉及 commit: {数量}
- 部署模式: build / quick
- 版本标签: v{date}

### 部署结果
- 状态: ✅ 成功 / ❌ 失败
- 数据库迁移: ✅ 已执行 / ⚠️ 失败 / — 无需迁移

### 容器状态
{容器运行状态}

### 访问地址
- Web UI: http://{ip}:8000
- API: http://{ip}:8000/api
```
