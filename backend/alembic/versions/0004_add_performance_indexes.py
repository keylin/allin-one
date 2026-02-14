"""add performance indexes for common query patterns

After migrating from SQLite to PostgreSQL, queries that were fast on
small SQLite datasets now require proper indexes.  This migration adds
indexes on the most frequently filtered / sorted / joined columns.

Revision ID: 0004_perf_idx
Revises: 0003_fix_tz
Create Date: 2026-02-14
"""
from alembic import op

revision = "0004_perf_idx"
down_revision = "0003_fix_tz"
branch_labels = None
depends_on = None


def upgrade():
    # ---- content_items ----
    op.create_index("ix_content_source_id", "content_items", ["source_id"])
    op.create_index("ix_content_status", "content_items", ["status"])
    op.create_index("ix_content_collected_at", "content_items", ["collected_at"])
    op.create_index("ix_content_is_favorited", "content_items", ["is_favorited"])
    # 复合索引: 列表页按 source + status 筛选后按 collected_at 排序
    op.create_index(
        "ix_content_source_status_collected",
        "content_items",
        ["source_id", "status", "collected_at"],
    )
    # 去重查询用到 url + created_at
    op.create_index("ix_content_url", "content_items", ["url"])

    # ---- pipeline_executions ----
    op.create_index("ix_pexec_content_id", "pipeline_executions", ["content_id"])
    op.create_index("ix_pexec_status", "pipeline_executions", ["status"])
    op.create_index("ix_pexec_source_id", "pipeline_executions", ["source_id"])
    op.create_index("ix_pexec_created_at", "pipeline_executions", ["created_at"])

    # ---- pipeline_steps ----
    op.create_index("ix_pstep_pipeline_id", "pipeline_steps", ["pipeline_id"])
    op.create_index("ix_pstep_status", "pipeline_steps", ["status"])

    # ---- media_items ----
    op.create_index("ix_media_media_type", "media_items", ["media_type"])
    op.create_index("ix_media_status", "media_items", ["status"])

    # ---- collection_records ----
    op.create_index("ix_colrec_source_id", "collection_records", ["source_id"])


def downgrade():
    op.drop_index("ix_colrec_source_id", table_name="collection_records")
    op.drop_index("ix_media_status", table_name="media_items")
    op.drop_index("ix_media_media_type", table_name="media_items")
    op.drop_index("ix_pstep_status", table_name="pipeline_steps")
    op.drop_index("ix_pstep_pipeline_id", table_name="pipeline_steps")
    op.drop_index("ix_pexec_created_at", table_name="pipeline_executions")
    op.drop_index("ix_pexec_source_id", table_name="pipeline_executions")
    op.drop_index("ix_pexec_status", table_name="pipeline_executions")
    op.drop_index("ix_pexec_content_id", table_name="pipeline_executions")
    op.drop_index("ix_content_url", table_name="content_items")
    op.drop_index("ix_content_source_status_collected", table_name="content_items")
    op.drop_index("ix_content_is_favorited", table_name="content_items")
    op.drop_index("ix_content_collected_at", table_name="content_items")
    op.drop_index("ix_content_status", table_name="content_items")
    op.drop_index("ix_content_source_id", table_name="content_items")
