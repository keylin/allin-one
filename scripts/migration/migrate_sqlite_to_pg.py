#!/usr/bin/env python3
"""SQLite → PostgreSQL 数据迁移脚本

用法:
    python scripts/migrate_sqlite_to_pg.py [--sqlite PATH] [--pg-url URL]

默认:
    --sqlite  data/db/allin.db
    --pg-url  postgresql://allinone:allinone@localhost:5432/allinone

步骤:
    1. 连接 SQLite (只读) 和 PG (读写)
    2. 按外键依赖顺序导出所有表
    3. 逐行 INSERT (自动处理类型转换)
    4. 验证行数一致
    5. 输出迁移报告
"""

import argparse
import sqlite3
import sys
from contextlib import contextmanager

from sqlalchemy import create_engine, text, inspect


# 表导入顺序 — 按外键依赖排序 (无依赖的先导入)
TABLE_ORDER = [
    "system_settings",
    "prompt_templates",
    "pipeline_templates",
    "platform_credentials",
    "source_configs",
    "content_items",
    "collection_records",
    "finance_data_points",
    "media_items",
    "pipeline_executions",
    "pipeline_steps",
]


def get_sqlite_tables(sqlite_path: str) -> dict[str, list[str]]:
    """获取 SQLite 中每张表的列名"""
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = {}
    for table in TABLE_ORDER:
        try:
            cursor.execute(f"SELECT * FROM {table} LIMIT 0")
            tables[table] = [desc[0] for desc in cursor.description]
        except sqlite3.OperationalError:
            print(f"  [SKIP] Table '{table}' not found in SQLite")
    conn.close()
    return tables


def migrate_table(sqlite_path: str, pg_engine, table: str, columns: list[str]) -> int:
    """迁移单张表的数据"""
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    total = cursor.fetchone()[0]

    if total == 0:
        conn.close()
        return 0

    cursor.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()

    # 获取 PG 表中实际存在的列和类型
    pg_inspector = inspect(pg_engine)
    pg_col_info = {col["name"]: col for col in pg_inspector.get_columns(table)}
    common_columns = [c for c in columns if c in pg_col_info]

    if not common_columns:
        print(f"  [WARN] No common columns for '{table}', skipping")
        conn.close()
        return 0

    # 找出 boolean 列 (SQLite 存为 0/1, PG 需要 True/False)
    import sqlalchemy
    bool_columns = set()
    for c in common_columns:
        col_type = pg_col_info[c].get("type")
        if isinstance(col_type, sqlalchemy.Boolean):
            bool_columns.add(c)

    placeholders = ", ".join([f":{c}" for c in common_columns])
    col_names = ", ".join([f'"{c}"' for c in common_columns])
    insert_sql = text(f'INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING')

    inserted = 0
    batch_size = 500

    with pg_engine.begin() as pg_conn:
        batch = []
        for row in rows:
            row_dict = {c: row[c] for c in common_columns}
            # Convert SQLite integer booleans to Python bool
            for bc in bool_columns:
                v = row_dict.get(bc)
                if v is not None:
                    row_dict[bc] = bool(v)
            batch.append(row_dict)

            if len(batch) >= batch_size:
                pg_conn.execute(insert_sql, batch)
                inserted += len(batch)
                batch = []

        if batch:
            pg_conn.execute(insert_sql, batch)
            inserted += len(batch)

    conn.close()
    return inserted


def verify_counts(sqlite_path: str, pg_engine, tables: dict) -> list[tuple[str, int, int]]:
    """验证两端行数"""
    results = []
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    cursor = conn.cursor()

    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        sqlite_count = cursor.fetchone()[0]

        with pg_engine.connect() as pg_conn:
            pg_count = pg_conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        results.append((table, sqlite_count, pg_count))

    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite", default="data/db/allin.db", help="SQLite database path")
    parser.add_argument("--pg-url", default="postgresql://allinone:allinone@localhost:5432/allinone",
                        help="PostgreSQL connection URL")
    args = parser.parse_args()

    print(f"=== SQLite → PostgreSQL Migration ===")
    print(f"  SQLite: {args.sqlite}")
    print(f"  PG URL: {args.pg_url}")
    print()

    # 1. Discover tables
    print("[1/3] Discovering SQLite tables...")
    tables = get_sqlite_tables(args.sqlite)
    print(f"  Found {len(tables)} tables: {', '.join(tables.keys())}")
    print()

    # 2. Migrate data
    print("[2/3] Migrating data...")
    pg_engine = create_engine(args.pg_url)

    for table, columns in tables.items():
        count = migrate_table(args.sqlite, pg_engine, table, columns)
        print(f"  {table}: {count} rows migrated")

    print()

    # 3. Verify
    print("[3/3] Verifying row counts...")
    results = verify_counts(args.sqlite, pg_engine, tables)

    all_ok = True
    for table, sqlite_count, pg_count in results:
        status = "OK" if pg_count >= sqlite_count else "MISMATCH"
        if status == "MISMATCH":
            all_ok = False
        print(f"  {table}: SQLite={sqlite_count}, PG={pg_count} [{status}]")

    print()
    if all_ok:
        print("Migration completed successfully!")
    else:
        print("WARNING: Some tables have row count mismatches.")
        print("This may be expected if ON CONFLICT DO NOTHING skipped duplicates.")
        sys.exit(1)

    pg_engine.dispose()


if __name__ == "__main__":
    main()
