"""RSS 采集器共享工具"""
import json
import logging

from app.models.content import SourceConfig

logger = logging.getLogger(__name__)


def coerce_config(config_json) -> dict:
    """安全获取 source.config_json 为 dict。

    config_json 已是 JSONB（正常返回 dict），此处仅作脏数据恢复兜底：
    历史上个别源的 config 被二次编码成 JSON 字符串标量存入 JSONB 列，
    ORM 加载后是 str，直接 .get() 会抛 AttributeError。
    """
    if isinstance(config_json, dict):
        return config_json
    if isinstance(config_json, str):
        try:
            parsed = json.loads(config_json)
            if isinstance(parsed, dict):
                return parsed
            logger.warning("config_json 解析后非 dict: %r", parsed)
        except (json.JSONDecodeError, ValueError):
            logger.warning("config_json 字符串无法解析为 JSON: %.100r", config_json)
        return {}
    return {}


def resolve_rss_feed_url(source: SourceConfig, rsshub_base_url: str) -> str:
    """
    解析 RSS 数据源的实际 Feed URL

    逻辑:
      - rss.hub: 使用 config_json.rsshub_route，拼接到 rsshub_base_url
      - rss.standard: 使用 url 字段
      - 其他: 返回 url 字段

    Args:
        source: 数据源配置对象
        rsshub_base_url: RSSHub 服务的基础 URL（如 http://rsshub:1200）

    Returns:
        完整的 Feed URL

    Raises:
        ValueError: 如果必需字段缺失或格式错误
    """
    if source.source_type == "rss.hub":
        config = coerce_config(source.config_json)
        route = config.get("rsshub_route", "").strip()
        if not route:
            raise ValueError(f"RSSHub source '{source.name}' missing rsshub_route in config_json")
        if not route.startswith("/"):
            route = f"/{route}"
        return f"{rsshub_base_url.rstrip('/')}{route}"
    elif source.source_type == "rss.standard":
        if not source.url:
            raise ValueError(f"RSS/Atom source '{source.name}' missing url field")
        return source.url
    else:
        return source.url or ""
