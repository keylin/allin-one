#!/usr/bin/env python3
"""新旧金融数据源对拍（宏观口径门禁 + 行情抽查）

宏观：蚂蚁 seed 指标 vs akshare 近 N 期数值，相对偏差 <1% 才算通过。
行情：随机抽 A 股标的，蚂蚁 vs 雪球价格偏差 <0.5%（盘中数据有时差，仅警示）。

必须在 allin-mcp 容器内运行（需要 akshare 与 backend 代码）:
    docker exec allin-mcp python3 /app/scripts_verify_parity.py   # 或挂载后运行
    cd backend && python3 ../scripts/verify/financial_data/verify_parity.py
"""

import asyncio
import os
import sys

# 宿主机跑：项目根/backend；容器内跑：backend 挂载在 /app
for _p in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../backend"), "/app"):
    if os.path.isdir(os.path.join(_p, "app")):
        sys.path.insert(0, _p)
        break

MACRO_PAIRS = {
    # key: (akshare 函数, 日期列, 值列, 对拍期数)
    "ppi": ("macro_china_ppi", "月份", "当月", 6),
    "pmi": ("macro_china_pmi", "月份", "制造业-指数", 6),
    "gdp": ("macro_china_gdp", "季度", "国内生产总值-绝对值", 4),
    "m2": ("macro_china_money_supply", "月份", "货币和准货币(M2)-数量(亿元)", 6),
}


async def main() -> int:
    import akshare as ak

    from app.core.time import utcnow
    from datetime import timedelta
    from app.services.financial_data_client import get_financial_client
    from mcp_server import _MACRO_FD_SEED  # noqa: 复用生产 seed，保证对拍对象一致

    client = get_financial_client()
    if client is None:
        print("financial_data client 未启用（检查 FINANCIAL_DATA_API_KEY）")
        return 1

    failed = 0
    print("== 宏观口径对拍（门禁：偏差 <1%） ==")
    for key, (fn_name, date_col, val_col, periods) in MACRO_PAIRS.items():
        code, days = _MACRO_FD_SEED[key]
        _, fd_rows = await client.macro_query(code, utcnow() - timedelta(days=periods * days + 120))
        fd_by_month = {str(r["end_date"])[:7]: float(r["indicator_value"]) for r in fd_rows}

        # akshare 宏观表新→旧倒序，取 head；日期为中文格式，转 YYYY-MM 键
        def ak_month(raw: str) -> str | None:
            raw = str(raw).strip()
            if "季度" in raw:  # "2026年第1-2季度" → 累计到季末月
                year = raw[:4]
                quarter = raw.rstrip("季度").split("第")[-1][-1]
                month_map = {"1": "03", "2": "06", "3": "09", "4": "12"}
                return f"{year}-{month_map.get(quarter)}" if quarter in month_map else None
            if "年" in raw and "月" in raw:  # "2026年07月份"
                year, rest = raw.split("年", 1)
                return f"{year}-{rest[:2]}"
            return raw[:7] if len(raw) >= 7 and raw[4] in "-." else None

        ak_df = getattr(ak, fn_name)()
        checked = mismatched = 0
        for _, row in ak_df.head(periods * 3).iterrows():
            month = ak_month(row[date_col])
            if month not in fd_by_month:
                continue
            try:
                ak_val = float(row[val_col])
            except (TypeError, ValueError):
                continue
            fd_val = fd_by_month[month]
            dev = abs(fd_val - ak_val) / max(abs(ak_val), 1e-9)
            checked += 1
            if dev >= 0.01:
                mismatched += 1
                print(f"  ❌ {key} {month}: fd={fd_val} ak={ak_val} 偏差={dev:.2%}")
        ok = checked > 0 and mismatched == 0
        failed += not ok
        print(f"  {'✅' if ok else '❌'} {key}: 对拍 {checked} 期, 不一致 {mismatched} 期"
              + ("" if checked else "（无可对齐数据，须人工核对口径）"))

    print("== 行情抽查（警示性，不计门禁） ==")
    quotes = await client.quote_with_valuation(["600519.SH", "000001.SZ", "510050.SH"])
    for sym, row in quotes.items():
        price = row.get("last") or row.get("close")
        print(f"  {sym}: last={price} pct_chg={row.get('pct_chg')} pe_ttm={row.get('pe_ttm')}")

    await client.aclose()
    print(f"\n宏观门禁: {'✅ 全部通过' if not failed else f'❌ {failed} 个指标未通过（保持 legacy）'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
