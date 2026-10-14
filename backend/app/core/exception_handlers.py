from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.cache.coordination import ConversationBusyError
from app.core.exceptions import (
    ModelSelectionError,
    RateLimitExceededError,
    ResourceNotFoundError,
    UpstreamServiceError,
)


def register_exception_handlers(application: FastAPI) -> None:
    """Translate domain exceptions into stable HTTP responses in one place."""

    @application.exception_handler(ModelSelectionError)
    async def model_selection_handler(
        request: Request, exception: ModelSelectionError
    ) -> JSONResponse:
        """模型选项无效返回明确的 422，而不是服务器内部错误。"""
        return JSONResponse(status_code=422, content={"detail": str(exception)})

    @application.exception_handler(ConversationBusyError)
    async def busy_handler(request: Request, exception: ConversationBusyError) -> JSONResponse:
        """并发或幂等冲突返回 409，客户端可决定是否重试。"""
        return JSONResponse(status_code=409, content={"detail": str(exception)})

    @application.exception_handler(ResourceNotFoundError)
    async def resource_not_found_handler(
        request: Request,
        exception: ResourceNotFoundError,
    ) -> JSONResponse:
        """Convert a domain not-found error into HTTP 404."""
        return JSONResponse(status_code=404, content={"detail": str(exception)})

    @application.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(
        request: Request,
        exception: RateLimitExceededError,
    ) -> JSONResponse:
        """Tell clients to slow down without exposing Redis internals."""
        return JSONResponse(status_code=429, content={"detail": str(exception)})

    @application.exception_handler(UpstreamServiceError)
    async def upstream_service_handler(
        request: Request,
        exception: UpstreamServiceError,
    ) -> JSONResponse:
        """Represent model and search failures as a Bad Gateway response."""
        return JSONResponse(status_code=502, content={"detail": str(exception)})
