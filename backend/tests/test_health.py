from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_root_describes_the_api() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "AI Agentic RAG"
    assert response.json()["docs"] == "/docs"


def test_liveness_endpoint() -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "AI Agentic RAG",
        "version": "0.1.0",
    }


def test_readiness_reports_integrated_dependencies(monkeypatch) -> None:
    async def healthy_dependencies() -> dict[str, str]:
        return {"postgres": "ok", "redis": "ok", "qdrant": "ok"}

    monkeypatch.setattr("app.api.v1.health.collect_readiness", healthy_dependencies)
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"postgres": "ok", "redis": "ok", "qdrant": "ok"},
    }


def test_readiness_returns_503_when_a_dependency_is_unavailable(monkeypatch) -> None:
    async def degraded_dependencies() -> dict[str, str]:
        return {"postgres": "ok", "redis": "unavailable", "qdrant": "ok"}

    monkeypatch.setattr("app.api.v1.health.collect_readiness", degraded_dependencies)
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["redis"] == "unavailable"
