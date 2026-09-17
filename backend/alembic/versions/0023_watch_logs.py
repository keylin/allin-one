"""watch_logs：一部片多条观看记录；watch_records.comment 与 content_items.user_note 迁入后废弃

Revision ID: 0023_watch_logs
Revises: 0022_watch_precision
Create Date: 2026-09-17

建表用 IF NOT EXISTS：应用启动的 create_all 可能已先建出该表（见 design_film_library.md §10）。
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0023_watch_logs'
down_revision: Union[str, Sequence[str], None] = '0022_watch_precision'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS watch_logs (
            id VARCHAR PRIMARY KEY,
            record_id VARCHAR NOT NULL REFERENCES watch_records(id) ON DELETE CASCADE,
            watched_at DATE,
            watched_precision VARCHAR,
            my_rating SMALLINT,
            note TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_watch_logs_record ON watch_logs (record_id)")

    # 数据迁移：每条「看过」或带评分/短评/长评的记录 → 一条观看记录（短评 + 长评合并为 note）
    conn = op.get_bind()
    rows = conn.execute(sa.text("""
        SELECT r.id, r.status, r.my_rating, r.watched_at, r.watched_precision, r.comment, c.user_note, r.created_at
        FROM watch_records r JOIN content_items c ON c.id = r.content_id
        WHERE NOT EXISTS (SELECT 1 FROM watch_logs l WHERE l.record_id = r.id)
          AND (r.status = 'watched' OR r.my_rating IS NOT NULL OR r.comment IS NOT NULL OR c.user_note IS NOT NULL)
    """)).fetchall()
    for r in rows:
        parts = [p.strip() for p in (r.comment, r.user_note) if p and p.strip()]
        note = "\n\n".join(parts) or None
        conn.execute(sa.text("""
            INSERT INTO watch_logs (id, record_id, watched_at, watched_precision, my_rating, note, created_at, updated_at)
            VALUES (:id, :rid, :wa, :wp, :rating, :note, COALESCE(:created, NOW()), NOW())
        """), {"id": uuid.uuid4().hex, "rid": r.id, "wa": r.watched_at, "wp": r.watched_precision,
               "rating": r.my_rating, "note": note, "created": r.created_at})
    conn.execute(sa.text("""
        UPDATE content_items SET user_note = NULL
        WHERE id IN (SELECT content_id FROM watch_records) AND user_note IS NOT NULL
    """))
    with op.batch_alter_table('watch_records') as batch:
        batch.drop_column('comment')


def downgrade() -> None:
    with op.batch_alter_table('watch_records') as batch:
        batch.add_column(sa.Column('comment', sa.Text(), nullable=True))
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE watch_records r SET comment = l.note
        FROM (SELECT DISTINCT ON (record_id) record_id, note FROM watch_logs
              ORDER BY record_id, watched_at DESC NULLS LAST, created_at DESC) l
        WHERE l.record_id = r.id
    """))
    op.drop_index('ix_watch_logs_record', table_name='watch_logs')
    op.drop_table('watch_logs')
