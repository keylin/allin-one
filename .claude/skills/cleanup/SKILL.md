---
name: cleanup
description: 数据清理 — 分析存储占用 → 检测孤立数据 → Dry-run → 确认执行 → 清理报告
argument-hint: [可选: media|logs|tasks|orphans|all] (默认 dry-run 全量分析)
model: sonnet
---

# 数据清理

分析并清理过期/孤立数据，释放存储空间。清理范围: **$ARGUMENTS**（默认全量分析）

## 清理类别

| 类别 | 关键词 | 清理内容 |
|------|-------|---------|
| media | `media` | 孤立媒体文件（无 MediaItem 引用的文件） |
| logs | `logs` | 过期日志文件（>7 天的归档日志） |
| tasks | `tasks` | 过期任务记录（>30 天的已完成 procrastinate_jobs） |
| orphans | `orphans` | 孤立数据库记录（无关联的 MediaItem、ExecutionRecord 等） |
| all | `all` | 以上全部 |

## 三阶段工作流

### 阶段 1: 存储分析

```bash
# 总体磁盘占用
du -sh /Users/lin/workspace/allin-one/data/
du -sh /Users/lin/workspace/allin-one/data/*/

# 媒体文件分析
find /Users/lin/workspace/allin-one/data/media/ -type f | wc -l
du -sh /Users/lin/workspace/allin-one/data/media/

# 日志文件分析
ls -lhS /Users/lin/workspace/allin-one/data/logs/

# 数据库表大小
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT schemaname || '.' || tablename as table_name,
       pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) as total_size,
       n_live_tup as row_count
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
LIMIT 15;"

# 任务记录统计
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
SELECT status, count(*),
       min(scheduled_at) as oldest,
       max(scheduled_at) as newest
FROM procrastinate_jobs
GROUP BY status
ORDER BY status;"
```

### 阶段 2: Dry-run 分析

**不执行任何删除操作**，只分析并报告可清理的内容:

#### 孤立媒体文件
```bash
# 获取数据库中所有 MediaItem 的文件路径
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -t -c "
SELECT local_path FROM media_items WHERE local_path IS NOT NULL;" > /tmp/db_media_paths.txt

# 对比文件系统中的实际文件，找出未被引用的
```

#### 过期任务记录
```sql
-- 超过 30 天的已完成任务
SELECT count(*), pg_size_pretty(pg_total_relation_size('procrastinate_jobs'))
FROM procrastinate_jobs
WHERE status = 'succeeded'
  AND scheduled_at < now() - interval '30 days';
```

#### 孤立数据库记录
```sql
-- 无关联 Source 的 ContentItem
SELECT count(*) FROM content_items ci
LEFT JOIN source_configs sc ON ci.source_id = sc.id
WHERE sc.id IS NULL;

-- 无关联 ContentItem 的 MediaItem
SELECT count(*) FROM media_items mi
LEFT JOIN content_items ci ON mi.content_item_id = ci.id
WHERE ci.id IS NULL;
```

#### 过期日志
```bash
# 超过 7 天的日志文件
find /Users/lin/workspace/allin-one/data/logs/ -name "*.log.*" -mtime +7 -ls
```

### 阶段 3: 确认并执行

**必须向用户展示 Dry-run 结果并获得确认后才能执行删除**。

使用 AskUserQuestion 展示:
```
即将清理以下内容:
- 孤立媒体文件: {N} 个, 约 {size}
- 过期任务记录: {N} 条
- 孤立数据库记录: {N} 条
- 过期日志: {N} 个文件, 约 {size}

总计释放约 {total_size}

确认执行? (y/n)
```

用户确认后:

```bash
# 清理过期任务记录
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
DELETE FROM procrastinate_jobs
WHERE status = 'succeeded'
  AND scheduled_at < now() - interval '30 days';"

# 清理孤立 MediaItem
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "
DELETE FROM media_items mi
USING (
  SELECT mi2.id FROM media_items mi2
  LEFT JOIN content_items ci ON mi2.content_item_id = ci.id
  WHERE ci.id IS NULL
) orphans
WHERE mi.id = orphans.id;"

# 清理孤立媒体文件（逐个确认后删除）
# 清理过期日志
find /Users/lin/workspace/allin-one/data/logs/ -name "*.log.*" -mtime +7 -delete

# VACUUM 回收空间
docker compose -f docker-compose.local.yml exec postgres psql -U allinone -d allinone -c "VACUUM ANALYZE;"
```

## 输出格式

```
## 清理报告

### 清理前
- 磁盘占用: {before_size}
- 数据库大小: {before_db_size}

### 清理内容
| 类别 | 清理数量 | 释放空间 |
|------|---------|---------|
| 孤立媒体文件 | {N} 个 | {size} |
| 过期任务记录 | {N} 条 | {size} |
| 孤立数据库记录 | {N} 条 | — |
| 过期日志 | {N} 个 | {size} |

### 清理后
- 磁盘占用: {after_size}
- 数据库大小: {after_db_size}
- 总释放: {freed_size}

### 建议
- 定期运行 `/cleanup` 保持存储健康
- 如果媒体增长过快，检查 localize_media 配置
```

## 安全原则

- **永远先 Dry-run**: 不经分析和确认不执行任何删除
- **不删活跃数据**: 只清理孤立/过期数据
- **保留最近 30 天**: 任务记录至少保留 30 天
- **日志保留 7 天**: 当前活跃日志文件不删除
- **VACUUM 回收**: 删除后执行 VACUUM ANALYZE
