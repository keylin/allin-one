"""add cleanup settings - configurable cleanup time and retention policies

This migration adds system settings for configurable data cleanup:
1. Cleanup time configuration (cleanup_content_time, cleanup_records_time)
2. Minimum keep count per source (collection_min_keep)
3. Last run tracking (cleanup_content_last_run, cleanup_records_last_run)
4. Updates default collection retention to 90 days

Revision ID: 0007_add_cleanup_settings
Revises: 0006_intelligent_scheduling
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_add_cleanup_settings"
down_revision = "0006_intelligent_scheduling"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. 添加清理时间配置
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES
            ('cleanup_content_time', '03:00', '内容清理时间（UTC HH:MM）', NOW()),
            ('cleanup_records_time', '03:30', '记录清理时间（UTC HH:MM）', NOW()),
            ('collection_min_keep', '10', '每个数据源最少保留采集记录数', NOW())
        ON CONFLICT (key) DO NOTHING
    """))

    # 2. 更新默认采集记录保留天数（30天 → 90天）
    conn.execute(sa.text("""
        UPDATE system_settings
        SET value = '90'
        WHERE key = 'collection_retention_days' AND value = '30'
    """))

    # 3. 如果 collection_retention_days 不存在，则创建
    conn.execute(sa.text("""
        INSERT INTO system_settings (key, value, description, updated_at)
        VALUES ('collection_retention_days', '90', '采集记录保留天数（0表示永久保留）', NOW())
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade():
    conn = op.get_bind()

    # 删除新增的设置项
    conn.execute(sa.text("""
        DELETE FROM system_settings
        WHERE key IN (
            'cleanup_content_time',
            'cleanup_records_time',
            'collection_min_keep'
        )
    """))

    # 恢复 collection_retention_days 为 30 天（如果用户没有修改过）
    conn.execute(sa.text("""
        UPDATE system_settings
        SET value = '30'
        WHERE key = 'collection_retention_days' AND value = '90'
    """))
