"""add opened_at to content_items

首次打开详情时间，与 last_viewed_at（含滚动自动已读/批量已读）区分。

Revision ID: 0020_add_opened_at
Revises: 0019_text_to_jsonb
Create Date: 2026-09-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0020_add_opened_at'
down_revision: Union[str, Sequence[str], None] = '0019_text_to_jsonb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('content_items', sa.Column('opened_at', sa.DateTime(), nullable=True))
    op.create_index('ix_content_items_opened_at', 'content_items', ['opened_at'])


def downgrade() -> None:
    op.drop_index('ix_content_items_opened_at', table_name='content_items')
    op.drop_column('content_items', 'opened_at')
