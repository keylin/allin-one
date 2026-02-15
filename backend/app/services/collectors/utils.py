"""RSS 采集器共享工具"""
import json
from app.models.content import SourceConfig


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
        config = json.loads(source.config_json) if source.config_json else {}
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
