"""Text columns → JSONB for JSON data

Revision ID: 0019_text_to_jsonb
Revises: 0018_encrypt_credentials
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0019_text_to_jsonb'
down_revision: Union[str, Sequence[str], None] = '0018_encrypt_credentials'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All (table, column) pairs to migrate from Text to JSONB
_COLUMNS = [
    ("source_configs", "config_json"),
    ("source_configs", "periodicity_data"),
    ("content_items", "raw_data"),
    ("content_items", "analysis_result"),
    ("content_items", "chat_history"),
    ("pipeline_templates", "steps_config"),
    ("pipeline_steps", "step_config"),
    ("pipeline_steps", "input_data"),
    ("pipeline_steps", "output_data"),
    ("media_items", "metadata_json"),
    ("platform_credentials", "extra_info"),
    ("sync_task_progress", "result_data"),
    ("sync_task_progress", "options_json"),
    ("finance_data_points", "alert_json"),
    ("finance_data_points", "analysis_result"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        # NULLIF handles empty strings → NULL before cast
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE JSONB '
            f'USING NULLIF({column}, \'\')::jsonb'
        )

    # Add GIN index on analysis_result for tag queries
    op.create_index(
        "ix_content_analysis_gin",
        "content_items",
        ["analysis_result"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_content_analysis_gin", table_name="content_items")

    for table, column in _COLUMNS:
        op.execute(
            f'ALTER TABLE {table} '
            f'ALTER COLUMN {column} TYPE TEXT '
            f'USING {column}::text'
        )
