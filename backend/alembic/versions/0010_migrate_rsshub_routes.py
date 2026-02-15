"""Migrate RSSHub routes from url to config_json

Revision ID: 0010
Revises: 0009
Create Date: 2026-02-15
"""
from alembic import op
from sqlalchemy import text
import json

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    """将 rss.hub 源的 url 迁移到 config_json.rsshub_route"""
    conn = op.get_bind()

    # 查找所有 url 不为空的 RSSHub 源
    sources = conn.execute(text("""
        SELECT id, url, config_json
        FROM source_configs
        WHERE source_type = 'rss.hub' AND url IS NOT NULL AND url != ''
    """)).fetchall()

    migrated_count = 0

    for source in sources:
        config = json.loads(source.config_json or '{}')

        # 如果 config_json 中已有 rsshub_route，跳过
        if config.get('rsshub_route'):
            continue

        # 如果 url 看起来像路由（不是完整 HTTP URL），迁移到 config_json
        url = source.url.strip()
        if not url.startswith(('http://', 'https://')):
            config['rsshub_route'] = url
            conn.execute(text("""
                UPDATE source_configs
                SET config_json = :config, url = NULL
                WHERE id = :id
            """), {"config": json.dumps(config), "id": source.id})
            migrated_count += 1

    print(f"Migrated {migrated_count} RSSHub sources from url to config_json.rsshub_route")


def downgrade():
    """回滚：将 rsshub_route 移回 url 字段"""
    conn = op.get_bind()

    sources = conn.execute(text("""
        SELECT id, config_json
        FROM source_configs
        WHERE source_type = 'rss.hub' AND config_json IS NOT NULL
    """)).fetchall()

    for source in sources:
        config = json.loads(source.config_json or '{}')
        route = config.get('rsshub_route')

        if route:
            conn.execute(text("""
                UPDATE source_configs
                SET url = :url
                WHERE id = :id
            """), {"url": route, "id": source.id})
