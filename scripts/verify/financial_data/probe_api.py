#!/usr/bin/env python3
"""蚂蚁 financial-data API 探针（Phase 0 门禁）

验证并固化以下事实（2026-09-04 首次运行结论已写入代码常量）：
1. 指数 symbol 静态表（backend/app/services/financial_symbols.py INDEX_FD_SYMBOLS）全部可查
2. 美股后缀批量探测机制：无效候选被 BAD_INPUT issue 剔除，有效候选返回行
3. 字段单位：pct_chg=百分比 / volume=股 / amount,total_mv=元 / turnover_rate=小数
4. K 线：count 独立可用（≤250）、返回倒序、date 带时分秒需截断
5. 宏观 seed（backend/mcp_server.py _MACRO_FD_SEED）有数据且单位符合预期

用法（宿主机或 allin-mcp 容器内，需 FINANCIAL_DATA_API_KEY）:
    python3 scripts/verify/financial_data/probe_api.py
"""

import json
import os
import sys
import urllib.request

BASE = os.environ.get("FINANCIAL_DATA_BASE_URL", "https://dfdatamcpnexus-prod.antgroup-inc.cn")
API_KEY = os.environ.get("FINANCIAL_DATA_API_KEY", "")

INDEX_FD_SYMBOLS = {
    "上证指数": "1A0001.SH", "深证成指": "2A01.SZ", "创业板指": "399006.SZ",
    "沪深300": "1B0300.SH", "中证500": "1B0905.SH", "科创50": "1B0688.SH",
    "恒生指数": "HSI.HK", "国企指数": "HZ5014.HK", "恒生科技": "HZ2083.HK",
    "道琼斯": "DJI.USI", "纳斯达克": "IXIC.USI",
}
MACRO_SEED = {
    "ppi": ("110002644", lambda v, u: 80 < v < 120),           # 上年同月=100 指数
    "pmi": ("110166523", lambda v, u: 35 < v < 65),            # PMI
    "gdp": ("110000001", lambda v, u: v > 100000 and u == "亿元"),  # 现价累计值
    "m2":  ("110111410", lambda v, u: v > 1000000 and u == "亿元"),  # 期末值
}

passed = failed = 0


def check(name: str, ok: bool, detail: str = ""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))


def query(mode: str, requests_body: list) -> dict:
    payload = json.dumps({"mode": mode, "requests": requests_body}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/common_query", data=payload, method="POST",
        headers={"X-API-Key": API_KEY, "X-API-Version": "1.6.0",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def rows_of(result: dict) -> list[dict]:
    fields = (result.get("meta") or {}).get("fields") or []
    return [dict(zip(fields, r)) for r in result.get("data") or []]


def main() -> int:
    if not API_KEY:
        print("FINANCIAL_DATA_API_KEY 未配置")
        return 1

    print("== 1. 指数 symbol 静态表 ==")
    r = query("data", [{"url": "/api/v1/quote/basic-snapshot",
                        "params": {"symbols": list(INDEX_FD_SYMBOLS.values())}}])
    got = {row["symbol"]: row for row in rows_of(r["results"][0])}
    for name, sym in INDEX_FD_SYMBOLS.items():
        row = got.get(sym)
        check(f"{name} {sym}", row is not None and row.get("last") is not None,
              f"last={row.get('last')}" if row else "无数据")

    print("== 2. 美股后缀批量探测 ==")
    r = query("data", [{"url": "/api/v1/quote/basic-snapshot",
                        "params": {"symbols": ["AAPL.O", "AAPL.N", "AAPL.A"]}}])
    res = r["results"][0]
    syms = {row["symbol"] for row in rows_of(res)}
    check("有效候选返回", syms == {"AAPL.O"}, f"got={syms}")
    check("无效候选以 issue 剔除",
          any(i.get("code") == "BAD_INPUT" for i in res.get("issues") or []),
          str(res.get("issues")))

    print("== 3. 字段单位合理性（600519.SH） ==")
    r = query("data", [
        {"url": "/api/v1/quote/basic-snapshot", "params": {"symbols": ["600519.SH"]}},
        {"url": "/api/v1/quote/derived-snapshot", "params": {"symbols": ["600519.SH"]}},
    ])
    basic = rows_of(r["results"][0])[0]
    derived = rows_of(r["results"][1])[0]
    check("pct_chg 是百分比数值", abs(basic["pct_chg"]) < 30, f"pct_chg={basic['pct_chg']}")
    check("last 价格量级合理", 100 < basic["last"] < 10000, f"last={basic['last']}")
    check("total_mv 单位是元（茅台 >1e11）", derived["total_mv"] > 1e11, f"total_mv={derived['total_mv']}")
    check("turnover_rate 是小数（<1）", 0 < derived["turnover_rate"] < 1,
          f"turnover_rate={derived['turnover_rate']}")

    print("== 4. K 线行为 ==")
    r = query("data", [{"url": "/api/v1/quote/kline-batch",
                        "params": {"symbols": ["600519.SH"], "period": "P_Day1",
                                   "split": "S_Before", "count": 250}}])
    kl = rows_of(r["results"][0])
    check("count=250 返回 250 条", len(kl) == 250, f"rows={len(kl)}")
    check("返回倒序（首条最新）", kl[0]["date"] > kl[-1]["date"], f"{kl[0]['date']} vs {kl[-1]['date']}")
    check("date 含时分秒（需截断）", len(kl[0]["date"]) > 10, kl[0]["date"])

    print("== 5. 宏观 seed ==")
    for key, (code, valid) in MACRO_SEED.items():
        r = query("macro_query", [{"params": {"indicator_codes": [code],
                                              "raw_question": f"查 {key}",
                                              "start_date": "2025-06-01 00:00:00"}}])
        res = r["results"][0]
        rows = rows_of(res)
        unit = ((res.get("meta") or {}).get("unit") or {}).get("indicator_value")
        val = rows[-1]["indicator_value"] if rows else None
        check(f"{key} ({code})", bool(rows) and valid(val, unit),
              f"latest={val} unit={unit} rows={len(rows)}")

    print(f"\n结果: {passed} 通过, {failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
