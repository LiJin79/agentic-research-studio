import json
from collections.abc import Callable
from typing import TypedDict

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.prompts import RESEARCH_SYSTEM_PROMPT
from app.agents.search_policy import domain_matches, requested_domains
from app.agents.tools.registry import extra_tools
from app.agents.tools.web_search import search_web
from app.cache.coordination import cached_search, search_cache_key
from app.core.config import get_settings
from app.llm.base import BaseLLMClient, ChatMessage, LLMProviderError
from app.vector.retrieval import KnowledgeRetriever


class SearchInput(BaseModel):
    """工具参数由 Pydantic 校验，模型不能传递无限长搜索词。"""

    query: str = Field(min_length=1, max_length=500, description="精炼的检索问题或关键词")


class ResearchState(TypedDict, total=False):
    """每位研究员有独立消息、工具结果和轮次，不共享可变列表。"""

    question: str
    messages: list[dict]
    evidence: list[dict]
    iterations: int
    pending_calls: list[dict]
    tool_events: list[dict]
    failures: list[str]
    calls_used: int


class ResearchAgent:
    """受限 ReAct 子图：模型提出工具调用，执行器返回观察，再由模型判断。"""

    def __init__(
        self,
        llm: BaseLLMClient,
        kind: str,
        retriever: KnowledgeRetriever,
        emit: Callable[[dict], None],
        domains: list[str] | None = None,
        question: str = "",
    ) -> None:
        """只提供本角色允许的工具；网页研究员无法绕过联网开关。"""
        self.llm, self.kind, self.retriever, self.emit = llm, kind, retriever, emit
        self.domains = domains or []
        self.tool = StructuredTool.from_function(
            coroutine=self._search,
            name="search_knowledge" if kind == "knowledge" else "search_web",
            description="检索内部文档原文片段" if kind == "knowledge" else "搜索最新互联网资料",
            args_schema=SearchInput,
        )
        self.tools_by_name = {
            tool.name: tool for tool in [self.tool, *extra_tools(kind, question, self.domains)]
        }

    async def _search(self, query: str) -> list[dict]:
        """执行真实搜索并统一证据形状，所有上游结果都保留可追溯来源。"""
        if self.kind == "knowledge":
            hits = await self.retriever.search(query)
            return [
                {
                    "source_type": "knowledge",
                    "title": h.filename,
                    "snippet": h.content,
                    "score": h.score,
                    "document_id": str(h.document_id),
                    "chunk_index": h.chunk_index,
                    "url": None,
                }
                for h in hits
            ]

        async def fetch() -> list[dict]:
            """只缓存实际联网结果，缓存缺失时调用外部搜索 API。"""
            domains = self.domains or requested_domains(query)
            hits = (
                await search_web(query, include_domains=domains)
                if domains
                else await search_web(query)
            )
            return [
                {
                    "source_type": "web",
                    "title": h.title,
                    "snippet": h.content,
                    "score": h.score,
                    "url": h.url,
                    "document_id": None,
                    "content_kind": "search_summary",
                }
                for h in hits
                if domain_matches(h.url, domains)
            ]

        # 限定域名必须属于缓存键；不能复用以前不受限制的网页结果。
        domains = self.domains or requested_domains(query)
        key = search_cache_key("web-v2", json.dumps([query, domains], ensure_ascii=False))
        results = await cached_search(key, fetch)
        return [r for r in results if domain_matches(r.get("url") or "", domains)]

    async def model(self, state: ResearchState) -> dict:
        """将工具 Schema 发给模型，并保存模型原始 tool_calls 供执行节点匹配。"""
        messages = state.get("messages") or [
            {
                "role": "system",
                "content": RESEARCH_SYSTEM_PROMPT.format(
                    role="内部文档研究员" if self.kind == "knowledge" else "网页研究员",
                    max_iterations=get_settings().agent_max_tool_iterations,
                    domains=", ".join(self.domains) if self.domains else "未限定",
                ),
            },
            {"role": "user", "content": state["question"]},
        ]
        response = await self.llm.chat(
            [
                ChatMessage(
                    m["role"],
                    m.get("content") or "",
                    m.get("tool_calls") or [],
                    m.get("tool_call_id"),
                    reasoning_content=m.get("reasoning_content"),
                )
                for m in messages
            ],
            tools=[convert_to_openai_tool(tool) for tool in self.tools_by_name.values()],
            tool_choice={"type": "function", "function": {"name": self.tool.name}}
            if state.get("iterations", 0) == 0
            else "auto",
        )
        if not response.tool_calls and state.get("iterations", 0) == 0:
            raise LLMProviderError("研究模型没有执行必需的搜索工具，不能声称已经搜索")
        return {
            "messages": messages + [response.to_dict()],
            "pending_calls": response.tool_calls,
            "iterations": state.get("iterations", 0) + 1,
        }

    async def tools(self, state: ResearchState) -> dict:
        """逐个校验白名单工具和参数，将观察与每个 tool_call_id 正确配对。"""
        observations, evidence = [], list(state.get("evidence", []))
        events = list(state.get("tool_events", []))
        failures, calls_used = list(state.get("failures", [])), state.get("calls_used", 0)
        # 控制单轮并行工具数量；拒绝额外调用仍提供配对的错误观察。
        for index, call in enumerate(state.get("pending_calls", [])):
            function = call.get("function") or {}
            name, call_id = function.get("name"), str(call.get("id") or f"invalid-{index}")
            self.emit({"event": "tool_start", "data": {"name": name, "agent": self.kind}})
            query = ""
            try:
                if name not in self.tools_by_name or index >= 3:
                    raise ValueError("工具不在允许列表或本轮调用次数过多")
                if calls_used >= get_settings().tool_max_calls:
                    raise ValueError("本次研究达到工具调用预算")
                calls_used += 1
                args = json.loads(function.get("arguments") or "{}")
                query = str(args.get("query") or "")
                results = await self.tools_by_name[name].ainvoke(args)
                # 工具消息和最终上下文都有边界，避免超长网页撑爆下一轮输入。
                settings = get_settings()
                results = [
                    dict(r, snippet=str(r.get("snippet", ""))[: settings.evidence_max_characters])
                    for r in results[: settings.context_max_sources]
                ]
                # 目录列表只帮助模型发现 ID，不将文件名列表冒充正文证据。
                evidence.extend(r for r in results if r.get("source_type") in {"knowledge", "web"})
                content = json.dumps({"results": results}, ensure_ascii=False)
                detail = f"获得 {len(results)} 条资料"
            except Exception as exc:
                # 上游失败不能当作“搜索成功但没有资料”，否则用户会得到虚假的未找到结论。
                detail = "工具失败：" + (str(exc) or type(exc).__name__)[:160]
                self.emit(
                    {
                        "event": "tool_end",
                        "data": {
                            "name": name,
                            "agent": self.kind,
                            "detail": detail,
                            "success": False,
                        },
                    }
                )
                failures.append(detail)
                observations.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(
                            {"success": False, "error": detail}, ensure_ascii=False
                        ),
                    }
                )
                events.append(
                    {
                        "name": name,
                        "agent": self.kind,
                        "detail": detail,
                        "success": False,
                        "result_count": 0,
                    }
                )
                continue
            observations.append({"role": "tool", "content": content, "tool_call_id": call_id})
            event = {
                "name": name,
                "agent": self.kind,
                "detail": detail,
                "query": query,
                "success": True,
                "result_count": len(results),
                "domains": self.domains,
            }
            events.append(event)
            self.emit({"event": "tool_end", "data": event})
        return {
            "messages": state["messages"] + observations,
            "evidence": evidence,
            "pending_calls": [],
            "tool_events": events,
            "failures": failures,
            "calls_used": calls_used,
        }

    def after_model(self, state: ResearchState) -> str:
        """有工具调用才进入执行器；达到轮次上限时终止研究而不无限循环。"""
        if state.get("pending_calls"):
            return "tools"
        return "finish"

    def after_tools(self, state: ResearchState) -> str:
        """允许模型根据观察改写搜索词，最多配置的模型决策轮数。"""
        return (
            "model" if state["iterations"] < get_settings().agent_max_tool_iterations else "finish"
        )

    def compile(self):
        """构建可被主图调用的独立研究子图。"""
        builder = StateGraph(ResearchState)
        builder.add_node("model", self.model)
        builder.add_node("tools", self.tools)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self.after_model, {"tools": "tools", "finish": END})
        builder.add_conditional_edges("tools", self.after_tools, {"model": "model", "finish": END})
        return builder.compile()
