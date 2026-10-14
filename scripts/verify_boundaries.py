"""运行少量真实 HTTP 边界检查，不依赖浏览器按钮掩盖后端权限问题。"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import httpx  # noqa: E402
from app.core.config import get_settings  # noqa: E402


async def main() -> None:
    """只创建本脚本会话，检查拒绝联网、错误输入、消息终态与会话管理。"""
    settings = get_settings()
    headers = (
        {"Authorization": f"Bearer {settings.app_access_token}"}
        if settings.app_access_token
        else {}
    )
    report = {"checks": {}, "mode": "cloud"}
    checks = report["checks"]
    session_id = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8080/api/v1", headers=headers, trust_env=False, timeout=240
    ) as client:
        try:
            response = await client.get("/runtime")
            response.raise_for_status()
            runtime = response.json()
            checks["runtime_hides_keys"] = not any("api_key" in k.lower() for k in runtime)
            checks["real_provider"] = runtime["llm_provider"] != "mock"
            response = await client.post(
                "/sessions", json={"title": "边界验收-" + uuid.uuid4().hex[:8]}
            )
            response.raise_for_status()
            session_id = response.json()["id"]
            response = await client.patch(
                f"/sessions/{session_id}", json={"title": "边界验收-已改名"}
            )
            response.raise_for_status()
            checks["rename_persists"] = (await client.get(f"/sessions/{session_id}")).json()[
                "title"
            ] == "边界验收-已改名"
            response = await client.post("/chat", json={"session_id": session_id, "message": "  "})
            checks["blank_input_422"] = response.status_code == 422
            response = await client.post(
                "/chat", json={"session_id": str(uuid.uuid4()), "message": "你好"}
            )
            checks["missing_session_404"] = response.status_code == 404
            response = await client.post(
                "/chat",
                json={
                    "session_id": session_id,
                    "message": "请进行网页搜索 site:fastapi.tiangolo.com FastAPI",
                    "use_web_search": False,
                },
            )
            checks["web_permission_enforced"] = (
                response.status_code == 502
                and "未执行网页搜索" in response.json().get("detail", "")
            )
            response = await client.get(f"/sessions/{session_id}/messages")
            response.raise_for_status()
            checks["failed_request_persisted"] = (
                response.json()["items"][-1]["message_metadata"]["status"] == "failed"
            )
            response = await client.post(
                "/chat",
                json={
                    "session_id": session_id,
                    "message": "你好，不需要查询资料或联网搜索，请用一句话介绍自己。",
                    "use_web_search": True,
                },
            )
            response.raise_for_status()
            result = response.json()
            checks["negation_does_not_search"] = result["metadata"][
                "route"
            ] == "direct" and not result["metadata"].get("tool_events")
            checks["general_answer_not_evidence_certified"] = (
                result["metadata"].get("verification_status") == "general_review"
            )
            response = await client.post(
                "/artifacts", json={"message_id": str(uuid.uuid4()), "format": "docx"}
            )
            checks["missing_artifact_message_404"] = response.status_code == 404
            response = await client.post(
                "/artifacts", json={"message_id": result["metadata"]["message_id"], "format": "exe"}
            )
            checks["invalid_export_format_422"] = response.status_code == 422
            response = await client.get(f"/sessions/{session_id}/messages")
            response.raise_for_status()
            user_id = next(m["id"] for m in response.json()["items"] if m["role"] == "user")
            response = await client.post(
                "/artifacts", json={"message_id": user_id, "format": "docx"}
            )
            checks["user_message_export_409"] = response.status_code == 409
        except Exception as exc:
            report["error"] = str(exc)[:300]
            raise
        finally:
            if session_id:
                response = await client.delete(f"/sessions/{session_id}")
                checks["own_session_deleted"] = response.status_code == 204
                checks["deleted_session_404"] = (
                    await client.get(f"/sessions/{session_id}")
                ).status_code == 404
            output = Path("evaluation/boundary-report.json")
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=True))
    if not all(checks.values()):
        raise RuntimeError("边界验收未全部通过")


if __name__ == "__main__":
    asyncio.run(main())
