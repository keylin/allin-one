"""重算所有 ContentItem 的 title_hash

归一化算法升级后需要重算，否则新旧 hash 不可比。
同时重新扫描去重关系。

用法:
    cd backend && python -m scripts.migration.rehash_title_dedup
    或:
    cd backend && python ../scripts/migration/rehash_title_dedup.py
"""

import sys
from pathlib import Path

# 确保 backend 在 sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal
from app.models.content import ContentItem
from app.services.dedup import compute_title_hash, hamming_distance, DEFAULT_THRESHOLD


def main():
    with SessionLocal() as db:
        # 1. 重算所有 title_hash
        items = db.query(ContentItem).filter(ContentItem.title.isnot(None)).all()
        print(f"共 {len(items)} 条内容，开始重算 title_hash ...")

        updated = 0
        for item in items:
            new_hash = compute_title_hash(item.title)
            if new_hash != item.title_hash:
                item.title_hash = new_hash
                updated += 1

        db.flush()
        print(f"更新了 {updated} 条 title_hash")

        # 2. 清除旧的去重标记，重新扫描
        cleared = db.query(ContentItem).filter(
            ContentItem.duplicate_of_id.isnot(None)
        ).update({"duplicate_of_id": None})
        db.flush()
        print(f"清除了 {cleared} 条旧去重标记，开始重新扫描 ...")

        # 3. 按采集时间排序，逐条扫描去重
        all_items = (
            db.query(ContentItem)
            .filter(ContentItem.title_hash.isnot(None))
            .order_by(ContentItem.collected_at.asc())
            .all()
        )

        # 构建已见原件列表，仅保留最近 5000 条（与生产代码 find_similar_content 行为一致）
        MAX_ORIGINALS = 5000
        originals = []
        duplicates_found = 0

        for item in all_items:
            found = False
            for orig in originals:
                if orig.source_id == item.source_id:
                    continue  # 同源跳过
                dist = hamming_distance(item.title_hash, orig.title_hash)
                if dist <= DEFAULT_THRESHOLD:
                    item.duplicate_of_id = orig.id
                    duplicates_found += 1
                    found = True
                    break

            if not found:
                originals.append(item)
                if len(originals) > MAX_ORIGINALS:
                    originals = originals[-MAX_ORIGINALS:]

        db.commit()
        print(f"重新扫描完成，标记 {duplicates_found} 条为重复")


if __name__ == "__main__":
    main()
