"""API Key 认证中间件"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class APIKeyMiddleware(BaseHTTPMiddleware):
    """简单的 API Key 认证，通过 X-API-Key header 验证。

    - 未配置 API_KEY 时跳过认证（本地开发零摩擦）
    - /health 和非 /api/ 路径不需要认证
    """

    async def dispatch(self, request: Request, call_next):
        # 非 API 路径和健康检查不需要认证
        if not request.url.path.startswith("/api/") or request.url.path == "/health":
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
