"""API Key 认证中间件"""

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

# 媒体流式传输路径豁免认证：浏览器原生 <video>/<audio>/<img> 标签无法携带自定义 header
# 路径含 UUID content_id，不可猜测，安全风险低
_MEDIA_PATH_RE = re.compile(r"^/api/(video|audio|media)/[a-f0-9]+/")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """简单的 API Key 认证，通过 X-API-Key header 验证。

    - 未配置 API_KEY 时跳过认证（本地开发零摩擦）
    - /health 和非 /api/ 路径不需要认证
    - 媒体流路径（video/audio/media）豁免认证
    """

    async def dispatch(self, request: Request, call_next):
        # 非 API 路径和健康检查不需要认证
        if not request.url.path.startswith("/api/") or request.url.path == "/health":
            return await call_next(request)

        # 媒体流路径豁免：<video>/<audio>/<img> 标签无法携带 X-API-Key
        # 仅限 GET，避免同路径前缀的写操作（如 /api/media/{id}/retry）被误豁免
        if request.method == "GET" and _MEDIA_PATH_RE.match(request.url.path):
            return await call_next(request)

        # 未配置 API_KEY 则跳过认证
        if not settings.API_KEY:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if api_key != settings.API_KEY:
            return JSONResponse(
                status_code=401,
                content={"code": 401, "data": None, "message": "Invalid API Key"},
            )

        return await call_next(request)
