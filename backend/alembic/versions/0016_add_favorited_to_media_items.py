"""add is_favorited and favorited_at to media_items

Revision ID: 0016_add_favorited_to_media
Revises: 0015_mv_playback_to_media
Create Date: 2026-02-26 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0016_add_favorited_to_media'
down_revision: Union[str, Sequence[str], None] = '0015_mv_playback_to_media'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('media_items', sa.Column('is_favorited', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('media_items', sa.Column('favorited_at', sa.DateTime(), nullable=True))

    # 回填：已收藏的 ContentItem，其所有 MediaItem 一并标记
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE media_items mi
        SET is_favorited = true,
            favorited_at = ci.favorited_at
        FROM content_items ci
        WHERE mi.content_id = ci.id AND ci.is_favorited = true
    """))


def downgrade() -> None:
    op.drop_column('media_items', 'favorited_at')
    op.drop_column('media_items', 'is_favorited')
