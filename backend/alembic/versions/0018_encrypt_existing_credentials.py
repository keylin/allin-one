"""encrypt existing credential data

Revision ID: 0018_encrypt_credentials
Revises: 0017_add_ondelete_fk
Create Date: 2026-02-28 10:01:00.000000

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0018_encrypt_credentials'
down_revision: Union[str, Sequence[str], None] = '0017_add_ondelete_fk'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        # 未配置密钥，跳过加密（现有数据保持明文）
        return

    from cryptography.fernet import Fernet
    f = Fernet(key.encode())

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, credential_data FROM platform_credentials")
    ).fetchall()

    for row in rows:
        cred_data = row[1]
        if not cred_data:
            continue
        # 跳过已加密的数据（Fernet token 以 gAAAAA 开头）
        if cred_data.startswith("gAAAAA"):
            continue
        encrypted = f.encrypt(cred_data.encode()).decode()
        conn.execute(
            sa.text(
                "UPDATE platform_credentials SET credential_data = :data WHERE id = :id"
            ),
            {"data": encrypted, "id": row[0]},
        )


def downgrade() -> None:
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        return

    from cryptography.fernet import Fernet
    f = Fernet(key.encode())

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, credential_data FROM platform_credentials")
    ).fetchall()

    for row in rows:
        cred_data = row[1]
        if not cred_data:
            continue
        if not cred_data.startswith("gAAAAA"):
            continue
        decrypted = f.decrypt(cred_data.encode()).decode()
        conn.execute(
            sa.text(
                "UPDATE platform_credentials SET credential_data = :data WHERE id = :id"
            ),
            {"data": decrypted, "id": row[0]},
        )
