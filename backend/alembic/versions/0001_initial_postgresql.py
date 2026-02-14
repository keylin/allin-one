"""initial postgresql

Revision ID: 0001_initial_pg
Revises:
Create Date: 2026-02-14
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_pg"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # system_settings
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )

    # prompt_templates
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("template_type", sa.String(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # pipeline_templates
    op.create_table(
        "pipeline_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps_config", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # platform_credentials
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("credential_type", sa.String(), nullable=True),
        sa.Column("credential_data", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("extra_info", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credential_platform", "platform_credentials", ["platform"])

    # source_configs
    op.create_table(
        "source_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=True),
        sa.Column("schedule_interval", sa.Integer(), nullable=True),
        sa.Column("pipeline_template_id", sa.String(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("credential_id", sa.String(), nullable=True),
        sa.Column("auto_cleanup_enabled", sa.Boolean(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("last_collected_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["pipeline_template_id"], ["pipeline_templates.id"]),
        sa.ForeignKeyConstraint(["credential_id"], ["platform_credentials.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_credential_id", "source_configs", ["credential_id"])

    # content_items
    op.create_table(
        "content_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("raw_data", sa.Text(), nullable=True),
        sa.Column("processed_content", sa.Text(), nullable=True),
        sa.Column("analysis_result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("is_favorited", sa.Boolean(), nullable=True),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(), nullable=True),
        sa.Column("playback_position", sa.Integer(), nullable=True),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_source_external"),
    )

    # collection_records
    op.create_table(
        "collection_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("items_found", sa.Integer(), nullable=True),
        sa.Column("items_new", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # finance_data_points
    op.create_table(
        "finance_data_points",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("date_key", sa.String(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("unit_nav", sa.Float(), nullable=True),
        sa.Column("cumulative_nav", sa.Float(), nullable=True),
        sa.Column("alert_json", sa.Text(), nullable=True),
        sa.Column("analysis_result", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "date_key", name="uq_finance_source_date"),
    )
    op.create_index("ix_finance_source_date", "finance_data_points", ["source_id", "date_key"])

    # media_items
    op.create_table(
        "media_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("content_id", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("original_url", sa.String(), nullable=False),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_item_content_id", "media_items", ["content_id"])

    # pipeline_executions
    op.create_table(
        "pipeline_executions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("content_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("template_id", sa.String(), nullable=True),
        sa.Column("template_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("trigger_source", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["source_configs.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["pipeline_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # pipeline_steps
    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("pipeline_id", sa.String(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(), nullable=False),
        sa.Column("step_config", sa.Text(), nullable=True),
        sa.Column("is_critical", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("input_data", sa.Text(), nullable=True),
        sa.Column("output_data", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipeline_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("pipeline_steps")
    op.drop_table("pipeline_executions")
    op.drop_index("ix_media_item_content_id", table_name="media_items")
    op.drop_table("media_items")
    op.drop_index("ix_finance_source_date", table_name="finance_data_points")
    op.drop_table("finance_data_points")
    op.drop_table("collection_records")
    op.drop_table("content_items")
    op.drop_index("ix_source_credential_id", table_name="source_configs")
    op.drop_table("source_configs")
    op.drop_index("ix_credential_platform", table_name="platform_credentials")
    op.drop_table("platform_credentials")
    op.drop_table("pipeline_templates")
    op.drop_table("prompt_templates")
    op.drop_table("system_settings")
