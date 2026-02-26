"""move playback fields to media_items

Revision ID: 0015_move_playback_to_media_items
Revises: 9b5adeeead25
Create Date: 2026-02-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0015_move_playback_to_media_items'
down_revision: Union[str, Sequence[str], None] = '9b5adeeead25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new columns to media_items
    op.add_column('media_items', sa.Column('playback_position', sa.Integer(), server_default='0'))
    op.add_column('media_items', sa.Column('last_played_at', sa.DateTime(), nullable=True))

    # 2. Migrate data: copy playback_position/last_played_at from content_items
    #    to the first video or audio media_item for each content.
    #    Uses a lateral subquery to pick the first matching media_item per content.
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE media_items mi
        SET playback_position = ci.playback_position,
            last_played_at = ci.last_played_at
        FROM content_items ci
        WHERE mi.content_id = ci.id
          AND mi.media_type IN ('video', 'audio')
          AND ci.playback_position > 0
          AND mi.id = (
              SELECT m2.id FROM media_items m2
              WHERE m2.content_id = ci.id
                AND m2.media_type IN ('video', 'audio')
              ORDER BY m2.created_at ASC
              LIMIT 1
          )
    """))

    # 3. Drop old columns from content_items
    op.drop_column('content_items', 'playback_position')
    op.drop_column('content_items', 'last_played_at')


def downgrade() -> None:
    # 1. Re-add columns to content_items
    op.add_column('content_items', sa.Column('playback_position', sa.Integer(), server_default='0'))
    op.add_column('content_items', sa.Column('last_played_at', sa.DateTime(), nullable=True))

    # 2. Migrate data back: copy from first video/audio media_item to content_items
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE content_items ci
        SET playback_position = mi.playback_position,
            last_played_at = mi.last_played_at
        FROM media_items mi
        WHERE mi.content_id = ci.id
          AND mi.media_type IN ('video', 'audio')
          AND mi.playback_position > 0
          AND mi.id = (
              SELECT m2.id FROM media_items m2
              WHERE m2.content_id = ci.id
                AND m2.media_type IN ('video', 'audio')
              ORDER BY m2.created_at ASC
              LIMIT 1
          )
    """))

    # 3. Drop columns from media_items
    op.drop_column('media_items', 'last_played_at')
    op.drop_column('media_items', 'playback_position')
