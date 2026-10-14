from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Lazily create one process-wide asynchronous Redis client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def check_redis() -> None:
    """Raise when Redis does not answer a PING command."""
    if not await get_redis_client().ping():
        raise ConnectionError("Redis ping returned a false value")


async def close_redis() -> None:
    """Close and clear the shared Redis client during application shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
