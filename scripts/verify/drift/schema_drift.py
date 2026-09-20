"""模型 / 真实库 / 文档 三方漂移检查

2026-09 审计发现 docs/system_design.md 的表结构是手写的，与模型、真实库多处对不上
（sync_task_progress 几乎是另一张表、ER 图缺表、索引名不符……）。从此表结构文档由模型生成，
并用本脚本检查三方一致性。通常经同目录的 check.sh 调用。

用法（在装有后端依赖的环境里，工作目录为 backend/）:
  python schema_drift.py doc      # 由模型生成表结构 Markdown（不连库）
  python schema_drift.py check    # 模型 vs 真实库，有差异则退出码 1
"""

import sys

from sqlalchemy import inspect as sa_inspect

import app.models  # noqa: F401  注册全部模型
from app.core.database import Base

# 没被 app.models.__init__ 导入、但属于本应用的模型模块也要注册进来
for _mod in ("film", "ebook", "finance", "pipeline", "credential", "sync_progress",
             "system_setting", "prompt_template", "content"):
    __import__(f"app.models.{_mod}")

TABLE_NOTES = {
    "source_configs": "数据源配置。只描述「从哪来」；某种源类型能做什么由源类型注册表 `app/models/source_types.py` 决定。",
    "content_items": "内容项。信息流条目与资料库条目共用此表，领域身份看 `kind`（ContentKind）。",
    "collection_records": "采集型数据源的运行记录，同时是智能调度算法的输入。",
    "media_items": "内容关联的媒体项（一对多）。",
    "sync_task_progress": "同步的运行记录与进度通道：内置同步（手动 / 自动）与外部推送都写，`options_json._trigger` 区分。",
    "watch_records": "影视库：用户对一部影片的标记（与影片 1:1）。`my_rating` / `watched_at` 是最近一次观看记录的缓存。",
    "watch_logs": "影视库：一部影片的多次观看记录（日期 + 精度 / 评分 / 感想）。",
    "reading_progress": "电子书阅读进度（与书 1:1）。",
    "book_annotations": "电子书标注。",
    "book_bookmarks": "电子书书签。",
    "finance_data_points": "金融时序数据点。AkShare 采集器直接写这里，不产出 ContentItem。",
    "pipeline_templates": "流水线模板：显式定义全部步骤。",
    "pipeline_executions": "流水线执行记录。",
    "pipeline_steps": "流水线步骤执行记录。",
    "prompt_templates": "提示词模板。",
    "platform_credentials": "平台凭证（`credential_data` Fernet 加密）。",
    "system_settings": "键值配置。含 `content.filters` 等 JSON 业务对象。",
}

_ONDELETE = {None: "NO ACTION"}


def _type(col) -> str:
    return str(col.type).replace("VARCHAR", "VARCHAR").upper()


def gen_doc() -> str:
    out = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        out.append(f"#### {table.name}\n")
        if table.name in TABLE_NOTES:
            out.append(TABLE_NOTES[table.name] + "\n")
        out.append("| 列 | 类型 | 可空 | 默认 | 约束 |")
        out.append("|---|---|---|---|---|")
        for col in table.columns:
            cons = []
            if col.primary_key:
                cons.append("PK")
            for fk in col.foreign_keys:
                cons.append(f"FK → {fk.target_fullname}（ON DELETE {fk.ondelete or 'NO ACTION'}）")
            default = ""
            if col.server_default is not None:
                default = f"`{col.server_default.arg}`（库级）"
            elif col.default is not None:
                arg = col.default.arg
                default = "（ORM 端）" if callable(arg) else f"`{arg}`（ORM 端）"
            out.append(f"| `{col.name}` | {_type(col)} | {'是' if col.nullable else '否'} | {default} | {'；'.join(cons)} |")
        extras = []
        for c in sorted(table.constraints, key=lambda c: c.name or ""):
            if c.__class__.__name__ == "UniqueConstraint":
                extras.append(f"- 唯一约束 `{c.name}`: ({', '.join(col.name for col in c.columns)})")
        for idx in sorted(table.indexes, key=lambda i: i.name):
            where = idx.dialect_options["postgresql"].get("where")
            desc = f"- {'唯一' if idx.unique else ''}索引 `{idx.name}`: ({', '.join(e.name for e in idx.expressions)})"
            if where is not None:
                desc += f" WHERE {where}"
            extras.append(desc)
        if extras:
            out.append("")
            out.extend(extras)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def check() -> int:
    from app.core.database import engine

    insp = sa_inspect(engine)
    problems: list[str] = []
    db_tables = {t for t in insp.get_table_names() if not t.startswith("procrastinate_") and t != "alembic_version"}
    model_tables = set(Base.metadata.tables)

    for t in sorted(model_tables - db_tables):
        problems.append(f"[表] 模型有、库里没有: {t}")
    for t in sorted(db_tables - model_tables):
        problems.append(f"[表] 库里有、模型没有: {t}")

    for name in sorted(model_tables & db_tables):
        table = Base.metadata.tables[name]
        db_cols = {c["name"]: c for c in insp.get_columns(name)}
        for c in sorted(set(table.columns.keys()) - set(db_cols)):
            problems.append(f"[列] {name}.{c}: 模型有、库里没有")
        for c in sorted(set(db_cols) - set(table.columns.keys())):
            problems.append(f"[列] {name}.{c}: 库里有、模型没有")
        for cname in set(table.columns.keys()) & set(db_cols):
            col = table.columns[cname]
            if not col.primary_key and bool(col.nullable) != bool(db_cols[cname]["nullable"]):
                problems.append(f"[可空] {name}.{cname}: 模型 nullable={col.nullable}，库 nullable={db_cols[cname]['nullable']}")

        db_idx = {i["name"] for i in insp.get_indexes(name)} | {u["name"] for u in insp.get_unique_constraints(name)}
        model_idx = {i.name for i in table.indexes} | {
            c.name for c in table.constraints if c.__class__.__name__ == "UniqueConstraint" and c.name
        }
        # 列上写 unique=True 时约束没有显式名字，PostgreSQL 自动命名为 <表>_<列>_key
        model_idx |= {f"{name}_{col.name}_key" for col in table.columns if col.unique}
        for i in sorted(model_idx - db_idx):
            problems.append(f"[索引] {name}.{i}: 模型声明了、库里没有")
        for i in sorted(db_idx - model_idx):
            problems.append(f"[索引] {name}.{i}: 库里有、模型没声明（autogenerate 会产出假 diff）")

        db_fks = {tuple(f["constrained_columns"]): (f["options"].get("ondelete") or "NO ACTION").upper()
                  for f in insp.get_foreign_keys(name)}
        for col in table.columns:
            for fk in col.foreign_keys:
                want = (fk.ondelete or "NO ACTION").upper()
                got = db_fks.get((col.name,))
                if got is None:
                    problems.append(f"[外键] {name}.{col.name}: 模型有外键、库里没有")
                elif got != want:
                    problems.append(f"[外键] {name}.{col.name}: ON DELETE 模型={want} 库={got}")

    if problems:
        print(f"发现 {len(problems)} 处模型与库不一致:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"模型与库一致（{len(model_tables)} 张表）")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "doc":
        sys.stdout.write(gen_doc())
    elif mode == "check":
        sys.exit(check())
    else:
        sys.exit(f"未知模式: {mode}")
