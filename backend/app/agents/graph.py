from functools import lru_cache
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.workflow import AgentNodes
from app.agents.state import AgentState
from app.core.config import get_settings
from app.llm.base import BaseLLMClient
from app.llm.factory import get_llm_client
from app.vector.retrieval import KnowledgeRetriever


def _route_from_supervisor(state: AgentState) -> Literal["direct", "knowledge", "web", "hybrid"]:
    """把 supervisor 写入 state 的路线映射到下一节点。"""
    return state.get("route", "knowledge")  # type: ignore[return-value]


def _route_after_verification(state: AgentState) -> Literal["revise", "finish"]:
    """证据不足且未达到次数上限时修订，否则结束。"""
    settings = get_settings()
    if state.get("route") != "direct" and not state.get("context"):
        return "finish"  # 修订文字不能补出不存在的证据，零结果直接结束。
    needs_revision = not state.get("answer_supported", True)
    below_limit = state.get("revision_count", 0) < settings.agent_max_revisions
    if needs_revision and below_limit:
        return "revise"
    return "finish"


def build_agent_graph(
    *,
    checkpointer: Any | None = None,
    llm: BaseLLMClient | None = None,
    retriever: KnowledgeRetriever | None = None,
) -> Any:
    """声明节点和边并编译 LangGraph；测试可注入模型或省略 Checkpointer。"""
    nodes = AgentNodes(llm or get_llm_client(), retriever=retriever)
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", nodes.supervisor)
    builder.add_node("knowledge_researcher", nodes.knowledge_researcher)
    builder.add_node("web_researcher", nodes.web_researcher)
    builder.add_node("parallel_research", nodes.parallel_research)
    builder.add_node("answer_writer", nodes.answer_writer)
    builder.add_node("citation_verifier", nodes.verifier)
    builder.add_node("revise_answer", nodes.revise_answer)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "direct": "answer_writer",
            "knowledge": "knowledge_researcher",
            "web": "web_researcher",
            "hybrid": "parallel_research",
        },
    )
    builder.add_edge("knowledge_researcher", "answer_writer")
    builder.add_edge("web_researcher", "answer_writer")
    builder.add_edge("parallel_research", "answer_writer")
    builder.add_edge("answer_writer", "citation_verifier")
    builder.add_conditional_edges(
        "citation_verifier",
        _route_after_verification,
        {"revise": "revise_answer", "finish": END},
    )
    builder.add_edge("revise_answer", "citation_verifier")
    return builder.compile(checkpointer=checkpointer)


@lru_cache(maxsize=16)
def get_agent_graph(checkpointer, model_id: str | None = None):
    """模型 ID 参与图缓存键，避免不同请求错误复用另一供应商的客户端。"""
    llm = get_llm_client(model_id) if model_id else get_llm_client()
    return build_agent_graph(checkpointer=checkpointer, llm=llm)
