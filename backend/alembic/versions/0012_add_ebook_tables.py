"""add ebook reader tables (reading_progress, book_annotations, book_bookmarks)

Revision ID: 0012_add_ebook_tables
Revises: 0011_add_colrec_composite_idx
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_add_ebook_tables"
down_revision = "0011_add_colrec_composite_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # reading_progress — 每本电子书一条阅读进度
    op.create_table(
        "reading_progress",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_id", sa.String(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cfi", sa.Text(), nullable=True),
        sa.Column("progress", sa.Float(), server_default="0"),
        sa.Column("section_index", sa.Integer(), server_default="0"),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_reading_progress_content", "reading_progress", ["content_id"], unique=True)

    # book_annotations — 批注/高亮
    op.create_table(
        "book_annotations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_id", sa.String(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cfi_range", sa.Text(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(), server_default="highlight"),
        sa.Column("color", sa.String(), server_default="yellow"),
        sa.Column("selected_text", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_annotation_content", "book_annotations", ["content_id"])

    # book_bookmarks — 书签
    op.create_table(
        "book_bookmarks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("content_id", sa.String(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cfi", sa.Text(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_bookmark_content", "book_bookmarks", ["content_id"])


def downgrade() -> None:
    op.drop_table("book_bookmarks")
    op.drop_table("book_annotations")
    op.drop_table("reading_progress")
