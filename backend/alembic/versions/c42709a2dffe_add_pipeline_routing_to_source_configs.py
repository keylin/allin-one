"""add_pipeline_routing_to_source_configs

Revision ID: c42709a2dffe
Revises: ad308b3ef8f4
Create Date: 2026-02-13 23:48:22.960549

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c42709a2dffe'
down_revision: Union[str, Sequence[str], None] = 'ad308b3ef8f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_configs', sa.Column('pipeline_routing', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('source_configs', 'pipeline_routing')
