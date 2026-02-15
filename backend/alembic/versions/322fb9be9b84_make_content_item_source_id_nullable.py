"""make content_item source_id nullable

Revision ID: 322fb9be9b84
Revises: 0004_perf_idx
Create Date: 2026-02-15 08:57:49.276053

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '322fb9be9b84'
down_revision: Union[str, Sequence[str], None] = '0004_perf_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """允许 content_items.source_id 为 NULL，删除数据源时可保留内容"""
    op.alter_column('content_items', 'source_id',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.drop_constraint('content_items_source_id_fkey', 'content_items', type_='foreignkey')
    op.create_foreign_key(
        'content_items_source_id_fkey', 'content_items', 'source_configs',
        ['source_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """恢复 source_id NOT NULL 约束"""
    op.drop_constraint('content_items_source_id_fkey', 'content_items', type_='foreignkey')
    op.create_foreign_key(
        'content_items_source_id_fkey', 'content_items', 'source_configs',
        ['source_id'], ['id'],
    )
    op.alter_column('content_items', 'source_id',
               existing_type=sa.VARCHAR(),
               nullable=False)
