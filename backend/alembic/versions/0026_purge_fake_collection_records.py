"""清理非采集型数据源上的假采集记录与错误的调度状态

审计（docs/audit_2026-09_architecture.md §3-B）：采集任务此前对任意类型的数据源都会执行，
没有采集器的类型也写一条 completed / 0 条的记录、更新 last_collected_at、计算下次采集时间。
生产库里 sync.bilibili 有 261 条、sync.emby 有 3 条这样的假成功记录，污染成功率统计与调度活跃度。

代码侧已由源类型注册表（app/models/source_types.py）在入口处拦截，这里把历史数据归位。
纯数据修复，无法 autogenerate，故手写。downgrade 不恢复已删除的假记录。

Revision ID: 0026_purge_fake_collect
Revises: 0025_content_kind
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0026_purge_fake_collect'
down_revision: Union[str, Sequence[str], None] = '0025_content_kind'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 冻结在迁移里（与本版本的源类型注册表一致）
_COLLECTABLE = ('rss.hub', 'rss.standard', 'podcast.apple', 'web.scraper', 'api.akshare', 'account.generic', 'file.upload')
_SCHEDULABLE = ('rss.hub', 'rss.standard', 'podcast.apple', 'web.scraper', 'api.akshare', 'account.generic')


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # 1. 没有采集器的数据源不可能产生真实的采集记录
    op.execute(f"""
        DELETE FROM collection_records r
        USING source_configs s
        WHERE s.id = r.source_id AND s.source_type NOT IN {_in(_COLLECTABLE)}
    """)
    # 2. 不可调度的数据源：调度状态归位
    op.execute(f"""
        UPDATE source_configs
        SET schedule_enabled = false,
            schedule_mode = 'manual',
            next_collection_at = NULL,
            calculated_interval = NULL,
            periodicity_data = NULL,
            periodicity_updated_at = NULL,
            hotspot_level = NULL,
            hotspot_detected_at = NULL,
            consecutive_failures = 0
        WHERE source_type NOT IN {_in(_SCHEDULABLE)}
    """)
    # 3. 从未真正写入过内容的非采集型数据源，last_collected_at 只可能来自假采集
    op.execute(f"""
        UPDATE source_configs s
        SET last_collected_at = NULL
        WHERE s.source_type NOT IN {_in(_COLLECTABLE)}
          AND NOT EXISTS (SELECT 1 FROM content_items c WHERE c.source_id = s.id)
    """)


def downgrade() -> None:
    pass
