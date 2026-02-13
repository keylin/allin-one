"""migrate bilibili cookies to platform_credentials

Extract cookie values from source_configs.config_json for bilibili sources,
create PlatformCredential rows (de-duplicated by cookie value),
and set credential_id on the source.

Revision ID: c52de1146cf4
Revises: 978cd0a42911
Create Date: 2026-02-13 10:54:52.804086

"""
import json
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c52de1146cf4'
down_revision: Union[str, Sequence[str], None] = '978cd0a42911'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate bilibili cookies from config_json to platform_credentials."""
    conn = op.get_bind()

    # Find bilibili sources with cookies in config_json
    rows = conn.execute(sa.text(
        "SELECT id, name, config_json FROM source_configs "
        "WHERE source_type = 'account.bilibili' AND config_json IS NOT NULL"
    )).fetchall()

    if not rows:
        return

    # De-duplicate by cookie value
    cookie_to_cred_id = {}  # cookie_str -> credential_id
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        source_id, source_name, config_json_str = row
        try:
            config = json.loads(config_json_str)
        except (json.JSONDecodeError, TypeError):
            continue

        cookie = config.get("cookie")
        if not cookie:
            continue

        if cookie not in cookie_to_cred_id:
            # Create new credential
            cred_id = uuid.uuid4().hex
            conn.execute(sa.text(
                "INSERT INTO platform_credentials (id, platform, credential_type, credential_data, display_name, status, created_at, updated_at) "
                "VALUES (:id, :platform, :ctype, :cdata, :dname, :status, :created, :updated)"
            ), {
                "id": cred_id,
                "platform": "bilibili",
                "ctype": "cookie",
                "cdata": cookie,
                "dname": f"B站账号 (迁移自 {source_name})",
                "status": "active",
                "created": now,
                "updated": now,
            })
            cookie_to_cred_id[cookie] = cred_id

        cred_id = cookie_to_cred_id[cookie]

        # Set credential_id on source
        conn.execute(sa.text(
            "UPDATE source_configs SET credential_id = :cred_id WHERE id = :source_id"
        ), {"cred_id": cred_id, "source_id": source_id})

        # Remove cookie from config_json
        del config["cookie"]
        new_config = json.dumps(config, ensure_ascii=False) if config else None
        conn.execute(sa.text(
            "UPDATE source_configs SET config_json = :cfg WHERE id = :source_id"
        ), {"cfg": new_config, "source_id": source_id})


def downgrade() -> None:
    """Move cookies back from platform_credentials to config_json."""
    conn = op.get_bind()

    # Find sources with credential_id
    rows = conn.execute(sa.text(
        "SELECT sc.id, sc.config_json, pc.credential_data "
        "FROM source_configs sc "
        "JOIN platform_credentials pc ON sc.credential_id = pc.id "
        "WHERE sc.source_type = 'account.bilibili'"
    )).fetchall()

    for source_id, config_json_str, cookie in rows:
        try:
            config = json.loads(config_json_str or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}
        config["cookie"] = cookie
        conn.execute(sa.text(
            "UPDATE source_configs SET config_json = :cfg, credential_id = NULL WHERE id = :source_id"
        ), {"cfg": json.dumps(config, ensure_ascii=False), "source_id": source_id})

    # Delete all migrated credentials
    conn.execute(sa.text(
        "DELETE FROM platform_credentials WHERE display_name LIKE '%迁移自%'"
    ))
