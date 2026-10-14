from fastapi import APIRouter

from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.runtime import router as runtime_router
from app.api.v1.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(runtime_router, tags=["runtime"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
