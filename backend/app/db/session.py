from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,
)
session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Provide one transaction-capable session to a FastAPI request."""
    async with session_factory() as session:
        yield session


async def check_postgres() -> None:
    """Raise when PostgreSQL cannot execute a minimal query."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_postgres() -> None:
    """Dispose the SQLAlchemy connection pool during application shutdown."""
    await engine.dispose()
