"""advanced scheduling - hotspot detection and periodicity analysis

This migration implements advanced scheduling features:
1. Adds periodicity analysis fields for detecting hourly/daily/weekly patterns
2. Adds hotspot detection fields for aggressive privilege escalation
3. Inserts 18 new system settings for hotspot, periodicity, and window boost configuration

Revision ID: 0008_advanced_scheduling
Revises: 0007_add_cleanup_settings
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_advanced_scheduling"
down_revision = "0007_add_cleanup_settings"
branch_labels = None
depends_on = None


def upgrade():
    # 1. 添加周期性识别字段
    op.add_column("source_configs", sa.Column("periodicity_data", sa.Text(), nullable=True))
    op.add_column("source_configs", sa.Column("periodicity_updated_at", sa.DateTime(), nullable=True))

    # 2. 添加热点状态缓存字段
    op.add_column("source_configs", sa.Column("hotspot_level", sa.String(), nullable=True))
    op.add_column("source_configs", sa.Column("hotspot_detected_at", sa.DateTime(), nullable=True))

    # 3. 插入系统配置项
    conn = op.get_bind()

    # 热点提权参数（11个）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            -- 热点功能开关
            ('hotspot_enabled', 'true', '是否启用热点检测', NOW()),

            -- 提权因子（分级响应）
            ('hotspot_instant_factor', '0.3', '即时热点提权因子（缩短到30%）', NOW()),
            ('hotspot_high_factor', '0.2', '高度热点提权因子（缩短到20%）', NOW()),
            ('hotspot_extreme_factor', '0.1', '极端热点提权因子（缩短到10%）', NOW()),

            -- 触发阈值（绝对值）
            ('hotspot_instant_threshold', '5', '即时热点触发阈值（新内容数 ≥5）', NOW()),
            ('hotspot_high_threshold', '8', '高度热点触发阈值（新内容数 ≥8）', NOW()),
            ('hotspot_extreme_threshold', '10', '极端热点触发阈值（新内容数 ≥10）', NOW()),

            -- 相对突增倍数
            ('hotspot_surge_multiplier_2x', '2.0', '相对突增2倍触发instant热点', NOW()),
            ('hotspot_surge_multiplier_3x', '3.0', '相对突增3倍触发high热点', NOW()),

            -- 其他参数
            ('hotspot_history_days', '7', '计算历史均值的天数', NOW()),
            ('max_hotspot_sources', '5', '全局热点源数量上限', NOW())
        ON CONFLICT (key) DO NOTHING
    """))

    # 周期性识别参数（4个）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('periodicity_enabled', 'true', '是否启用周期性识别', NOW()),
            ('periodicity_min_samples', '14', '周期性分析最小样本数', NOW()),
            ('periodicity_confidence_threshold', '0.7', '周期性识别置信度阈值', NOW()),
            ('periodicity_analysis_interval', '86400', '周期性分析间隔（秒，默认24小时）', NOW())
        ON CONFLICT (key) DO NOTHING
    """))

    # 时间窗口提权参数（3个）
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('window_boost_enabled', 'true', '是否启用时间窗口提权', NOW()),
            ('window_boost_hourly_factor', '0.4', 'hourly模式窗口提权因子', NOW()),
            ('window_boost_weekly_factor', '0.6', 'weekly模式窗口提权因子', NOW())
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    # 1. 删除系统配置项
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM system_settings
        WHERE key IN (
            -- 热点配置
            'hotspot_enabled',
            'hotspot_instant_factor',
            'hotspot_high_factor',
            'hotspot_extreme_factor',
            'hotspot_instant_threshold',
            'hotspot_high_threshold',
            'hotspot_extreme_threshold',
            'hotspot_surge_multiplier_2x',
            'hotspot_surge_multiplier_3x',
            'hotspot_history_days',
            'max_hotspot_sources',

            -- 周期性配置
            'periodicity_enabled',
            'periodicity_min_samples',
            'periodicity_confidence_threshold',
            'periodicity_analysis_interval',

            -- 时间窗口配置
            'window_boost_enabled',
            'window_boost_hourly_factor',
            'window_boost_weekly_factor'
        )
    """))

    # 2. 删除热点状态字段
    op.drop_column("source_configs", "hotspot_detected_at")
    op.drop_column("source_configs", "hotspot_level")

    # 3. 删除周期性字段
    op.drop_column("source_configs", "periodicity_updated_at")
    op.drop_column("source_configs", "periodicity_data")
