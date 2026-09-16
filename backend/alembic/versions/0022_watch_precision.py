"""watch_records: 看过日期精度（day / month / year；NULL = 时间不详）

Revision ID: 0022_watch_precision
Revises: 0021_add_watch_records
Create Date: 2026-09-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0022_watch_precision'
down_revision: Union[str, Sequence[str], None] = '0021_add_watch_records'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('watch_records') as batch:
        batch.add_column(sa.Column('watched_precision', sa.String(), nullable=True))
    # 既有日期都是精确到天的（Emby 播放日期 / 用户手填）
    op.execute("UPDATE watch_records SET watched_precision = 'day' WHERE watched_at IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table('watch_records') as batch:
        batch.drop_column('watched_precision')
