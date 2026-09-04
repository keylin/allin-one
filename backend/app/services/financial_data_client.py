"""蚂蚁 financial-data API 客户端（MCP 金融工具主数据源）

设计要点（docs/system_design.md §10.5）：
- 单端点 POST /api/v1/common_query，X-API-Key 鉴权
- 错误三分类 classify_error → retryable / fatal / quota
- 主源冷却：连续失败或 quota 后 N 秒内跳过主源直接走 legacy（不做熔断状态机）
- 单层 TTL 缓存落在本模块，工具层不再叠加
- 响应严格按 meta.fields 动态映射，禁止固定下标
"""

import asyncio
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.services.financial_symbols import US_SUFFIX, us_candidates

logger = logging.getLogger(__name__)

_COMMON_QUERY_PATH = "/api/v1/common_query"
URL_BASIC_SNAPSHOT = "/api/v1/quote/basic-snapshot"
URL_DERIVED_SNAPSHOT = "/api/v1/quote/derived-snapshot"
URL_KLINE_BATCH = "/api/v1/quote/kline-batch"

# 冷却窗口：quota 或连续失败后跳过主源的秒数
_COOLDOWN_SECONDS = 60
_FAILURE_THRESHOLD = 3
# 单次请求（含重试）总预算，超出即放弃走降级——MCP 是同步交互，不能让 AI 客户端久等
_TOTAL_BUDGET_SECONDS = 12.0


class FinancialDataError(Exception):
    """主源调用失败（已含重试），调用方捕获后走 legacy 降级"""


def classify_error(exc: Exception) -> Literal["retryable", "fatal", "quota"]:
    """错误三分类：retryable 重试；quota 冷却后降级；fatal 直接降级"""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "quota"
        if status in (401, 403):
            return "fatal"
        if status >= 500:
            return "retryable"
        return "fatal"
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return "retryable"
    return "fatal"


class _TTLCache:
    """极简 TTL 缓存：key → (expire_at, value)"""

    def __init__(self, max_entries: int = 512):
        self._data: dict[str, tuple[float, Any]] = {}
        self._max = max_entries

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry and entry[0] > time.time():
            return entry[1]
        return None

    def set(self, key: str, value: Any, ttl: float) -> None:
        if len(self._data) >= self._max:
            now = time.time()
            self._data = {k: v for k, v in self._data.items() if v[0] > now}
            if len(self._data) >= self._max:  # 清理后仍满，丢弃最早过期的一半
                keep = sorted(self._data.items(), key=lambda kv: kv[1][0])[len(self._data) // 2:]
                self._data = dict(keep)
        self._data[key] = (time.time() + ttl, value)


def _cache_key(mode: str, requests: list[dict]) -> str:
    payload = json.dumps({"m": mode, "r": requests}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()


def _bj_time_str(dt: datetime | None = None) -> str:
    """北京时间字符串，仅用于蚂蚁 API 的 start_date/end_date 参数。

    容器 TZ=UTC，蚂蚁 API 是北京时间口径；此函数绝不用于落库或与 utcnow() 比较。
    """
    from app.core.time import utcnow

    return ((dt or utcnow()) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


class FinancialDataClient:
    def __init__(self, api_key: str, base_url: str, api_version: str, timeout: float):
        self._headers = {
            "X-API-Key": api_key,
            "X-API-Version": api_version,
            "Content-Type": "application/json",
        }
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._cache = _TTLCache()
        self._us_symbol_cache: dict[str, str] = {}
        self._cooldown_until = 0.0
        self._consecutive_failures = 0
        self._client: httpx.AsyncClient | None = None

    # ---- 底层 ----

    def in_cooldown(self) -> bool:
        return time.time() < self._cooldown_until

    def _record_failure(self, kind: str) -> None:
        self._consecutive_failures += 1
        if kind == "quota" or self._consecutive_failures >= _FAILURE_THRESHOLD:
            self._cooldown_until = time.time() + _COOLDOWN_SECONDS
            logger.warning(
                "financial_data cooldown %ds (kind=%s, failures=%d)",
                _COOLDOWN_SECONDS, kind, self._consecutive_failures,
            )

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    async def _post(self, body: dict) -> dict:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers,
                timeout=httpx.Timeout(self._timeout, connect=3.0),
            )
        resp = await self._client.post(_COMMON_QUERY_PATH, json=body)
        resp.raise_for_status()
        return resp.json()

    async def _request(self, mode: str, requests: list[dict]) -> dict:
        """带重试的 common_query 请求，返回校验过 status 的原始响应。

        整体受 _TOTAL_BUDGET_SECONDS 硬预算约束，超时按 retryable 失败处理。
        """
        if self.in_cooldown():
            raise FinancialDataError("financial_data in cooldown")
        try:
            return await asyncio.wait_for(
                self._request_with_retries(mode, requests), timeout=_TOTAL_BUDGET_SECONDS,
            )
        except asyncio.TimeoutError:
            self._record_failure("retryable")
            raise FinancialDataError(
                f"total budget {_TOTAL_BUDGET_SECONDS}s exceeded for {mode}"
            ) from None

    async def _request_with_retries(self, mode: str, requests: list[dict]) -> dict:
        body = {"mode": mode, "requests": requests}
        max_retries = settings.FINANCIAL_DATA_MAX_RETRIES
        for attempt in range(max_retries + 1):
            try:
                data = await self._post(body)
                break
            except Exception as e:
                kind = classify_error(e)
                logger.warning(
                    "financial_data %s attempt %d/%d failed kind=%s: %s",
                    mode, attempt + 1, max_retries + 1, kind, e,
                )
                if kind != "retryable" or attempt >= max_retries:
                    self._record_failure(kind)
                    raise FinancialDataError(str(e)) from e
                await asyncio.sleep(0.4 * (3 ** attempt) * random.uniform(0.75, 1.25))

        if data.get("status") not in ("SUCCESS", "FAILED"):
            self._record_failure("fatal")
            raise FinancialDataError(f"unexpected status: {data.get('status')!r}")
        return data

    async def common_query(
        self,
        requests: list[dict],
        mode: str = "data",
        cache_ttl: float | None = None,
    ) -> list[dict]:
        """执行 common_query（results[] 形态的 mode：data / macro_query 等）。

        返回与 requests 下标对齐的列表，每项 {"url", "meta", "rows", "issues", "ok"}，
        rows 已按 meta.fields 转 dict。整体不可达/鉴权失败时抛 FinancialDataError。
        注意 entity_recognition 是 items[] 形态，走 recognize()，不能用本方法。
        """
        key = _cache_key(mode, requests)
        if cache_ttl:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        data = await self._request(mode, requests)

        results = []
        for res in data.get("results", []):
            fields = (res.get("meta") or {}).get("fields") or []
            rows: list[dict] = []
            for raw in res.get("data") or []:
                if len(raw) == len(fields):
                    rows.append(dict(zip(fields, raw)))
            results.append({
                "url": res.get("url"),
                "meta": res.get("meta") or {},
                "rows": rows,
                "issues": res.get("issues") or [],
                "ok": bool(rows),
            })
        # FAILED 且无任何可用子结果才算失败
        if data.get("status") == "FAILED" and not any(r["ok"] for r in results):
            self._record_failure("fatal")
            raise FinancialDataError(f"FAILED: {data.get('issues')}")
        # SUCCESS 但 results 条数不足（vendor 部分退化）→ 视为失败，避免下游 IndexError
        if len(results) < len(requests):
            self._record_failure("fatal")
            raise FinancialDataError(
                f"results incomplete: got {len(results)}, expected {len(requests)}")

        self._record_success()
        if cache_ttl:
            self._cache.set(key, results, cache_ttl)
        return results

    # ---- 行情 ----

    async def basic_snapshot(self, symbols: list[str], cache_ttl: float = 30) -> dict[str, dict]:
        """实时行情快照。返回 {fd_symbol: row}，无数据的 symbol 不出现。"""
        results = await self.common_query(
            [{"url": URL_BASIC_SNAPSHOT, "params": {"symbols": symbols}}],
            cache_ttl=cache_ttl,
        )
        return {r["symbol"]: r for r in results[0]["rows"] if r.get("symbol")}

    async def quote_with_valuation(self, symbols: list[str]) -> dict[str, dict]:
        """一次往返拿行情+估值，按 symbol 合并（估值字段可能缺失）。"""
        results = await self.common_query(
            [
                {"url": URL_BASIC_SNAPSHOT, "params": {"symbols": symbols}},
                {"url": URL_DERIVED_SNAPSHOT, "params": {"symbols": symbols}},
            ],
            cache_ttl=30,
        )
        merged = {r["symbol"]: dict(r) for r in results[0]["rows"] if r.get("symbol")}
        for row in results[1]["rows"]:
            sym = row.get("symbol")
            if sym in merged:
                merged[sym].update({k: v for k, v in row.items() if v is not None})
        return merged

    async def kline(self, fd_symbol: str, period: str, split: str, count: int) -> list[dict]:
        """单标的 K 线，返回按日期升序（API 返回倒序，此处反转）。"""
        results = await self.common_query(
            [{
                "url": URL_KLINE_BATCH,
                "params": {"symbols": [fd_symbol], "period": period, "split": split, "count": count},
            }],
            cache_ttl=300,
        )
        return list(reversed(results[0]["rows"]))

    # ---- 宏观 ----

    async def macro_query(self, indicator_code: str, start_date: datetime) -> tuple[str | None, list[dict]]:
        """单指标宏观查询。返回 (单位, 按 end_date 升序的 rows)。"""
        results = await self.common_query(
            [{
                "params": {
                    "indicator_codes": [indicator_code],
                    "raw_question": f"查询指标 {indicator_code} 历史数据",
                    "start_date": _bj_time_str(start_date),
                },
            }],
            mode="macro_query",
            cache_ttl=3600,
        )
        res = results[0]
        unit = ((res["meta"].get("unit") or {}).get("indicator_value")
                if isinstance(res["meta"].get("unit"), dict) else None)
        rows = sorted(res["rows"], key=lambda r: r.get("end_date") or "")
        return unit, rows

    # ---- 实体识别（关键词搜索） ----

    async def recognize(self, keyword: str, asset_type: str | None = None) -> list[dict]:
        """名称关键词 → 候选实体列表（含 symbol/secu_abbr/asset_type）。

        entity_recognition 响应是顶层 meta.fields + items[].data[][] 形态（与 data 模式的
        results[] 不同），故不走 common_query，单独解析。
        """
        entity: dict[str, Any] = {"input": keyword}
        if asset_type:
            entity["asset_type"] = [asset_type]
        requests = [{"params": {"entities": [entity], "limit": 10}}]

        key = _cache_key("entity_recognition", requests)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        data = await self._request("entity_recognition", requests)
        fields = (data.get("meta") or {}).get("fields") or []
        rows: list[dict] = []
        for item in data.get("items") or []:
            for raw in item.get("data") or []:
                if len(raw) == len(fields):
                    rows.append(dict(zip(fields, raw)))
        self._record_success()
        self._cache.set(key, rows, 7 * 86400)
        return rows

    async def resolve_us_symbol(self, ticker: str) -> str | None:
        """裸美股 ticker → 带后缀 symbol：静态表 → 进程缓存 → 批量探测三候选。

        探针实测：无效后缀被服务端以 BAD_INPUT issue 剔除，有效的正常返回行。
        """
        t = ticker.strip().upper()
        if t in US_SUFFIX:
            return f"{t}.{US_SUFFIX[t]}"
        if t in self._us_symbol_cache:
            return self._us_symbol_cache[t] or None
        try:
            snap = await self.basic_snapshot(us_candidates(t), cache_ttl=7 * 86400)
        except Exception:
            return None  # 探测失败不缓存，下次调用重试
        resolved = next(iter(snap), None)
        # 负向结果（""）随进程生命周期缓存：解析失败的 ticker 不反复探测，重启后重试
        self._us_symbol_cache[t] = resolved or ""
        return resolved

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


_client_singleton: FinancialDataClient | None = None


def get_financial_client() -> FinancialDataClient | None:
    """进程级单例。未启用/未配 key/冷却中返回 None，调用方直接走 legacy。"""
    global _client_singleton
    if not settings.FINANCIAL_DATA_ENABLED or not settings.FINANCIAL_DATA_API_KEY:
        return None
    if _client_singleton is None:
        _client_singleton = FinancialDataClient(
            api_key=settings.FINANCIAL_DATA_API_KEY,
            base_url=settings.FINANCIAL_DATA_BASE_URL,
            api_version=settings.FINANCIAL_DATA_API_VERSION,
            timeout=settings.FINANCIAL_DATA_TIMEOUT,
        )
    return None if _client_singleton.in_cooldown() else _client_singleton


def tool_enabled(tool: str) -> bool:
    """FINANCIAL_DATA_TOOLS 工具级开关（逗号分隔；"all" 或空 = 全开）"""
    conf = settings.FINANCIAL_DATA_TOOLS.strip().lower()
    if conf in ("", "all"):
        return True
    return tool in {t.strip() for t in conf.split(",")}
