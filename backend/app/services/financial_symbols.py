"""蚂蚁 financial-data API 的 symbol 格式转换（纯函数，无 I/O）

蚂蚁 symbol 格式（2026-09-04 探针实测，见 scripts/verify/financial_data/probe_api.py）：
- A 股/ETF: 600519.SH / 000001.SZ / 920001.BJ
- 港股: 00700.HK（5 位补零）
- 美股: AAPL.O(纳斯达克) / BABA.N(纽交所) / xx.A(美交所)，后缀无法从裸 ticker 推导
- 指数: 蚂蚁特色编码（上证指数 1A0001.SH、沪深300 1B0300.SH），只能静态表映射
"""

# 指数 code → 蚂蚁 symbol。探针经 entity_recognition + basic-snapshot 双重验证。
# 注意 000001 在此表是上证指数(1A0001.SH)，与个股平安银行(000001.SZ)靠调用方 market 区分。
INDEX_FD_SYMBOLS: dict[str, str] = {
    "000001": "1A0001.SH",   # 上证指数
    "399001": "2A01.SZ",     # 深证成指
    "399006": "399006.SZ",   # 创业板指
    "000300": "1B0300.SH",   # 沪深300
    "000905": "1B0905.SH",   # 中证500
    "000688": "1B0688.SH",   # 科创50
    "HSI": "HSI.HK",         # 恒生指数
    "HSCEI": "HZ5014.HK",    # 恒生国企指数
    "HSTECH": "HZ2083.HK",   # 恒生科技指数
    "DJI": "DJI.USI",        # 道琼斯
    "IXIC": "IXIC.USI",      # 纳斯达克综合
}

# 高频美股 ticker → 交易所后缀，miss 时走批量探测（见 client.resolve_us_symbol）
US_SUFFIX: dict[str, str] = {
    "AAPL": "O", "MSFT": "O", "GOOG": "O", "GOOGL": "O", "AMZN": "O",
    "META": "O", "NVDA": "O", "TSLA": "O", "AVGO": "O", "NFLX": "O",
    "AMD": "O", "INTC": "O", "QCOM": "O", "CSCO": "O", "ADBE": "O",
    "PEP": "O", "COST": "O", "TXN": "O", "AMAT": "O", "MU": "O",
    "PDD": "O", "JD": "O", "BIDU": "O", "NTES": "O", "MRNA": "O",
    "ASML": "O", "ARM": "O", "SMCI": "O", "COIN": "O", "MSTR": "O",
    "BABA": "N", "BRK.B": "N", "BRK.A": "N", "JPM": "N", "V": "N",
    "MA": "N", "UNH": "N", "HD": "N", "PG": "N", "XOM": "N",
    "CVX": "N", "KO": "N", "MCD": "N", "DIS": "N", "NKE": "N",
    "BA": "N", "GS": "N", "MS": "N", "WMT": "N", "JNJ": "N",
    "PFE": "N", "MRK": "N", "ABBV": "N", "LLY": "N", "CRM": "N",
    "ORCL": "N", "IBM": "N", "GE": "N", "CAT": "N", "MMM": "N",
    "T": "N", "VZ": "N", "TSM": "N", "NIO": "N", "XPEV": "N",
    "LI": "N", "BEKE": "N", "ZM": "O", "UBER": "N", "ABNB": "O",
    "PLTR": "O", "SNOW": "N", "SHOP": "N", "SPOT": "N", "SQ": "N",
    "PYPL": "O", "TM": "N", "SONY": "N", "F": "N", "GM": "N",
}

_US_EXCHANGES = ("O", "N", "A")


def a_share_suffix(code: str) -> str:
    """A 股/ETF/可转债代码 → 交易所后缀。

    规则与既有雪球映射 _to_xq_symbol 一致（经 3 次线上修正验证）：
      SH: 6xx(主板) 688(科创板) 5xx(ETF, 除159) 9xx(B股) 110/113(可转债)
      SZ: 0xx(主板) 3xx(创业板) 159(ETF) 12x(可转债)
      BJ: 4xx 8xx 920(北交所)
    """
    if code.startswith("159"):
        return "SZ"
    if code[0] in "569":
        return "SH"
    if code[0] in "48":
        return "BJ"
    if code[:3] in ("110", "113"):
        return "SH"
    return "SZ"


def to_fd_symbol(code: str, market: str) -> str | None:
    """内部 (code, market) → 蚂蚁 symbol。无法确定性映射时返回 None（调用方降级）。

    market: "A" | "etf" | "HK" | "US" | "index"
    美股返回 None 的场景交由 client.resolve_us_symbol 探测。
    """
    code = code.strip()
    if not code:
        return None
    if market in ("A", "etf"):
        if not code.isdigit() or len(code) != 6:
            return None
        return f"{code}.{a_share_suffix(code)}"
    if market == "HK":
        if not code.isdigit():
            return None
        return f"{code.zfill(5)}.HK"
    if market == "US":
        suffix = US_SUFFIX.get(code.upper())
        return f"{code.upper()}.{suffix}" if suffix else None
    if market == "index":
        return INDEX_FD_SYMBOLS.get(code.upper())
    return None


def us_candidates(ticker: str) -> list[str]:
    """裸美股 ticker → 三个交易所后缀候选，供批量探测（无效项服务端自动剔除）"""
    t = ticker.strip().upper()
    return [f"{t}.{ex}" for ex in _US_EXCHANGES]


def from_fd_symbol(fd_symbol: str) -> str:
    """蚂蚁 symbol → 原始代码（600519.SH → 600519，AAPL.O → AAPL），用于响应回显"""
    return fd_symbol.rsplit(".", 1)[0] if "." in fd_symbol else fd_symbol
