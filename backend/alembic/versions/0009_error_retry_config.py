"""error retry config - intelligent error classification and tiered retry

This migration implements intelligent error retry mechanism:
1. Collector-level immediate retry configuration (3 settings)
2. Scheduler-level transient error fast retry configuration (2 settings)
3. Backoff strategy configuration for permanent errors (3 settings)

Total: 8 new system settings for error classification and tiered retry

Revision ID: 0009_error_retry_config
Revises: 0008_advanced_scheduling
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_error_retry_config"
down_revision = "0008_advanced_scheduling"
branch_labels = None
depends_on = None


def upgrade():
    # 插入错误重试配置项（8个）
    conn = op.get_bind()

    # 采集层立即重试配置（3个）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('retry_in_collector_enabled', 'true', '是否启用采集层立即重试', NOW()),
            ('retry_in_collector_max_attempts', '3', '采集层最大重试次数（包含首次尝试）', NOW()),
            ('retry_in_collector_delays', '30,60', '采集层重试间隔（秒），逗号分隔', NOW())
        ON CONFLICT (key) DO NOTHING
    """))

    # 调度层快速重试配置（2个，暂时性错误）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('retry_transient_intervals', '300,900,1800,3600', '暂时性错误快速重试间隔序列（5min,15min,30min,1h）', NOW()),
            ('retry_transient_max_failures', '4', '暂时性错误使用固定间隔的最大失败次数', NOW())
        ON CONFLICT (key) DO NOTHING
    """))

    # 退避策略配置（3个）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('backoff_permanent_enabled', 'true', '是否对持续性错误启用激进退避', NOW()),
            ('backoff_base_interval', '3600', '退避基础间隔（秒，默认1小时）', NOW()),
            ('backoff_max_interval', '86400', '退避最大间隔（秒，默认24小时）', NOW())
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    # 删除错误重试配置项
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM system_settings
        WHERE key IN (
            -- 采集层重试配置
            'retry_in_collector_enabled',
            'retry_in_collector_max_attempts',
            'retry_in_collector_delays',

            -- 调度层暂时性错误配置
            'retry_transient_intervals',
            'retry_transient_max_failures',

            -- 退避策略配置
            'backoff_permanent_enabled',
            'backoff_base_interval',
            'backoff_max_interval'
        )
    """))
