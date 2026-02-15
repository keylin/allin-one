"""intelligent scheduling - dynamic interval calculation based on historical data

This migration implements the intelligent dynamic scheduling strategy:
1. Replaces fixed schedule_interval with flexible schedule_mode system
2. Adds calculated_interval and next_collection_at for smart scheduling
3. Migrates existing sources to appropriate modes (auto/fixed)
4. Adds system settings for scheduling configuration

Revision ID: 0006_intelligent_scheduling
Revises: 0005_dedup_content_items_by_url
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_intelligent_scheduling"
down_revision = "0005_dedup_url"
branch_labels = None
depends_on = None


def upgrade():
    # 1. 添加新列（先添加，后面重命名旧列）
    op.add_column("source_configs", sa.Column("schedule_mode", sa.String(), nullable=True))
    op.add_column("source_configs", sa.Column("schedule_interval_override", sa.Integer(), nullable=True))
    op.add_column("source_configs", sa.Column("calculated_interval", sa.Integer(), nullable=True))
    op.add_column("source_configs", sa.Column("next_collection_at", sa.DateTime(), nullable=True))

    # 2. 数据迁移：将现有的 schedule_interval 迁移到新字段
    #    - 如果 schedule_interval != 3600（非默认值），设为 fixed 模式并保存到 override
    #    - 如果 schedule_interval == 3600（默认值），设为 auto 模式
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE source_configs
        SET schedule_mode = CASE
            WHEN schedule_interval != 3600 THEN 'fixed'
            ELSE 'auto'
        END,
        schedule_interval_override = CASE
            WHEN schedule_interval != 3600 THEN schedule_interval
            ELSE NULL
        END
    """))

    # 3. 删除旧列 schedule_interval
    op.drop_column("source_configs", "schedule_interval")

    # 4. 设置 schedule_mode 默认值（对于新创建的记录）
    op.alter_column("source_configs", "schedule_mode",
                    server_default="auto",
                    nullable=False)

    # 5. 创建性能索引（用于定时任务的轮询查询）
    op.create_index(
        "ix_source_next_collection",
        "source_configs",
        ["is_active", "schedule_enabled", "next_collection_at"],
    )

    # 6. 添加 SystemSettings 配置项
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('schedule_min_interval', '300', '最小采集间隔（秒）', NOW()),
            ('schedule_max_interval', '86400', '最大采集间隔（秒）', NOW()),
            ('schedule_base_interval', '3600', '基础采集间隔（秒）', NOW()),
            ('schedule_lookback_window', '10', '统计的历史采集次数', NOW()),
            ('schedule_activity_high', '5.0', '高活跃阈值', NOW()),
            ('schedule_activity_medium', '2.0', '中活跃阈值', NOW()),
            ('schedule_activity_low', '0.5', '低活跃阈值', NOW())
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    # 1. 删除 SystemSettings 配置项
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM system_settings
        WHERE key IN (
            'schedule_min_interval',
            'schedule_max_interval',
            'schedule_base_interval',
            'schedule_lookback_window',
            'schedule_activity_high',
            'schedule_activity_medium',
            'schedule_activity_low'
        )
    """))

    # 2. 删除索引
    op.drop_index("ix_source_next_collection", table_name="source_configs")

    # 3. 恢复旧列 schedule_interval
    op.add_column("source_configs", sa.Column("schedule_interval", sa.Integer(), nullable=True))

    # 4. 数据恢复：从 schedule_interval_override 或使用默认值 3600
    conn.execute(sa.text("""
        UPDATE source_configs
        SET schedule_interval = COALESCE(schedule_interval_override, 3600)
    """))

    # 5. 设置默认值并设为非空
    op.alter_column("source_configs", "schedule_interval",
                    server_default="3600",
                    nullable=False)

    # 6. 删除新列
    op.drop_column("source_configs", "next_collection_at")
    op.drop_column("source_configs", "calculated_interval")
    op.drop_column("source_configs", "schedule_interval_override")
    op.drop_column("source_configs", "schedule_mode")
