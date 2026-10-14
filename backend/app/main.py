import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.cache.redis import close_redis
from app.core.config import get_settings
from app.core.exception_handlers import register_exception_handlers
from app.db.checkpointer import close_checkpointer
from app.db.session import close_postgres
from app.observability.middleware import request_middleware
from app.vector.qdrant import close_qdrant

logger = logging.getLogger(__name__)


def configure_windows_event_loop() -> None:
    """Use the selector loop required by psycopg asynchronous connections on Windows."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


configure_windows_event_loop()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own startup and shutdown resources in one explicit lifecycle."""
    settings = get_settings()
    logger.info("Starting %s", settings.app_name)

    try:
        yield
    finally:
        await asyncio.gather(
            close_postgres(),
            close_checkpointer(),
            close_redis(),
            close_qdrant(),
            return_exceptions=True,
        )
        logger.info("Stopping %s", settings.app_name)


def create_app() -> FastAPI:
    """Create the FastAPI application without performing work at import time."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.app_debug,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(application)
    application.middleware("http")(request_middleware)
    application.include_router(api_router, prefix=settings.api_v1_prefix)

    @application.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        """Return service identity and the relative Swagger URL."""
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return application


app = create_app()
