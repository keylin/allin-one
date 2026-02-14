"""remove miniflux source type

Revision ID: 0002_rm_miniflux
Revises: 0001_initial_pg
Create Date: 2026-02-14
"""
from alembic import op
import sqlalchemy as sa
import json

# revision identifiers, used by Alembic.
revision = "0002_rm_miniflux"
down_revision = "0001_initial_pg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert rss.miniflux sources to rss.standard
    conn = op.get_bind()

    # Update source_type
    conn.execute(
        sa.text(
            "UPDATE source_configs SET source_type = 'rss.standard' "
            "WHERE source_type = 'rss.miniflux'"
        )
    )

    # Remove miniflux_feed_id from config_json
    rows = conn.execute(
        sa.text(
            "SELECT id, config_json FROM source_configs "
            "WHERE config_json LIKE '%miniflux_feed_id%'"
        )
    ).fetchall()

    for row in rows:
        try:
            config = json.loads(row[1]) if row[1] else {}
            config.pop("miniflux_feed_id", None)
            new_config = json.dumps(config, ensure_ascii=False) if config else None
            conn.execute(
                sa.text("UPDATE source_configs SET config_json = :config WHERE id = :id"),
                {"config": new_config, "id": row[0]},
            )
        except (json.JSONDecodeError, TypeError):
            pass


def downgrade() -> None:
    # No-op: can't restore miniflux_feed_id values
    pass
