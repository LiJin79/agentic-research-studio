"""Run HTTP acceptance; cloud validation requires actual configured credentials."""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import get_settings  # noqa: E402


def wait_ready(client: httpx.Client, document_id: str) -> dict:
    """轮询后台入库到终态，失败立即输出可追踪错误。"""
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/documents/{document_id}")
        response.raise_for_status()
        document = response.json()
        if document["status"] == "ready":
            return document
        if document["status"] == "failed":
            raise RuntimeError(document["error_message"])
        time.sleep(1)
    raise TimeoutError("文档入库未在验收时间内完成")


def main() -> None:
    """验收后台队列、检索、原生工具路径、SSE、幂等与持久历史，最后清理自建数据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--output", default="evaluation/http-report.json")
    args = parser.parse_args()
    token = get_settings().app_access_token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    results, document_id, session_id = {}, None, None
    with httpx.Client(
        base_url=args.base_url, timeout=360, headers=headers, trust_env=False
    ) as client:
        client.get("/api/v1/health/ready").raise_for_status()
        runtime = client.get("/api/v1/runtime").json()
        if not runtime["llm_configured"] or not runtime["embedding_configured"]:
            raise RuntimeError("需要先补齐生成与向量 API Key；此脚本不会自动退回演示模式")
        try:
            created = client.post(
                "/api/v1/sessions", json={"title": "自动验收-" + str(uuid.uuid4())[:8]}
            )
            created.raise_for_status()
            session_id = created.json()["id"]
            data = (
                "验收文档：员工应在出差结束后30日内提交报销申请。财务应在5个工作日内完成审核。"
                + "\n本次自动验收标识："
                + str(uuid.uuid4())
            )
            uploaded = client.post(
                "/api/v1/documents/upload",
                files={
                    "file": (
                        "acceptance-" + str(uuid.uuid4()) + ".txt",
                        data.encode("utf-8"),
                        "text/plain",
                    )
                },
            )
            assert uploaded.status_code == 202, uploaded.text
            document_id = uploaded.json()["document"]["id"]
            document = wait_ready(client, document_id)
            results["ingestion"] = {
                "status": document["status"],
                "chunks": document["document_metadata"]["chunk_count"],
            }
            retrieval = client.post(
                "/api/v1/documents/search/test", json={"query": "报销申请期限", "limit": 5}
            )
            retrieval.raise_for_status()
            assert any(x["document_id"] == document_id for x in retrieval.json()), retrieval.text
            request_id = str(uuid.uuid4())
            payload = {
                "session_id": session_id,
                "request_id": request_id,
                "message": "请根据文档说明员工应在多少日内提交报销申请，并引用依据。",
                "use_web_search": False,
            }
            events, done = [], None
            with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
                response.raise_for_status()
                name = ""
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        name = line[6:].strip()
                    if line.startswith("data:"):
                        body = json.loads(line[5:].strip())
                        events.append(name)
                        if name == "error":
                            raise RuntimeError(body["message"])
                        if name == "done":
                            done = body
            assert done and "tool_start" in events and "tool_end" in events and "token" in events, (
                events
            )
            assert done["sources"], done
            assert done["provider"] == runtime["llm_provider"]
            results["chat"] = {
                "provider": done["provider"],
                "route": done["metadata"]["route"],
                "verified": done["metadata"]["verified"],
                "events": events,
                "answer": done["answer"],
            }
            # 幂等重复请求不应新增任何消息。
            repeated = client.post("/api/v1/chat", json=payload)
            repeated.raise_for_status()
            assert repeated.json()["answer"] == done["answer"]
            history = client.get(f"/api/v1/sessions/{session_id}/messages").json()
            assert history["total"] == 2, history
            results["idempotency"] = "passed"
            # 同一个幂等 ID 只代表同一个请求，不能拿它提交新的问题。
            changed = client.post("/api/v1/chat", json=payload | {"message": "这个问题已经改变"})
            assert changed.status_code == 409, changed.text
            results["idempotency_conflict"] = "passed"
            followup = client.post(
                "/api/v1/chat",
                json=payload | {"request_id": str(uuid.uuid4()), "message": "你好"},
            )
            followup.raise_for_status()
            # 直接回答不应继承上一轮知识库查询的 context、sources 或研究 trace。
            assert followup.json()["metadata"]["route"] == "direct", followup.text
            assert followup.json()["sources"] == [], followup.text
            assert all(
                item["node"] not in {"knowledge_researcher", "web_researcher", "parallel_research"}
                for item in followup.json()["trace"]
            ), followup.text
            results["state_reset"] = "passed"
            memory_code = "MEM-" + uuid.uuid4().hex[:8]
            remembered = client.post(
                "/api/v1/chat",
                json=payload
                | {
                    "request_id": str(uuid.uuid4()),
                    "message": (
                        f"我的会话测试代号是 {memory_code}，"
                        "请记住，只回复已记住，不用联网。"
                    ),
                },
            )
            remembered.raise_for_status()
            recalled = client.post(
                "/api/v1/chat",
                json=payload
                | {
                    "request_id": str(uuid.uuid4()),
                    "message": "刚才我告诉你的会话测试代号是什么？不要查询资料，不要联网。",
                },
            )
            recalled.raise_for_status()
            assert memory_code in recalled.json()["answer"], recalled.text
            assert not recalled.json()["metadata"].get("tool_events"), recalled.text
            results["conversation_memory"] = "passed"
            hybrid = client.post(
                "/api/v1/chat",
                json=payload
                | {
                    "request_id": str(uuid.uuid4()),
                    "use_web_search": True,
                    "message": (
                        "请结合知识库里的验收文档和网页搜索 site:fastapi.tiangolo.com FastAPI："
                        "分别给出文档规定的报销期限和 FastAPI 的一句话介绍，引用两种来源。"
                    ),
                },
            )
            hybrid.raise_for_status()
            combined = hybrid.json()
            assert combined["metadata"]["route"] == "hybrid", hybrid.text
            assert {s["source_type"] for s in combined["sources"]} == {"knowledge", "web"}, (
                hybrid.text
            )
            tool_names = {t["name"] for t in combined["metadata"].get("tool_events", [])}
            assert {"search_knowledge", "search_web"} <= tool_names, hybrid.text
            results["hybrid_tools"] = {"result": "passed", "tools": sorted(tool_names)}
            download = client.get(f"/api/v1/documents/{document_id}/download")
            assert download.content == data.encode("utf-8")
            results["download"] = "passed"
            results["mode"] = "demo" if runtime["demo"] else "cloud"
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {"mode": results["mode"], "checks": list(results), "output": args.output},
                    ensure_ascii=False,
                )
            )
        finally:
            if document_id:
                client.delete(f"/api/v1/documents/{document_id}").raise_for_status()
            if session_id:
                client.delete(f"/api/v1/sessions/{session_id}").raise_for_status()


if __name__ == "__main__":
    main()
