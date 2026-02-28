"""add ondelete to foreign keys

Revision ID: 0017_add_ondelete_fk
Revises: 0016_add_favorited_to_media
Create Date: 2026-02-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0017_add_ondelete_fk'
down_revision: Union[str, Sequence[str], None] = '0016_add_favorited_to_media'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, constraint_name, column, ref_table.ref_column, ondelete)
_FK_CHANGES = [
    # CASCADE — child must be deleted with parent
    ("media_items", "media_items_content_id_fkey",
     "content_id", "content_items.id", "CASCADE"),
    ("pipeline_executions", "pipeline_executions_content_id_fkey",
     "content_id", "content_items.id", "CASCADE"),
    ("pipeline_steps", "pipeline_steps_pipeline_id_fkey",
     "pipeline_id", "pipeline_executions.id", "CASCADE"),
    ("collection_records", "collection_records_source_id_fkey",
     "source_id", "source_configs.id", "CASCADE"),
    ("finance_data_points", "finance_data_points_source_id_fkey",
     "source_id", "source_configs.id", "CASCADE"),
    # SET NULL — nullable reference, keep row but clear FK
    ("pipeline_executions", "pipeline_executions_source_id_fkey",
     "source_id", "source_configs.id", "SET NULL"),
    ("pipeline_executions", "pipeline_executions_template_id_fkey",
     "template_id", "pipeline_templates.id", "SET NULL"),
    ("source_configs", "source_configs_pipeline_template_id_fkey",
     "pipeline_template_id", "pipeline_templates.id", "SET NULL"),
    ("source_configs", "source_configs_credential_id_fkey",
     "credential_id", "platform_credentials.id", "SET NULL"),
]


def upgrade() -> None:
    for table, constraint, column, referent, ondelete in _FK_CHANGES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, referent.split(".")[0],
            [column], [referent.split(".")[1]],
            ondelete=ondelete,
        )


def downgrade() -> None:
    for table, constraint, column, referent, _ondelete in _FK_CHANGES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, referent.split(".")[0],
            [column], [referent.split(".")[1]],
        )
