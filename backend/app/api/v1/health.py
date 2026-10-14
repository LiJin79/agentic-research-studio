from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.schemas.common import HealthResponse, ReadinessResponse
from app.services.health_service import collect_readiness

router = APIRouter()


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report whether the API process can receive HTTP requests."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def ready(response: Response) -> ReadinessResponse:
    """Report whether every required infrastructure dependency is reachable."""
    checks = await collect_readiness()
    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    if status == "degraded":
        response.status_code = 503

    return ReadinessResponse(
        status=status,
        checks=checks,
    )
