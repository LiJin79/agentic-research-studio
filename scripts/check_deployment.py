"""Check local deployment and credential failure handling without paid model calls."""

import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings  # noqa: E402


def main() -> None:
    """检查基础设施、前端与脱敏配置，缺少生成密钥时验证明确失败及持久终态。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8001")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", default="evaluation/deployment-report.json")
    args = parser.parse_args()
    token = get_settings().app_access_token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(
        base_url=args.api_url, timeout=60, headers=headers, trust_env=False
    ) as client:
        health = client.get("/api/v1/health/ready")
        health.raise_for_status()
        runtime_response = client.get("/api/v1/runtime")
        runtime_response.raise_for_status()
        runtime = runtime_response.json()
        frontend = client.get(args.frontend_url)
        frontend.raise_for_status()
        assert '<div id="app">' in frontend.text
        results = {
            "health": health.json(),
            "frontend": "passed",
            "runtime": runtime,
            "cloud_inference": "not_tested",
            "ollama_gpu": "not_tested",
        }
        if not runtime["llm_configured"]:
            created = client.post(
                "/api/v1/sessions", json={"title": "配置验收-" + str(uuid.uuid4())[:8]}
            )
            created.raise_for_status()
            session_id = created.json()["id"]
            try:
                response = client.post(
                    "/api/v1/chat", json={"session_id": session_id, "message": "你好"}
                )
                assert response.status_code == 502, response.text
                assert "LLM_API_KEY" in response.json()["detail"], response.text
                history = client.get(f"/api/v1/sessions/{session_id}/messages")
                history.raise_for_status()
                assert history.json()["total"] == 1, history.text
                assert history.json()["items"][0]["message_metadata"]["status"] == "failed"
                results["missing_key_rejected_without_mock_fallback"] = "passed"
            finally:
                client.delete(f"/api/v1/sessions/{session_id}").raise_for_status()
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
