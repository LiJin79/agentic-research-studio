import logging
import secrets
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings

logger = logging.getLogger("app.requests")


async def request_middleware(request: Request, call_next):
    """请求 id、耗时与可选访问口令；日志不记录请求正文和凭据。"""
    started, request_id = time.monotonic(), str(uuid.uuid4())
    token = get_settings().app_access_token
    if token and request.url.path.startswith("/api/") and "/health/" not in request.url.path:
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if not secrets.compare_digest(supplied, token):
            return JSONResponse(status_code=401, content={"detail": "请填写工作台访问口令"})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request id=%s method=%s path=%s status=%s duration_ms=%d",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.monotonic() - started) * 1000,
    )
    return response
