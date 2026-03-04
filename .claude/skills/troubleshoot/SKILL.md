---
name: troubleshoot
description: 问题修复专家 — 根据问题现象分析日志与代码，定位根因并修复
argument-hint: <问题描述> (如 "worker 反复重启", "内容列表空白", "采集任务卡住")
model: opus
allowed-tools: Read, Grep, Glob, Edit, Write, Bash, Agent
---

# 问题修复专家 (Troubleshooter)

当前问题: **$ARGUMENTS**

## 工作流程

按以下五阶段排查并修复问题:

### 1. 现象收集
- 理解 `$ARGUMENTS` 中描述的问题现象
- 确认影响范围（哪些功能、本地还是远程）

### 2. 日志分析

**重要**: 日志脚本必须用非交互模式（传子命令 + `--no-follow`），否则会挂起。文件日志优先用 Read 工具直接读取。

**本地环境**:
```bash
# 文件日志 — 优先用 Read 工具读取
# data/logs/error.log, data/logs/backend.log, data/logs/worker.log

# 容器错误汇总（推荐首先执行）
./logs-local.sh error --no-follow

# 特定服务容器日志
./logs-local.sh app --no-follow -n 200
./logs-local.sh worker --no-follow -n 200
./logs-local.sh pipeline --no-follow -n 200
./logs-local.sh scheduled --no-follow -n 200

# 按关键词/时间过滤
./logs-local.sh worker --no-follow --grep "error" -n 500
./logs-local.sh app --no-follow --since "30m"
```

**远程环境** (远程: `allin@192.168.1.103:2222`, 目录: `~/allin-one`):
```bash
# 远程错误汇总（推荐首先执行）
./logs-remote.sh error --no-follow

# 远程容器日志
./logs-remote.sh app --no-follow -n 200
./logs-remote.sh worker --no-follow -n 200

# 远程文件日志
./logs-remote.sh file backend --no-follow -n 200
./logs-remote.sh file error --no-follow -n 200

# 直接 SSH（日志脚本不够用时）
ssh -T -p 2222 allin@192.168.1.103 "cd ~/allin-one && docker compose -f docker-compose.remote.yml ps"
ssh -T -p 2222 allin@192.168.1.103 "cd ~/allin-one && docker compose -f docker-compose.remote.yml logs --tail 100 allin-one"
```

容器名: `allin-one`(app), `allin-worker-pipeline`, `allin-worker-scheduled`, `allin-rsshub`, `allin-browserless`, `allin-postgres`

按时间线还原错误过程，识别关键错误堆栈。

### 3. 代码溯源

根据日志中的错误信息，用 Grep/Read 追踪代码路径:
- 定位出错的文件和行号
- 理解调用链路和上下文
- 区分直接原因和根本原因

阅读相关规范确认正确做法:
- `CLAUDE.md` — 项目架构约束
- `backend/CLAUDE.md` — 后端开发规范
- `frontend/CLAUDE.md` — 前端开发规范

### 4. 修复实施

**简单问题** — 直接修复代码。

**复杂问题** — 用 Agent 工具派发专家:
- `backend-developer` — 后端多文件修复、数据库迁移
- `frontend-developer` — 前端组件重构、状态管理
- `code-tester` — 修复后代码质量验证
- `product-reviewer` — 修复后产品体验验收

### 5. 验证闭环
- 确认错误不再出现
- 检查是否引入回归问题

## 输出格式

```
## 问题诊断: {问题简述}

### 现象
{问题现象}

### 根因
{根本原因，附代码位置}

### 修复
{修改内容}

### 验证
{验证结果}
```
