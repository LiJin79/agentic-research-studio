import asyncio
import json
import uuid

import httpx
import pytest
from app.agents.evidence import citation_errors, merge_evidence
from app.agents.graph import build_agent_graph
from app.core.config import get_settings
from app.llm.base import ChatMessage, LLMProviderError
from app.llm.factory import MockLLMClient, OpenAICompatibleLLMClient
from app.vector.embeddings import OpenAICompatibleEmbeddingClient
from app.vector.retrieval import RetrievedChunk


class FakeRetriever:
    """返回可追溯资料，图测试不依赖外部服务。"""

    async def search(self, query, **kwargs):
        """返回单条内部命中用于检验工具观察与引用。"""
        return [RetrievedChunk(uuid.uuid4(), "policy.txt", 0, "报销期限为30日。", 0.9)]


class InvalidVerifier(MockLLMClient):
    """校验输出无效时必须修订并标记不可靠。"""

    async def generate(self, messages, *, json_mode=False):
        """让每次验证都返回无法接受的布尔字符串。"""
        if "VERIFY_ANSWER" in messages[-1].content:
            return '{"supported":"false","feedback":"bad"}'
        return await super().generate(messages, json_mode=json_mode)


def test_invalid_verification_is_bounded_and_not_accepted(monkeypatch):
    """验证失败进入修订，并在上限处结束；最终保持 verified=false。"""
    monkeypatch.setattr(get_settings(), "agent_max_revisions", 2)

    async def scenario():
        """执行整个图检查真实路由与状态。"""
        graph = build_agent_graph(llm=InvalidVerifier(), retriever=FakeRetriever())
        result = await graph.ainvoke(
            {
                "question": "你好",
                "history": [],
                "use_web_search": False,
                "context": [],
                "sources": [],
                "trace": [],
                "revision_count": 0,
            }
        )
        assert result["answer_supported"] is False
        assert result["revision_count"] == 2
        assert sum(x["node"] == "citation_verifier" for x in result["trace"]) == 3

    asyncio.run(scenario())


def test_domestic_search_protocol(monkeypatch):
    """验证国内博查请求头与响应映射，不向真实服务发送请求。"""
    from app.agents.tools import web_search

    settings = get_settings()
    monkeypatch.setattr(settings, "web_search_provider", "bocha")
    monkeypatch.setattr(settings, "bocha_api_key", "test-only")
    seen = {}

    async def fake_post(url, *, payload, headers):
        """供应商格式的假响应仅检验协议转换。"""
        seen.update(url=url, payload=payload, headers=headers)
        return {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {"name": "source", "url": "https://example.com", "summary": "evidence"}
                    ]
                }
            },
        }

    monkeypatch.setattr(web_search, "post_json", fake_post)
    result = asyncio.run(web_search.search_web("query"))
    assert result[0].content == "evidence"
    assert result[0].score is None
    assert seen["headers"]["Authorization"] == "Bearer test-only"
    assert seen["payload"]["query"] == "query"


def test_hybrid_research_collects_both_tool_sources(monkeypatch):
    """混合路线运行两位独立研究员；联网关闭时应退回知识库路线。"""
    from app.agents.subgraphs import research
    from app.agents.tools.web_search import WebSearchResult

    async def fake_search(query):
        """提供独立网页结果，使测试没有外部依赖。"""
        return [WebSearchResult("web", "https://example.com/report", "web evidence", 0.9)]

    async def no_cache(key, fetch):
        """隔离 Redis 以验证图本身的并发汇合。"""
        return await fetch()

    monkeypatch.setattr(research, "search_web", fake_search)
    monkeypatch.setattr(research, "cached_search", no_cache)

    class HybridLLM(MockLLMClient):
        """固定选择 hybrid，用于测试权限保护和子图汇合。"""

        async def generate(self, messages, *, json_mode=False):
            """只有路由固定，其他节点仍采用测试供应商实现。"""
            if "ROUTE_DECISION" in messages[-1].content:
                return '{"route":"hybrid","reason":"test"}'
            return await super().generate(messages, json_mode=json_mode)

    async def scenario():
        """分别验证联网允许和禁止两种状态。"""
        graph = build_agent_graph(llm=HybridLLM(), retriever=FakeRetriever())
        initial = {
            "question": "对比资料",
            "history": [],
            "trace": [],
            "context": [],
            "sources": [],
            "revision_count": 0,
            "use_web_search": True,
        }
        result = await graph.ainvoke(initial)
        assert {s["source_type"] for s in result["sources"]} == {"knowledge", "web"}
        assert any(s["node"] == "parallel_research" for s in result["trace"])
        denied = await graph.ainvoke(initial | {"use_web_search": False})
        assert denied["route"] == "knowledge"
        assert all(s["source_type"] == "knowledge" for s in denied["sources"])

    asyncio.run(scenario())


def test_ollama_tool_result_keeps_native_tool_name():
    """本地适配器将统一调用 id 转换为 Ollama tool_name 观察。"""
    from app.llm.factory import OllamaLLMClient

    client = OllamaLLMClient(base_url="http://test", model="qwen3", timeout=2, temperature=0.2)
    messages = [
        ChatMessage(
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "id1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query":"x"}'},
                }
            ],
        ),
        ChatMessage("tool", "result", tool_call_id="id1"),
    ]
    payload = client._payload(messages)
    assert payload["messages"][0]["tool_calls"][0]["function"]["arguments"] == {"query": "x"}
    assert payload["messages"][1]["tool_name"] == "search"


def test_blank_question_is_rejected():
    """Swagger 或外部客户端也不能提交纯空白问题。"""
    from app.schemas.chat import ChatRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ChatRequest(session_id=uuid.uuid4(), message="  ")


def test_tool_events_and_true_stream_are_emitted():
    """工具事件必须在 token 前出现，文字增量在图结束前被消费。"""

    async def scenario():
        """读取 LangGraph custom 流并检查事件顺序。"""
        events = []
        graph = build_agent_graph(llm=MockLLMClient(), retriever=FakeRetriever())
        async for mode, value in graph.astream(
            {
                "question": "根据文档介绍 RAG",
                "history": [],
                "use_web_search": False,
                "context": [],
                "sources": [],
                "trace": [],
                "revision_count": 0,
            },
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom":
                events.append(value)
        names = [e["event"] for e in events]
        assert names.index("tool_start") < names.index("tool_end") < names.index("token")
        assert any(e["event"] == "tool_end" and "1" in e["data"]["detail"] for e in events)

    asyncio.run(scenario())


def test_evidence_deduplication_and_limits(monkeypatch):
    """同一网页去掉 fragment 后去重，危险 URL 和超出预算资料被过滤。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "context_max_characters", 20)
    monkeypatch.setattr(settings, "evidence_max_characters", 10)
    values = [
        {
            "source_type": "web",
            "title": "A",
            "snippet": "x" * 100,
            "url": "https://example.com/a#x",
        },
        {"source_type": "web", "title": "B", "snippet": "same", "url": "https://example.com/a#y"},
        {"source_type": "web", "title": "bad", "snippet": "bad", "url": "javascript:alert(1)"},
    ]
    result = merge_evidence(values)
    assert len(result) == 1
    assert result[0]["citation_id"] == "W1"
    assert len(result[0]["snippet"]) == 10
    assert citation_errors("错误引用 [K9]", result, "web")


def test_cloud_adapter_sends_tools_and_parses_stream(monkeypatch):
    """以本地 HTTP 假响应检验真实云适配器协议，不把它称为云端验证。"""
    seen = []

    def handler(request):
        """捕获原生工具请求并提供供应商格式的 SSE。"""
        body = json.loads(request.content)
        seen.append(body)
        if body.get("stream"):
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
                "data: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "type": "function",
                                    "function": {"name": "search", "arguments": '{"query":"x"}'},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def scenario():
        """同一适配器分别测试工具与增量接口。"""
        client = OpenAICompatibleLLMClient(
            provider="dashscope",
            base_url="https://test/v1",
            api_key="test-key",
            model="test",
            timeout=2,
            temperature=0.2,
        )
        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        reply = await client.chat([ChatMessage("user", "x")], tools=tools)
        assert reply.tool_calls[0]["id"] == "t1"
        text = [part async for part in client.stream([ChatMessage("user", "x")])]
        assert text == ["a", "b"]
        assert seen[0]["tools"] == tools
        assert seen[0]["enable_thinking"] is False

    asyncio.run(scenario())


def test_missing_cloud_key_is_explicit():
    """默认真实服务缺少密钥时立即提示，不自动退回 mock。"""

    async def scenario():
        """确认网络请求之前已经校验凭据。"""
        client = OpenAICompatibleLLMClient(
            provider="dashscope",
            base_url="https://test",
            api_key="",
            model="test",
            timeout=2,
            temperature=0.2,
        )
        with pytest.raises(LLMProviderError, match="LLM_API_KEY"):
            await client.generate([ChatMessage("user", "x")])

    asyncio.run(scenario())


def test_truncated_upstream_stream_is_not_success(monkeypatch):
    """HTTP 正常结束但缺少模型终止帧时，已收到的内容只能作为失败草稿。"""

    def handler(request):
        """给出一条增量后直接 EOF，模拟代理截断。"""
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def scenario():
        """先收到草稿，再收到明确失败，不能默默返回成功。"""
        client = OpenAICompatibleLLMClient(
            provider="dashscope",
            base_url="https://test",
            api_key="test",
            model="test",
            timeout=2,
            temperature=0.2,
        )
        chunks = []
        with pytest.raises(LLMProviderError, match="提前结束"):
            async for part in client.stream([ChatMessage("user", "x")]):
                chunks.append(part)
        assert chunks == ["partial"]

    asyncio.run(scenario())


def test_sse_disconnect_closes_backpressured_service():
    """浏览器退出时，即使生产者卡在已满队列，也必须关闭内部生成器。"""
    from app.api.v1.chat import stream_chat
    from app.schemas.chat import ChatRequest

    class FastService:
        """快速产生数据以稳定触发队列背压，无需数据库或收费模型。"""

        closed = False

        async def stream(self, **kwargs):
            """模拟持有资源的服务生成器，以 finally 检验关闭传播。"""
            try:
                for _ in range(100):
                    yield {"event": "token", "data": {"content": "x"}}
                await asyncio.Event().wait()
            finally:
                self.closed = True

    async def scenario():
        """只读取一帧，让队列填满后主动关闭 HTTP 响应生成器。"""
        service = FastService()
        response = await stream_chat(ChatRequest(session_id=uuid.uuid4(), message="test"), service)
        await anext(response.body_iterator)
        await asyncio.sleep(0.05)
        await response.body_iterator.aclose()
        assert service.closed

    asyncio.run(scenario())


def test_embedding_batches_and_validates_dimensions(monkeypatch):
    """超过十段文本正确分批，并将每批结果恢复为输入顺序。"""
    sizes = []

    def handler(request):
        """模拟供应商乱序响应，要求客户端按 index 恢复顺序。"""
        body = json.loads(request.content)
        sizes.append(len(body["input"]))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [float(i), 1.0]}
                    for i in reversed(range(len(body["input"])))
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def scenario():
        """批量输出维度和数量都必须一致。"""
        client = OpenAICompatibleEmbeddingClient(
            base_url="https://test/v1", api_key="test", model="test", dimensions=2, timeout=2
        )
        result = await client.embed(["text"] * 23)
        assert sizes == [10, 10, 3]
        assert len(result) == 23
        assert result[1] == [1.0, 1.0]

    asyncio.run(scenario())


def test_embedding_factory_keeps_custom_workspace_url(monkeypatch):
    """百炼地域和工作空间地址由用户配置决定，不被供应商名称覆盖。"""
    from app.vector.embeddings import get_embedding_client

    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "dashscope")
    monkeypatch.setattr(settings, "embedding_base_url", "https://workspace.example/v1")
    get_embedding_client.cache_clear()
    try:
        assert get_embedding_client().base_url == "https://workspace.example/v1"
    finally:
        get_embedding_client.cache_clear()


def test_ollama_embedding_checks_every_vector(monkeypatch):
    """第二条向量维度错误也必须拒绝，不能仅检查第一条。"""
    from app.vector import embeddings

    async def fake_post(url, *, payload):
        """返回首条正确、第二条错误的本地协议测试数据。"""
        return {"embeddings": [[1.0, 0.0], [1.0]]}

    monkeypatch.setattr(embeddings, "post_json", fake_post)
    client = embeddings.OllamaEmbeddingClient(
        base_url="http://test", model="test", dimensions=2, timeout=2
    )
    with pytest.raises(ValueError, match="Ollama Embedding"):
        asyncio.run(client.embed(["first", "second"]))
