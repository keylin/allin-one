---
name: worker-debug
description: Worker 任务调试 — 查询任务状态 → 关联日志 → 诊断根因 → 建议操作
argument-hint: <问题描述> (如 "pipeline 任务卡住", "scheduled 任务不执行", "任务反复失败")
model: sonnet
---

# Worker 任务调试

诊断 Procrastinate 双进程 Worker 架构中的任务问题。当前问题: **$ARGUMENTS**

## 架构背景

- **双进程队列隔离**:
  - `worker-pipeline` (concurrency=4, queue=pipeline) — 跑流水线步骤
  - `worker-scheduled` (concurrency=2, queue=scheduled) — 跑定时采集/报告/清理
- **任务调度**: `procrastinate_jobs` 表存储所有任务状态
- **日志位置**: `data/logs/worker.log`, `data/logs/error.log`

## 四阶段工作流

### 阶段 1: 任务状态查询

查询 Procrastinate 任务表，了解当前任务状态分布:

```bash
# 连接数据库
cd /Users/lin/workspace/allin-one

# 任务状态总览
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT status, queue_name, count(*)
FROM procrastinate_jobs
GROUP BY status, queue_name
ORDER BY queue_name, status;"

# 失败任务详情（最近 20 条）
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT id, queue_name, task_name, status,
       scheduled_at, started_at,
       attempts,
       left(args::text, 200) as args_preview
FROM procrastinate_jobs
WHERE status IN ('failed', 'error')
ORDER BY scheduled_at DESC
LIMIT 20;"

# 卡住的任务（运行中超过 10 分钟）
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT id, queue_name, task_name, status,
       started_at,
       now() - started_at as duration
FROM procrastinate_jobs
WHERE status = 'doing'
  AND started_at < now() - interval '10 minutes'
ORDER BY started_at;"

# Pending 堆积（按队列）
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT queue_name, count(*),
       min(scheduled_at) as oldest_pending,
       now() - min(scheduled_at) as max_wait_time
FROM procrastinate_jobs
WHERE status = 'todo'
GROUP BY queue_name;"
```

根据问题描述，选择合适的查询组合。

### 阶段 2: 日志关联

根据阶段 1 发现的问题任务，关联 Worker 日志:

**文件日志**（用 Read 工具直接读取）:
- `data/logs/worker.log` — Worker 任务执行日志
- `data/logs/error.log` — 错误汇总

**容器日志**:
```bash
# Pipeline Worker 日志
./logs-local.sh pipeline --no-follow -n 300

# Scheduled Worker 日志
./logs-local.sh scheduled --no-follow -n 300

# 按关键词过滤（用任务 ID 或错误信息）
./logs-local.sh worker --no-follow --grep "{keyword}" -n 500
```

**分析要点**:
- 错误堆栈和异常类型
- 任务重试次数和间隔
- Worker 进程是否存活
- 内存/连接池耗尽迹象

### 阶段 3: 根因诊断

结合任务状态和日志，判断问题类型:

#### 常见问题模式

| 现象 | 可能原因 | 诊断方法 |
|------|---------|---------|
| 任务状态 `doing` 超时 | 死锁/无限循环/外部依赖超时 | 检查 started_at 时间 + worker 日志 |
| 任务反复 `failed` | 代码 bug/数据异常/依赖服务不可用 | 查看 attempts 和错误日志 |
| `todo` 堆积不消费 | Worker 未启动/Worker 崩溃/队列名不匹配 | `docker compose ps` + worker 容器日志 |
| 定时任务不触发 | scheduled worker 未运行/cron 表达式错误 | 检查 worker-scheduled 容器状态 |
| DB 连接错误 | 连接池耗尽/PG 容器异常 | `pg_stat_activity` 查询 + PG 日志 |
| LLM API 错误 | API Key 无效/限流/网络问题 | 检查错误日志中的 HTTP 状态码 |

#### 深入诊断

```bash
# Worker 容器状态
docker compose -f docker-compose.local.yml ps

# PG 连接池状态
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT state, count(*)
FROM pg_stat_activity
WHERE datname = 'allinone'
GROUP BY state;"

# 特定任务的完整错误信息
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT id, task_name, args, status, attempts,
       scheduled_at, started_at,
       left(events::text, 500) as events_preview
FROM procrastinate_jobs
WHERE id = {task_id};"
```

### 阶段 4: 建议操作

根据诊断结果，给出明确的操作建议:

- **配置问题** → 直接调整配置（concurrency/timeout/retry 策略）
- **代码 Bug** → `/g-develop "修复 {task_name} 中的 XX 问题"`
- **架构缺陷** → `/g-design "重新设计 {模块} 的任务处理方式"`
- **资源不足** → 调整 Worker 配置或扩容
- **数据异常** → 手动修复数据或标记跳过
- **外部依赖** → 检查依赖服务状态，必要时降级处理

## 输出格式

```
## Worker 诊断报告: {问题描述}

### 任务状态
{状态分布和异常任务列表}

### 日志分析
{关键错误和时间线}

### 根因
{根本原因，附代码位置或配置项}

### 建议操作
{具体操作步骤，含命令}

### 下一步
- 配置调整 → 直接执行
- 代码修复 → `/g-develop "{修复描述}"`
- 架构调整 → `/g-design "{设计描述}"`
```

## 关键文件

- `backend/app/tasks/procrastinate_app.py` — Procrastinate 应用配置
- `backend/app/tasks/pipeline_tasks.py` — Pipeline 任务定义
- `backend/app/tasks/collection_tasks.py` — 采集任务定义
- `backend/app/services/pipeline/executor.py` — 流水线执行器
- `data/logs/worker.log` — Worker 日志
- `data/logs/error.log` — 错误日志

## 紧急操作速查

```bash
# 重启 Worker 容器
docker compose -f docker-compose.local.yml restart worker-pipeline
docker compose -f docker-compose.local.yml restart worker-scheduled

# 强制取消卡住的任务
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
UPDATE procrastinate_jobs SET status = 'failed'
WHERE id = {task_id} AND status = 'doing';"

# 重试失败任务（谨慎使用）
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
UPDATE procrastinate_jobs SET status = 'todo', attempts = 0
WHERE id = {task_id} AND status = 'failed';"
```
