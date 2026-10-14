from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by the lightweight liveness endpoint."""

    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Response containing one availability result per infrastructure service."""

    status: Literal["ok", "degraded"]
    checks: dict[str, str]
