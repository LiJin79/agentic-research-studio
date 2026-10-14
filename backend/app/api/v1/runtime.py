from fastapi import APIRouter

from app.agents.tools.registry import tool_catalog
from app.core.config import get_settings
from app.llm.catalog import model_catalog

router = APIRouter()


@router.get("/runtime")
async def runtime_info() -> dict:
    """返回可展示配置与密钥是否已配置，任何时候都不返回密钥内容。"""
    settings = get_settings()
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_configured": settings.llm_provider in {"mock", "ollama"} or bool(settings.llm_api_key),
        "models": [profile.public() for profile in model_catalog()],
        "tools": tool_catalog(),
        "prompt_version": "2026-10-13-tools-v1",
        "default_model_id": "default",
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_configured": settings.embedding_provider in {"hash", "local", "ollama"}
        or bool(settings.embedding_api_key),
        "embedding_dimensions": settings.embedding_dimensions,
        "collection": settings.vector_collection,
        "web_configured": settings.web_search_configured,
        "web_provider": settings.web_search_provider,
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
        "demo": settings.llm_provider == "mock",
    }
