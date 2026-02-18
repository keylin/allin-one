"""add chat_history to content_items

Revision ID: 2e52f6fbdf1d
Revises: c430089e799a
Create Date: 2026-02-19 01:12:13.395143

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e52f6fbdf1d'
down_revision: Union[str, Sequence[str], None] = 'c430089e799a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('content_items', sa.Column('chat_history', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_items', 'chat_history')
