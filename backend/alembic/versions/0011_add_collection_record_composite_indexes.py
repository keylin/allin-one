"""add composite indexes on collection_records for multi-column query patterns

Revision ID: 0011_add_colrec_composite_idx
Revises: 2e52f6fbdf1d
Create Date: 2026-02-21

典型高频查询覆盖:
- source_id = X ORDER BY started_at DESC LIMIT N
- source_id = X AND status IN (...) ORDER BY started_at DESC LIMIT N
- source_id = X AND status = 'completed' AND items_new > 0 ORDER BY started_at DESC LIMIT N
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_add_colrec_composite_idx"
down_revision = "2e52f6fbdf1d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_colrec_source_started",
        "collection_records",
        ["source_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_colrec_source_status_started",
        "collection_records",
        ["source_id", "status", sa.text("started_at DESC")],
    )


def downgrade():
    op.drop_index("ix_colrec_source_status_started", table_name="collection_records")
    op.drop_index("ix_colrec_source_started", table_name="collection_records")
