import asyncio
from collections.abc import Awaitable, Callable

from app.cache.redis import check_redis
from app.db.session import check_postgres
from app.vector.qdrant import check_qdrant

HealthCheck = Callable[[], Awaitable[None]]


async def collect_readiness() -> dict[str, str]:
    """Probe infrastructure concurrently and return one status per dependency."""
    checks: dict[str, HealthCheck] = {
        "postgres": check_postgres,
        "redis": check_redis,
        "qdrant": check_qdrant,
    }
    results = await asyncio.gather(
        *(check() for check in checks.values()),
        return_exceptions=True,
    )

    return {
        name: "ok" if not isinstance(result, BaseException) else "unavailable"
        for name, result in zip(checks, results, strict=True)
    }
