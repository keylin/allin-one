"""add favorited_at to content_items

Revision ID: c430089e799a
Revises: 0010_migrate_rsshub_routes
Create Date: 2026-02-19 00:02:17.740869

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c430089e799a'
down_revision: Union[str, Sequence[str], None] = '0010_migrate_rsshub_routes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('content_items', sa.Column('favorited_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('content_items', 'favorited_at')
