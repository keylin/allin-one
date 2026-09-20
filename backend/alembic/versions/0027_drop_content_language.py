"""删除死列 content_items.language

0001 建出、模型里早已没有的列：全表皆 NULL，ORM 不读不写，响应 Schema 里的同名字段因此恒为 None。
电子书的语言实际存在 raw_data["language"]，与此列无关。见审计 §4 🟡「模型 vs 库」。

Revision ID: 0027_drop_content_language
Revises: 0026_purge_fake_collect
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0027_drop_content_language'
down_revision: Union[str, Sequence[str], None] = '0026_purge_fake_collect'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE content_items DROP COLUMN IF EXISTS language")


def downgrade() -> None:
    op.add_column('content_items', sa.Column('language', sa.String(), nullable=True))
