"""add title_hash and duplicate_of_id to content_items for similarity dedup

Revision ID: 0013_content_dedup
Revises: 0012_add_ebook_tables
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_content_dedup"
down_revision = "0012_add_ebook_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("title_hash", sa.BigInteger(), nullable=True))
    op.add_column(
        "content_items",
        sa.Column(
            "duplicate_of_id",
            sa.String(),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_content_title_hash", "content_items", ["title_hash"])
    op.create_index("ix_content_duplicate_of", "content_items", ["duplicate_of_id"])


def downgrade() -> None:
    op.drop_index("ix_content_duplicate_of", table_name="content_items")
    op.drop_index("ix_content_title_hash", table_name="content_items")
    op.drop_column("content_items", "duplicate_of_id")
    op.drop_column("content_items", "title_hash")
