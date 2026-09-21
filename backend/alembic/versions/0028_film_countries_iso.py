"""影片国家字段统一为 ISO 3166-1 两位码：Emby 同步写入的英文全称改写为与 TMDb 一致的代码

Revision ID: 0028_film_countries_iso
Revises: 0027_drop_content_language
Create Date: 2026-09-21
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0028_film_countries_iso'
down_revision: Union[str, Sequence[str], None] = '0027_drop_content_language'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 迁移自带映射快照（不 import 应用代码）；覆盖库内实际出现过的全称及常见值
_NAME_TO_ISO = {
    "united states of america": "US", "united states": "US", "united kingdom": "GB",
    "china": "CN", "hong kong": "HK", "taiwan": "TW", "japan": "JP", "south korea": "KR",
    "india": "IN", "thailand": "TH", "france": "FR", "germany": "DE", "italy": "IT",
    "spain": "ES", "sweden": "SE", "denmark": "DK", "russia": "RU", "canada": "CA",
    "australia": "AU", "new zealand": "NZ",
}


def normalize_countries(values):
    out = []
    for v in values or []:
        v = (v or "").strip()
        if not v:
            continue
        code = v.upper() if len(v) == 2 else _NAME_TO_ISO.get(v.lower(), v)
        if code not in out:
            out.append(code)
    return out


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, raw_data->'countries' FROM content_items "
        "WHERE kind = 'film' AND jsonb_typeof(raw_data->'countries') = 'array'"
    )).fetchall()
    for cid, countries in rows:
        if isinstance(countries, str):
            countries = json.loads(countries)
        fixed = normalize_countries(countries)
        if fixed != countries:
            conn.execute(
                sa.text("UPDATE content_items SET raw_data = jsonb_set(raw_data, '{countries}', CAST(:c AS jsonb)) WHERE id = :id"),
                {"c": json.dumps(fixed), "id": cid},
            )


def downgrade() -> None:
    pass  # 归一化不可逆，也无需回退
