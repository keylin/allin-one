"""add external_id and location to book_annotations, make cfi_range nullable

Revision ID: 0014_apple_books_sync
Revises: 0013_content_dedup
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_apple_books_sync"
down_revision = "0013_content_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add external_id column for external annotation dedup (e.g. Apple Books UUID)
    op.add_column(
        "book_annotations",
        sa.Column("external_id", sa.String(), nullable=True),
    )
    op.create_index("ix_annotation_external_id", "book_annotations", ["external_id"])

    # Add location column for external positioning info
    op.add_column(
        "book_annotations",
        sa.Column("location", sa.String(), nullable=True),
    )

    # Make cfi_range nullable (external annotations may not have EPUB CFI)
    op.alter_column(
        "book_annotations",
        "cfi_range",
        existing_type=sa.Text(),
        nullable=True,
    )

    # Partial unique constraint: (content_id, external_id) WHERE external_id IS NOT NULL
    op.execute(
        "CREATE UNIQUE INDEX uq_annotation_content_external "
        "ON book_annotations (content_id, external_id) "
        "WHERE external_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_annotation_content_external")
    op.alter_column(
        "book_annotations",
        "cfi_range",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("book_annotations", "location")
    op.drop_index("ix_annotation_external_id", table_name="book_annotations")
    op.drop_column("book_annotations", "external_id")
