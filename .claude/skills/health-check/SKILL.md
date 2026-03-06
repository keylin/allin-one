---
name: health-check
description: 系统健康检查 — 容器状态 → 数据库连接 → Worker 队列 → 磁盘空间 → 错误汇总
argument-hint: [可选: local|remote] (默认 local)
model: sonnet
---

# 系统健康检查

对运行环境进行全面健康检查。目标环境: **$ARGUMENTS**（默认 local）

## 环境配置

| 环境 | compose 文件 | 访问方式 |
|------|-------------|---------|
| local | `docker-compose.local.yml` | 本地直连 |
| remote | `docker-compose.remote.yml` | SSH `allin@192.168.1.103:2222` |

## 检查项（按顺序执行）

### 1. 容器状态

```bash
# Local
docker compose -f docker-compose.local.yml ps -a

# Remote
ssh -T -p 2222 allin@192.168.1.103 "cd ~/allin-one && docker compose -f docker-compose.remote.yml ps -a"
```

**期望**: 所有容器 `Up`，无 `Restarting` 或 `Exited`

检查容器列表:
- `allin-one` (backend) — FastAPI 应用
- `allin-worker-pipeline` — Pipeline Worker (concurrency=4)
- `allin-worker-scheduled` — Scheduled Worker (concurrency=2)
- `allin-postgres` — PostgreSQL
- `allin-rsshub` — RSSHub
- `allin-browserless` — Browserless (浏览器渲染)

### 2. 数据库连接与连接池

```bash
# 连接池使用状态
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT state, count(*), max(now() - state_change) as max_duration
FROM pg_stat_activity
WHERE datname = 'allinone'
GROUP BY state
ORDER BY count DESC;"

# 数据库大小
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT pg_size_pretty(pg_database_size('allinone')) as db_size;"

# 最大的表
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT schemaname || '.' || tablename as table_name,
       pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as total_size,
       n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
LIMIT 10;"
```

**关注**: idle 连接是否过多（> DB_POOL_SIZE * 容器数），是否有长时间 active 查询

### 3. Worker 队列状态

```bash
# 队列深度和延迟
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT queue_name, status, count(*),
       CASE WHEN status = 'todo' THEN
         extract(epoch from now() - min(scheduled_at))::int || 's waiting'
       ELSE '-' END as max_delay
FROM procrastinate_jobs
WHERE status IN ('todo', 'doing', 'failed')
GROUP BY queue_name, status
ORDER BY queue_name, status;"

# 最近 1 小时的任务吞吐
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT queue_name, status, count(*)
FROM procrastinate_jobs
WHERE scheduled_at > now() - interval '1 hour'
GROUP BY queue_name, status
ORDER BY queue_name, status;"

# 失败任务 Top 5（按任务类型）
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT task_name, count(*) as fail_count,
       max(scheduled_at) as last_failure
FROM procrastinate_jobs
WHERE status = 'failed'
  AND scheduled_at > now() - interval '24 hours'
GROUP BY task_name
ORDER BY fail_count DESC
LIMIT 5;"
```

**关注**: `todo` 堆积、`doing` 超时（>10min）、`failed` 集中

### 4. 磁盘空间

```bash
# data/ 目录大小
du -sh /Users/lin/workspace/allin-one/data/
du -sh /Users/lin/workspace/allin-one/data/*/

# 日志文件大小
ls -lh /Users/lin/workspace/allin-one/data/logs/

# Docker 存储
docker system df
```

**关注**: `data/media/` 增长趋势、日志文件过大（>100MB）

### 5. 最近错误汇总

```bash
# 文件错误日志（最近 50 行）
tail -50 /Users/lin/workspace/allin-one/data/logs/error.log

# 容器错误日志
./logs-local.sh error --no-follow
```

**关注**: 重复出现的错误模式、新出现的错误类型

### 6. 服务可达性

```bash
# Backend API
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "unreachable"

# RSSHub
curl -s -o /dev/null -w "%{http_code}" http://localhost:1200 2>/dev/null || echo "unreachable"
```

## 输出格式

```
## 健康检查报告

### 环境: local / remote
### 检查时间: {timestamp}

### 总体状态: healthy / degraded / unhealthy

### 容器状态
| 容器 | 状态 | 运行时间 |
|------|------|---------|
| ... | Up / Down | ... |

### 数据库
- 连接池: {active}/{idle}/{total} (上限 {pool_size})
- 数据库大小: {size}
- 最大表: {table} ({size}, {rows} rows)

### Worker 队列
| 队列 | Pending | Running | Failed | 最大延迟 |
|------|---------|---------|--------|---------|
| pipeline | ... | ... | ... | ... |
| scheduled | ... | ... | ... | ... |

### 磁盘空间
- data/ 总计: {size}
- media/: {size}
- logs/: {size}

### 最近错误 (24h)
- {错误类型}: {次数}
- ...

### 问题与建议
- {问题}: {建议操作}
  - 磁盘空间不足 → `/cleanup`
  - Worker 异常 → `/worker-debug`
  - 容器崩溃 → 检查日志后重启
```

## 与其他 Skill 联动

- `/g-ship` 部署后可调用 `/health-check` 验证部署结果
- 发现 Worker 问题 → 建议 `/worker-debug` 深入诊断
- 磁盘空间不足 → 建议 `/cleanup` 清理数据
