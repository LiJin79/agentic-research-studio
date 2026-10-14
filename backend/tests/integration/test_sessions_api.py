import asyncio
import time
import uuid

import pytest
from app.agents.graph import build_agent_graph
from app.cache.redis import close_redis
from app.core.config import get_settings
from app.db.checkpointer import close_checkpointer
from app.db.models import Message
from app.llm.factory import MockLLMClient
from app.main import app
from app.services.session_service import SessionService
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration


def test_session_lifecycle_against_postgres() -> None:
    """Exercise the HTTP, service, repository, and PostgreSQL layers together."""
    title = f"integration-{uuid.uuid4()}"

    with TestClient(app) as client:
        create_response = client.post("/api/v1/sessions", json={"title": title})
        assert create_response.status_code == 201
        created = create_response.json()
        session_id = created["id"]

        get_response = client.get(f"/api/v1/sessions/{session_id}")
        assert get_response.status_code == 200
        assert get_response.json()["title"] == title

        # 改名会更新数据库时间；响应序列化不能尝试隐式异步 I/O。
        renamed = client.patch(f"/api/v1/sessions/{session_id}", json={"title": title + "-renamed"})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["title"] == title + "-renamed"
        assert renamed.json()["updated_at"]

        list_response = client.get("/api/v1/sessions", params={"limit": 100})
        assert list_response.status_code == 200
        assert any(item["id"] == session_id for item in list_response.json()["items"])

        messages_response = client.get(f"/api/v1/sessions/{session_id}/messages")
        assert messages_response.status_code == 200
        assert messages_response.json()["items"] == []

        delete_response = client.delete(f"/api/v1/sessions/{session_id}")
        assert delete_response.status_code == 204

        missing_response = client.get(f"/api/v1/sessions/{session_id}")
        assert missing_response.status_code == 404


def test_unknown_user_cannot_own_a_session() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sessions",
            json={"title": "Invalid owner", "user_id": str(uuid.uuid4())},
        )

    assert response.status_code == 404
    assert "User" in response.json()["detail"]


def test_service_persists_messages_and_database_cascades_deletion() -> None:
    async def scenario() -> None:
        # A dedicated engine keeps this async test isolated from TestClient's event loop.
        engine = create_async_engine(get_settings().postgres_dsn, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with factory() as database:
                service = SessionService(database)
                chat_session = await service.create_session(
                    title="Message persistence verification",
                    user_id=None,
                )
                session_id = chat_session.id

                await service.append_message(
                    session_id=session_id,
                    role="user",
                    content="What is Agentic RAG?",
                )
                messages, total = await service.list_messages(
                    session_id=session_id,
                    limit=20,
                    offset=0,
                )
                assert total == 1
                assert messages[0].content == "What is Agentic RAG?"

                await service.delete_session(session_id)
                remaining = await database.scalar(
                    select(func.count(Message.id)).where(Message.session_id == session_id)
                )
                assert remaining == 0
        finally:
            await close_checkpointer()
            await close_redis()
            await engine.dispose()

    asyncio.run(scenario())


def test_document_to_agentic_rag_lifecycle(monkeypatch) -> None:
    """Exercise upload, Qdrant retrieval, LangGraph chat, persistence, and cleanup."""
    # 生成模型必须显式替换，不能依赖学习者的 .env 恰好处于 mock 模式。
    # 向量入库仍由当前部署的 worker 完成，因此使用该部署的 Embedding 配置。
    llm = MockLLMClient()
    monkeypatch.setattr("app.services.chat_service.get_llm_client", lambda: llm)
    monkeypatch.setattr(
        "app.services.chat_service.get_agent_graph",
        lambda saver: build_agent_graph(checkpointer=saver, llm=llm),
    )
    with TestClient(app) as client:
        session_response = client.post(
            "/api/v1/sessions",
            json={"title": f"Full RAG integration-{uuid.uuid4().hex[:8]}"},
        )
        assert session_response.status_code == 201
        session_id = session_response.json()["id"]
        document_id, owns_document = None, False
        try:
            upload_response = client.post(
                "/api/v1/documents/upload",
                files={
                    "file": (
                        "agent-guide.txt",
                        "Agentic RAG combines retrieval, graph routing, and answer verification.",
                        "text/plain",
                    )
                },
            )
            assert upload_response.status_code == 202
            document_id = upload_response.json()["document"]["id"]
            owns_document = not upload_response.json().get("deduplicated", False)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                document = client.get(f"/api/v1/documents/{document_id}").json()
                if document["status"] in {"ready", "failed"}:
                    break
                time.sleep(1)
            assert document["status"] == "ready", document
            retrieval_response = client.post(
                "/api/v1/documents/search/test",
                json={"query": "Agentic RAG", "limit": 3},
            )
            assert retrieval_response.status_code == 200
            assert any(item["document_id"] == document_id for item in retrieval_response.json())
            chat_response = client.post(
                "/api/v1/chat",
                json={
                    "session_id": session_id,
                    "message": "请根据文档解释 Agentic RAG",
                    "use_web_search": False,
                },
            )
            assert chat_response.status_code == 200
            assert chat_response.json()["provider"] == "mock"
            assert chat_response.json()["sources"]
            messages_response = client.get(f"/api/v1/sessions/{session_id}/messages")
            assert messages_response.status_code == 200
            assert messages_response.json()["total"] == 2
        finally:
            # 不管断言成功与否都清理本次会话，复用别人的文档时不能删原件。
            if document_id and owns_document:
                assert client.delete(f"/api/v1/documents/{document_id}").status_code == 204
            assert client.delete(f"/api/v1/sessions/{session_id}").status_code == 204
