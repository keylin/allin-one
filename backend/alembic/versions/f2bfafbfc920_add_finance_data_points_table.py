"""add finance_data_points table

Revision ID: f2bfafbfc920
Revises: 1d483cd21224
Create Date: 2026-02-12 23:34:45.342617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2bfafbfc920'
down_revision: Union[str, Sequence[str], None] = '1d483cd21224'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'finance_data_points',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('date_key', sa.String(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('volume', sa.Float(), nullable=True),
        sa.Column('unit_nav', sa.Float(), nullable=True),
        sa.Column('cumulative_nav', sa.Float(), nullable=True),
        sa.Column('alert_json', sa.Text(), nullable=True),
        sa.Column('analysis_result', sa.Text(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['source_configs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'date_key', name='uq_finance_source_date'),
    )
    op.create_index('ix_finance_source_date', 'finance_data_points', ['source_id', 'date_key'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_finance_source_date', table_name='finance_data_points')
    op.drop_table('finance_data_points')
