"""验证已配置的通义 Flash 选择、SSE、幂等与错误边界；仅清理自身验证会话。"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402


async def main() -> None:
    """调用一次真实云端小问题，其余检查复用结果或在模型调用前被拒绝。"""
    token = get_settings().app_access_token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    report = {}
    async with httpx.AsyncClient(
        base_url="http://localhost:8001/api/v1/", headers=headers, timeout=360
    ) as client:
        runtime = await client.get("runtime")
        runtime.raise_for_status()
        catalog = runtime.json()["models"]
        assert next(item for item in catalog if item["id"] == "qwen-flash")["configured"]
        created = await client.post("sessions", json={"title": "[验证]模型切换与回答边界"})
        created.raise_for_status()
        session_id = created.json()["id"]
        try:
            payload = {
                "session_id": session_id,
                "request_id": str(uuid.uuid4()),
                "model_id": "qwen-flash",
                "use_web_search": False,
                "message": (
                    "不要联网，也不要查询知识库。请只用三句话回答："
                    "Redis是否没有事务？同一个LangGraph thread_id是否就无需并发控制？"
                    "Checkpoint是否自动等于SSE断点恢复？"
                ),
            }
            result, event, tokens = None, "", 0
            async with client.stream("POST", "chat/stream", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:])
                        if event == "error":
                            raise RuntimeError(data["message"])
                        if event == "token":
                            tokens += 1
                        if event == "done":
                            result = data
            assert result and tokens
            assert result["metadata"]["model_id"] == "qwen-flash"
            assert result["metadata"]["model"] == "qwen-flash"
            assert result["provider"] == "dashscope"
            assert result["metadata"]["route"] == "direct"
            assert not result["sources"]
            replay = await client.post("chat", json=payload)
            replay.raise_for_status()
            assert replay.json()["answer"] == result["answer"]
            conflict = await client.post("chat", json=payload | {"model_id": "qwen-plus"})
            assert conflict.status_code == 409
            messages = await client.get(f"sessions/{session_id}/messages")
            messages.raise_for_status()
            assert len(messages.json()["items"]) == 2
            unavailable = next((item for item in catalog if not item["configured"]), None)
            if unavailable:
                rejected = await client.post(
                    "chat",
                    json=payload | {"request_id": str(uuid.uuid4()), "model_id": unavailable["id"]},
                )
                assert rejected.status_code == 422
                after = await client.get(f"sessions/{session_id}/messages")
                assert len(after.json()["items"]) == 2
            report = {
                "model": result["metadata"]["model"],
                "route": "direct",
                "sse_tokens": tokens,
                "answer": result["answer"],
                "metadata_persisted": True,
                "verified": result["metadata"]["verified"],
                "verification_status": result["metadata"]["verification_status"],
                "verification_feedback": result["metadata"]["verification_feedback"],
                "revision_count": result["metadata"]["revision_count"],
                "idempotency": "passed",
                "model_change_conflict": "passed",
                "unconfigured_rejected": bool(unavailable),
            }
        finally:
            deleted = await client.delete(f"sessions/{session_id}")
            assert deleted.status_code == 204, "验证会话清理失败"
    report["own_session_deleted"] = True
    output = ROOT / "evaluation" / "model-font-controls" / "live-model.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
