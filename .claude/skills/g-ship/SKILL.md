---
name: g-ship
description: 发布上线 — 部署检查 → 构建验证 → 自动部署
argument-hint: [build|quick] (默认 quick 快速部署，build 全量构建)
model: sonnet
---

# 发布上线 (Ship Gate)

执行部署上线流程。部署模式: **$ARGUMENTS**（默认 quick）。

## 三阶段工作流

### 阶段 1: 预检

#### 1. Git 状态检查
- 运行 `git status` 检查工作区是否干净
- **有未 commit 的变更 → 拒绝部署**，提示先用 `/g-accept` 验收提交

#### 2. 验收检查
- 运行 `git log -1 --format=%B` 查看最近 commit message
- **commit message 不含"验收通过" → 警告**，提示应先通过 `/g-accept` 验收

#### 3. 部署配置检查
- 启动 `code-tester` agent，要求检查:
  - `Dockerfile` 语法和构建逻辑
  - `docker-compose.remote.yml` 配置完整性
  - 环境变量是否齐全（对比 `.env.example` 或文档）
  - 端口映射、卷挂载是否正确

### 阶段 2: 判定

根据预检结果做出判定:

- **✅ 可部署**: 工作区干净 + 已验收 + 配置无问题
- **❌ 不可部署**: 输出所有阻塞原因，停止流程

### 阶段 3: 部署（需用户确认）

判定通过后，**必须先获得用户确认**再执行部署:

#### 1. 确认部署模式
- `build`: 全量构建（`./deploy-remote.sh build`）
- `quick`: 快速部署（`./deploy-remote.sh quick`，默认）

使用 AskUserQuestion 确认:
- 部署模式（build/quick）
- 是否确认执行部署

#### 2. 执行部署
- 运行 `./deploy-remote.sh [build|quick]`
- 等待部署结果

#### 3. 部署验证
- 展示容器状态（`docker ps` 或远程查看）
- 确认所有服务正常运行

#### 4. 版本标签
- 部署成功后打版本标签: `git tag v{YYYY-MM-DD}`（如 `v2026-03-05`）
- 如果当天已有标签，追加序号: `v2026-03-05.2`

## 输出格式

```
## 部署报告

### 预检结果
- Git 工作区: ✅ 干净 / ❌ 有未提交变更
- 验收状态: ✅ 已验收 / ⚠️ 未验收
- 配置检查: ✅ 通过 / ❌ 有问题

### 部署结果
- 模式: build / quick
- 状态: ✅ 成功 / ❌ 失败
- 版本标签: v{date}

### 容器状态
{容器运行状态}
```
