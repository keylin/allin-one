"""content_items.kind —— 内容的领域身份一等化

审计（docs/audit_2026-09_architecture.md §3-A）发现「这是什么内容」有 6 种并存的判定方式，
影片靠 JOIN 数据源类型识别，导致混入信息流/未读/仪表盘口径，且删源会让影片隐形。

- 新增 kind 列（NOT NULL，server_default 'article'），按所属数据源类型回填
- 影片跨 sync.emby / user.film 两个数据源，全局唯一性落到部分唯一索引

回填含数据修复 SQL，无法 autogenerate，故手写。

Revision ID: 0025_content_kind
Revises: 0024_watch_status_backlog
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0025_content_kind'
down_revision: Union[str, Sequence[str], None] = '0024_watch_status_backlog'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 冻结在迁移里的映射（与 app.models.content._KIND_BY_SOURCE_TYPE 在本版本时一致）
_KIND_BY_SOURCE_TYPE = {
    'podcast.apple': 'audio',
    'sync.bilibili': 'video',
    'sync.apple_books': 'book',
    'sync.wechat_read': 'book',
    'sync.kindle': 'book',
    'sync.douban_books': 'book',
    'sync.emby': 'film',
    'sync.douban_movies': 'film',
    'user.film': 'film',
    'sync.safari_bookmarks': 'bookmark',
    'sync.chrome_bookmarks': 'bookmark',
    'user.note': 'note',
    'file.upload': 'file',
}


def upgrade() -> None:
    op.add_column(
        'content_items',
        sa.Column('kind', sa.String(), nullable=False, server_default='article'),
    )

    whens = ' '.join(f"WHEN '{st}' THEN '{kind}'" for st, kind in _KIND_BY_SOURCE_TYPE.items())
    op.execute(f"""
        UPDATE content_items c
        SET kind = CASE s.source_type {whens} ELSE 'article' END
        FROM source_configs s
        WHERE s.id = c.source_id
    """)
    # 手动下载的视频挂在 user.note 数据源下（routes/video.py），按媒体项纠正
    op.execute("""
        UPDATE content_items c SET kind = 'video'
        WHERE c.kind = 'note'
          AND EXISTS (SELECT 1 FROM media_items m WHERE m.content_id = c.id AND m.media_type = 'video')
    """)

    op.create_index('ix_content_kind', 'content_items', ['kind'])
    op.create_index(
        'uq_content_film_external', 'content_items', ['external_id'],
        unique=True, postgresql_where=sa.text("kind = 'film'"),
    )


def downgrade() -> None:
    op.drop_index('uq_content_film_external', table_name='content_items')
    op.drop_index('ix_content_kind', table_name='content_items')
    op.drop_column('content_items', 'kind')
