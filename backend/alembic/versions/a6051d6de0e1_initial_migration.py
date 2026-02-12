"""Initial migration

Revision ID: a6051d6de0e1
Revises:
Create Date: 2026-02-12 00:55:02.531189

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6051d6de0e1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pipeline_templates',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('steps_config', sa.Text(), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'source_configs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('source_type', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('media_type', sa.String(), server_default='text', nullable=True),
        sa.Column('schedule_enabled', sa.Boolean(), server_default='1', nullable=True),
        sa.Column('schedule_interval', sa.Integer(), server_default='3600', nullable=True),
        sa.Column('pipeline_template_id', sa.String(), sa.ForeignKey('pipeline_templates.id'), nullable=True),
        sa.Column('config_json', sa.Text(), nullable=True),
        sa.Column('last_collected_at', sa.DateTime(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'content_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('source_id', sa.String(), sa.ForeignKey('source_configs.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('author', sa.String(), nullable=True),
        sa.Column('raw_data', sa.Text(), nullable=True),
        sa.Column('processed_content', sa.Text(), nullable=True),
        sa.Column('analysis_result', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=True),
        sa.Column('media_type', sa.String(), server_default='text', nullable=True),
        sa.Column('language', sa.String(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('is_favorited', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('user_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('source_id', 'external_id', name='uq_source_external'),
    )

    op.create_table(
        'pipeline_executions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('content_id', sa.String(), sa.ForeignKey('content_items.id'), nullable=False),
        sa.Column('source_id', sa.String(), sa.ForeignKey('source_configs.id'), nullable=True),
        sa.Column('template_id', sa.String(), sa.ForeignKey('pipeline_templates.id'), nullable=True),
        sa.Column('template_name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=True),
        sa.Column('current_step', sa.Integer(), server_default='0', nullable=True),
        sa.Column('total_steps', sa.Integer(), server_default='0', nullable=True),
        sa.Column('trigger_source', sa.String(), server_default='manual', nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'pipeline_steps',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('pipeline_id', sa.String(), sa.ForeignKey('pipeline_executions.id'), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False),
        sa.Column('step_type', sa.String(), nullable=False),
        sa.Column('step_config', sa.Text(), nullable=True),
        sa.Column('is_critical', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('status', sa.String(), server_default='pending', nullable=True),
        sa.Column('input_data', sa.Text(), nullable=True),
        sa.Column('output_data', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('template_type', sa.String(), server_default='news_analysis', nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('user_prompt', sa.Text(), nullable=False),
        sa.Column('output_format', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'collection_records',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('source_id', sa.String(), sa.ForeignKey('source_configs.id'), nullable=False),
        sa.Column('status', sa.String(), server_default='running', nullable=True),
        sa.Column('items_found', sa.Integer(), server_default='0', nullable=True),
        sa.Column('items_new', sa.Integer(), server_default='0', nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('collection_records')
    op.drop_table('pipeline_steps')
    op.drop_table('pipeline_executions')
    op.drop_table('content_items')
    op.drop_table('source_configs')
    op.drop_table('pipeline_templates')
    op.drop_table('prompt_templates')
    op.drop_table('system_settings')
