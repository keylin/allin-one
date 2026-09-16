"""add watch_records (影视资料库用户标记)

Revision ID: 0021_add_watch_records
Revises: 0020_add_opened_at
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0021_add_watch_records'
down_revision: Union[str, Sequence[str], None] = '0020_add_opened_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'watch_records',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('content_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='unmarked'),
        sa.Column('my_rating', sa.SmallInteger(), nullable=True),
        sa.Column('watched_at', sa.Date(), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('status_source', sa.String(), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['content_id'], ['content_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_watch_records_content', 'watch_records', ['content_id'], unique=True)
    op.create_index('ix_watch_records_status', 'watch_records', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_watch_records_status', table_name='watch_records')
    op.drop_index('uq_watch_records_content', table_name='watch_records')
    op.drop_table('watch_records')
