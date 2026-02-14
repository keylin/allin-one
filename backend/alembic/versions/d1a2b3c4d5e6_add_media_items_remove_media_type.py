"""add media_items table, remove media_type and pipeline_routing columns,
rename download_video -> localize_media

Revision ID: d1a2b3c4d5e6
Revises: c42709a2dffe
Create Date: 2026-02-14 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c42709a2dffe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create media_items table (skip if already exists via create_all)
    conn = op.get_bind()
    table_exists = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_items'")
    ).fetchone()
    if not table_exists:
        op.create_table(
            'media_items',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('content_id', sa.String(), sa.ForeignKey('content_items.id'), nullable=False),
            sa.Column('media_type', sa.String(), nullable=False),
            sa.Column('original_url', sa.String(), nullable=False),
            sa.Column('local_path', sa.String(), nullable=True),
            sa.Column('filename', sa.String(), nullable=True),
            sa.Column('status', sa.String(), default='pending'),
            sa.Column('metadata_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_media_item_content_id', 'media_items', ['content_id'])

    # 2. Remove deprecated columns (SQLite requires batch mode)
    with op.batch_alter_table('source_configs') as batch_op:
        batch_op.drop_column('media_type')
        batch_op.drop_column('pipeline_routing')

    with op.batch_alter_table('content_items') as batch_op:
        batch_op.drop_column('media_type')

    # 3. Rename step_type: download_video -> localize_media
    #    and inject has_video=true into output_data for existing video steps
    conn.execute(
        sa.text(
            "UPDATE pipeline_steps SET step_type = 'localize_media' "
            "WHERE step_type = 'download_video'"
        )
    )

    # Add has_video to output_data of migrated steps
    rows = conn.execute(
        sa.text(
            "SELECT id, output_data FROM pipeline_steps "
            "WHERE step_type = 'localize_media' AND output_data IS NOT NULL"
        )
    ).fetchall()
    for row_id, output_data in rows:
        try:
            data = json.loads(output_data)
            if "has_video" not in data:
                data["has_video"] = True
                conn.execute(
                    sa.text(
                        "UPDATE pipeline_steps SET output_data = :data WHERE id = :id"
                    ),
                    {"data": json.dumps(data, ensure_ascii=False), "id": row_id},
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # 4. Update pipeline template steps_config: download_video -> localize_media
    tmpl_rows = conn.execute(
        sa.text(
            "SELECT id, steps_config FROM pipeline_templates "
            "WHERE steps_config LIKE '%download_video%'"
        )
    ).fetchall()
    for tmpl_id, steps_config in tmpl_rows:
        new_config = steps_config.replace('"download_video"', '"localize_media"')
        conn.execute(
            sa.text(
                "UPDATE pipeline_templates SET steps_config = :config WHERE id = :id"
            ),
            {"config": new_config, "id": tmpl_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Rename step_type back
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE pipeline_steps SET step_type = 'download_video' "
            "WHERE step_type = 'localize_media'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE pipeline_templates SET steps_config = "
            "REPLACE(steps_config, '\"localize_media\"', '\"download_video\"') "
            "WHERE steps_config LIKE '%localize_media%'"
        )
    )

    # Re-add removed columns
    with op.batch_alter_table('content_items') as batch_op:
        batch_op.add_column(sa.Column('media_type', sa.String(), default='text'))

    with op.batch_alter_table('source_configs') as batch_op:
        batch_op.add_column(sa.Column('pipeline_routing', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('media_type', sa.String(), default='text'))

    # Drop media_items table
    op.drop_index('ix_media_item_content_id', 'media_items')
    op.drop_table('media_items')
