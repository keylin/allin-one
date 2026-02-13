"""add FK indexes for query performance

Revision ID: b8e3a1f42c90
Revises: f2bfafbfc920
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b8e3a1f42c90'
down_revision: Union[str, Sequence[str], None] = 'f2bfafbfc920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_content_items_source_id', 'content_items', ['source_id'])
    op.create_index('ix_pipeline_executions_content_id', 'pipeline_executions', ['content_id'])
    op.create_index('ix_pipeline_executions_source_id', 'pipeline_executions', ['source_id'])
    op.create_index('ix_pipeline_executions_template_id', 'pipeline_executions', ['template_id'])
    op.create_index('ix_pipeline_steps_pipeline_id', 'pipeline_steps', ['pipeline_id'])
    op.create_index('ix_collection_records_source_id', 'collection_records', ['source_id'])


def downgrade() -> None:
    op.drop_index('ix_collection_records_source_id', 'collection_records')
    op.drop_index('ix_pipeline_steps_pipeline_id', 'pipeline_steps')
    op.drop_index('ix_pipeline_executions_template_id', 'pipeline_executions')
    op.drop_index('ix_pipeline_executions_source_id', 'pipeline_executions')
    op.drop_index('ix_pipeline_executions_content_id', 'pipeline_executions')
    op.drop_index('ix_content_items_source_id', 'content_items')
