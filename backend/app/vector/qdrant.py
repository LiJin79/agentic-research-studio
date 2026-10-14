from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings

_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    """Lazily create one process-wide asynchronous Qdrant client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncQdrantClient(url=settings.qdrant_url)
    return _client


async def check_qdrant() -> None:
    """Raise when Qdrant cannot return its collection list."""
    await get_qdrant_client().get_collections()


async def close_qdrant() -> None:
    """Close and clear the shared Qdrant client during application shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
