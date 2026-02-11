---
name: new-collector
description: 引导创建新的数据采集器（Collector）
argument-hint: <数据源类型> (如 rss_std, scraper, akshare)
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# 创建新的数据采集器

你正在为以下数据源类型创建采集器: **$ARGUMENTS**

## 开始之前

阅读现有模式和接口:
1. `backend/app/models/content.py` — SourceConfig, ContentItem, CollectionRecord, SourceType 枚举
2. `backend/app/tasks/scheduled_tasks.py` — 调度器如何调用采集器
3. `backend/app/services/pipeline/registry.py` — 步骤定义（注意不要和采集器混淆）
4. `docs/system_design.md` 第 4 节 — 采集器设计和三级抓取策略
5. `docs/business_glossary.md` 第 3.1 节 — SourceType 枚举值

确认 `$ARGUMENTS` 数据源类型已存在于 `backend/app/models/content.py` 的 SourceType 枚举中。

## 架构规则（必须遵守）

- 采集器不是流水线步骤。它们运行在调度器循环中，不在流水线内。
- 采集器的职责: 给定一个 SourceConfig，抓取原始条目，创建 ContentItem 行。
- 去重由 `(source_id, external_id)` 唯一约束处理。
- 采集完成后，调度器为每条新内容触发 PipelineOrchestrator。
- 采集器不得调用任何流水线或步骤处理器代码。
- 没有 BilibiliVideoCollector 或 YouTubeVideoCollector。视频下载是流水线步骤。

## 第 1 步: 创建采集器文件

创建 `backend/app/services/collectors/$ARGUMENTS.py`:

```python
"""$ARGUMENTS 采集器"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.content import SourceConfig, ContentItem, CollectionRecord, ContentStatus, MediaType

logger = logging.getLogger(__name__)


class ${CollectorName}Collector:
    """从 $ARGUMENTS 类型的数据源采集内容。"""

    async def collect(self, source: SourceConfig, db: Session) -> list[ContentItem]:
        """从数据源抓取新条目。

        Args:
            source: 数据源配置，包含 url、config_json 等。
            db: 数据库会话，用于创建 ContentItem。

        Returns:
            新创建的 ContentItem 列表。
        """
        config = json.loads(source.config_json or '{}')
        new_items = []

        # TODO: 实现 $ARGUMENTS 特有的抓取逻辑
        # raw_entries = await self._fetch_entries(source.url, config)

        # 为每条数据创建 ContentItem（去重由唯一约束保证）:
        # for entry in raw_entries:
        #     item = ContentItem(
        #         source_id=source.id,
        #         title=entry["title"],
        #         external_id=entry["url"],  # 用于去重
        #         url=entry["url"],
        #         author=entry.get("author"),
        #         raw_data=json.dumps(entry, ensure_ascii=False),
        #         status=ContentStatus.PENDING.value,
        #         media_type=source.media_type or MediaType.TEXT.value,
        #         published_at=entry.get("published_at"),
        #         collected_at=datetime.now(timezone.utc),
        #     )
        #     db.add(item)
        #     new_items.append(item)

        return new_items
```

## 第 2 步: 注册到采集服务

在 `backend/app/tasks/scheduled_tasks.py`（或专门的 CollectionService）中添加映射:

```python
from app.services.collectors.$ARGUMENTS import ${CollectorName}Collector

COLLECTOR_MAP = {
    # ... 已有的采集器 ...
    "$ARGUMENTS": ${CollectorName}Collector(),
}
```

## 第 3 步: 创建采集记录

记录每次采集尝试，用于监控:

```python
record = CollectionRecord(
    source_id=source.id,
    status="completed",  # 或 "failed"
    items_found=len(raw_entries),
    items_new=len(new_items),
    completed_at=datetime.now(timezone.utc),
)
db.add(record)
db.commit()
```

## 第 4 步: 错误处理

遵循 `scheduled_tasks.py` 中已有的退避策略:
- 成功时: 重置 `source.consecutive_failures = 0`
- 失败时: 递增 `source.consecutive_failures += 1`
- 调度器会根据失败次数自动应用指数退避

## 自查清单

- [ ] SourceType 枚举中存在 `$ARGUMENTS`
- [ ] 采集器返回包含所有必填字段的 ContentItem 对象
- [ ] `external_id` 在同一数据源内唯一（去重由 DB 约束保证）
- [ ] `raw_data` 是合法的 JSON 字符串
- [ ] `published_at` 是 UTC 时间或 None
- [ ] `collected_at` 设置为 `datetime.now(timezone.utc)`
- [ ] 每次采集都创建了 CollectionRecord
- [ ] 采集器中没有调用流水线或步骤处理器代码
- [ ] HTTP 请求设置了合理的超时时间
