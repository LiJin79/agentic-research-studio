import asyncio
import json

from app.agents.graph import build_agent_graph
from app.llm.base import ChatMessage
from app.llm.factory import MockLLMClient
from app.vector.retrieval import RetrievedChunk


class ScenarioLLM(MockLLMClient):
    """按提示词标记返回固定结果，专门验证图的控制流。"""

    provider_name = "test"

    def __init__(self, route: str) -> None:
        """route 决定 supervisor 在本测试中选择哪个分支。"""
        self.route = route

    async def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        """为 supervisor、writer 和 verifier 返回可预测内容。"""
        prompt = messages[-1].content
        if "ROUTE_DECISION" in prompt:
            return json.dumps({"route": self.route, "reason": "test route"})
        if "VERIFY_ANSWER" in prompt:
            return json.dumps({"supported": True, "feedback": "ok"})
        return "图生成的最终答案"

    async def stream(self, messages):
        """模拟上游增量协议；内部研究回答必须携带真实引用编号。"""
        yield "图生成的最终答案"
        if self.route != "direct":
            yield " [K1]"


class ScenarioRetriever:
    """避免连接 Qdrant 的测试检索器。"""

    async def search(self, query: str, *, limit: int | None = None) -> list[RetrievedChunk]:
        """返回一条固定知识库证据。"""
        import uuid

        return [
            RetrievedChunk(
                document_id=uuid.uuid4(),
                filename="guide.md",
                chunk_index=0,
                content=f"与 {query} 相关的证据",
                score=0.9,
            )
        ]


def test_direct_route_skips_retrieval() -> None:
    """direct 分支应从 supervisor 直接进入 writer 和 verifier。"""

    async def scenario() -> None:
        graph = build_agent_graph(llm=ScenarioLLM("direct"), retriever=ScenarioRetriever())
        result = await graph.ainvoke(
            {"question": "你好", "history": [], "context": [], "sources": [], "trace": []}
        )

        assert result["answer"] == "图生成的最终答案"
        assert [step["node"] for step in result["trace"]] == [
            "supervisor",
            "answer_writer",
            "citation_verifier",
        ]

    asyncio.run(scenario())


def test_knowledge_route_adds_retrieval_source() -> None:
    """knowledge 分支应把检索片段传递给 writer，并输出引用来源。"""

    async def scenario() -> None:
        graph = build_agent_graph(llm=ScenarioLLM("knowledge"), retriever=ScenarioRetriever())
        result = await graph.ainvoke(
            {"question": "解释 RAG", "history": [], "context": [], "sources": [], "trace": []}
        )

        assert result["sources"][0]["title"] == "guide.md"
        assert result["sources"][0]["source_type"] == "knowledge"
        assert any(step["node"] == "knowledge_researcher" for step in result["trace"])

    asyncio.run(scenario())
