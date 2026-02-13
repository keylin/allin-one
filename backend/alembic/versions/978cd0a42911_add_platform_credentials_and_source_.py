"""add platform_credentials and source credential_id

Revision ID: 978cd0a42911
Revises: b8e3a1f42c90
Create Date: 2026-02-13 10:46:45.451367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '978cd0a42911'
down_revision: Union[str, Sequence[str], None] = 'b8e3a1f42c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    # init_db() may have already created the table via create_all
    tables = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='platform_credentials'"
    )).fetchall()
    if not tables:
        op.create_table(
            'platform_credentials',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('platform', sa.String(), nullable=False),
            sa.Column('credential_type', sa.String(), nullable=True),
            sa.Column('credential_data', sa.Text(), nullable=False),
            sa.Column('display_name', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('extra_info', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
    # create index if not exists
    indexes = conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_credential_platform'"
    )).fetchall()
    if not indexes:
        op.create_index('ix_credential_platform', 'platform_credentials', ['platform'], unique=False)

    # Add credential_id column if not exists
    cols = [r[1] for r in conn.execute(sa.text("PRAGMA table_info('source_configs')")).fetchall()]
    if 'credential_id' not in cols:
        op.add_column('source_configs', sa.Column('credential_id', sa.String(), nullable=True))
        op.create_index('ix_source_credential_id', 'source_configs', ['credential_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_source_credential_id', 'source_configs', type_='foreignkey')
    op.drop_index('ix_source_credential_id', table_name='source_configs')
    op.drop_column('source_configs', 'credential_id')
    op.drop_index('ix_credential_platform', table_name='platform_credentials')
    op.drop_table('platform_credentials')
