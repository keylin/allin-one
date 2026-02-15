"""dedup content_items by (source_id, url)

RSSHub guid 不稳定导致同一视频被重复入库。按 (source_id, url)
分组去重：保留最早的条目（优先保留有已下载 MediaItem 的），
将重复条目的 media_items 和 pipeline_executions 迁移到保留条目，
然后删除重复条目。

Revision ID: 0005_dedup_url
Revises: 322fb9be9b84
Create Date: 2026-02-15
"""
from alembic import op
from sqlalchemy import text

revision = "0005_dedup_url"
down_revision = "322fb9be9b84"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 找出所有 (source_id, url) 重复组
    dup_groups = conn.execute(
        text("""
            SELECT source_id, url
            FROM content_items
            WHERE source_id IS NOT NULL AND url IS NOT NULL AND url != ''
            GROUP BY source_id, url
            HAVING COUNT(*) > 1
        """)
    ).fetchall()

    if not dup_groups:
        return

    total_deleted = 0

    for source_id, url in dup_groups:
        # 取该组所有条目，优先保留有已下载视频的，其次保留最早创建的
        rows = conn.execute(
            text("""
                SELECT ci.id,
                       EXISTS(
                           SELECT 1 FROM media_items mi
                           WHERE mi.content_id = ci.id
                             AND mi.media_type = 'video'
                             AND mi.status = 'downloaded'
                       ) AS has_video
                FROM content_items ci
                WHERE ci.source_id = :source_id AND ci.url = :url
                ORDER BY has_video DESC, ci.created_at ASC
            """),
            {"source_id": source_id, "url": url},
        ).fetchall()

        keeper_id = rows[0][0]
        dup_ids = [r[0] for r in rows[1:]]

        if not dup_ids:
            continue

        # 将重复条目的 media_items 迁移到 keeper
        conn.execute(
            text("UPDATE media_items SET content_id = :keeper WHERE content_id = ANY(:dups)"),
            {"keeper": keeper_id, "dups": dup_ids},
        )

        # 将重复条目的 pipeline_executions 迁移到 keeper
        conn.execute(
            text("UPDATE pipeline_executions SET content_id = :keeper WHERE content_id = ANY(:dups)"),
            {"keeper": keeper_id, "dups": dup_ids},
        )

        # 删除重复条目
        conn.execute(
            text("DELETE FROM content_items WHERE id = ANY(:dups)"),
            {"dups": dup_ids},
        )

        total_deleted += len(dup_ids)

    if total_deleted:
        print(f"[dedup] Removed {total_deleted} duplicate content_items across {len(dup_groups)} groups")


def downgrade():
    # 数据迁移不可逆 — 重复数据已被清理
    pass
