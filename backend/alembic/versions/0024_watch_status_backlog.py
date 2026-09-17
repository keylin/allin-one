"""观影状态「没看过」(unseen) 改为「待看」(backlog)：进入观看流程，优先级低于想看

Revision ID: 0024_watch_status_backlog
Revises: 0023_watch_logs
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = '0024_watch_status_backlog'
down_revision: Union[str, Sequence[str], None] = '0023_watch_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE watch_records SET status = 'backlog' WHERE status = 'unseen'")


def downgrade() -> None:
    op.execute("UPDATE watch_records SET status = 'unseen' WHERE status = 'backlog'")
