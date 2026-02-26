"""add sync_task_progress

Revision ID: 9b5adeeead25
Revises: 0014_apple_books_sync
Create Date: 2026-02-25 21:01:35.015478

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9b5adeeead25'
down_revision: Union[str, Sequence[str], None] = '0014_apple_books_sync'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    if conn.dialect.has_table(conn, 'sync_task_progress'):
        return
    op.create_table('sync_task_progress',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('phase', sa.String(), nullable=True),
        sa.Column('message', sa.String(), nullable=True),
        sa.Column('current', sa.Integer(), nullable=True),
        sa.Column('total', sa.Integer(), nullable=True),
        sa.Column('result_data', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('options_json', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['source_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_progress_source_status', 'sync_task_progress', ['source_id', 'status'], unique=False)
    op.create_index('ix_sync_progress_created', 'sync_task_progress', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_sync_progress_created', table_name='sync_task_progress')
    op.drop_index('ix_sync_progress_source_status', table_name='sync_task_progress')
    op.drop_table('sync_task_progress')
