"""add_source_retention_fields

Revision ID: ad308b3ef8f4
Revises: c52de1146cf4
Create Date: 2026-02-13 22:48:30.468931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad308b3ef8f4'
down_revision: Union[str, Sequence[str], None] = 'c52de1146cf4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_configs', sa.Column('auto_cleanup_enabled', sa.Boolean(), server_default=sa.text('0'), nullable=True))
    op.add_column('source_configs', sa.Column('retention_days', sa.Integer(), nullable=True))
    # Backfill existing rows
    op.execute('UPDATE source_configs SET auto_cleanup_enabled = 0 WHERE auto_cleanup_enabled IS NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('source_configs', 'retention_days')
    op.drop_column('source_configs', 'auto_cleanup_enabled')
