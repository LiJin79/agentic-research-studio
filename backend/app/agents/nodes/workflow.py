import asyncio
import json
import re
from typing import Literal

from langgraph.config import get_stream_writer
from pydantic import BaseModel, StrictBool, ValidationError

from app.agents.evidence import citation_errors, format_evidence, merge_evidence
from app.agents.search_policy import requested_domains, requires_web_search, web_search_denied
from app.agents.state import AgentState
from app.agents.subgraphs.research import ResearchAgent
from app.llm.base import BaseLLMClient, ChatMessage, LLMProviderError
from app.vector.retrieval import KnowledgeRetriever


class RouteDecision(BaseModel):
    """路由 JSON 必须属于已实现的分支，不接受任意模型字符串。"""

    route: Literal["direct", "knowledge", "web", "hybrid"]
    reason: str


class Verification(BaseModel):
    """严格布尔校验，字符串 false 不能被 bool('false') 误判为真。"""

    supported: StrictBool
    feedback: str


def parse_decision(raw: str, schema):
    """接受 Markdown JSON 围栏但仍执行严格 schema 校验，失败交给调用方。"""
    start, end = raw.find("{"), raw.rfind("}")
    return schema.model_validate(json.loads(raw[start : end + 1]))


class AgentNodes:
    """调度员、独立研究子图、流式写作和可循环验证节点。"""

    def __init__(self, llm: BaseLLMClient, retriever: KnowledgeRetriever | None = None) -> None:
        """注入模型与检索器，测试可替换依赖而无需云密钥。"""
        self.llm, self.retriever = llm, retriever or KnowledgeRetriever()

    def emit(self, event: str, **data) -> None:
        """通过 LangGraph custom 流向前端发送公开进度，不输出隐藏推理。"""
        get_stream_writer()({"event": event, "data": data})

    def trace(self, state: AgentState, node: str, detail: str) -> list[dict]:
        """追加可展示摘要；状态字段默认替换，因此显式拼接旧 trace。"""
        self.emit("status", stage=node, message=detail)
        return state.get("trace", []) + [{"node": node, "detail": detail}]

    async def supervisor(self, state: AgentState) -> dict:
        """结合最近对话判断问题路线，禁止未经许可的联网研究。"""
        from app.agents.prompts import SUPERVISOR_PROMPT

        # 显式搜索要求优先于历史上下文；关闭权限时明确阻止，而非悄悄查询知识库。
        domains = requested_domains(state["question"])
        if requires_web_search(state["question"]):
            if not state.get("use_web_search"):
                raise LLMProviderError("本次未执行网页搜索：请开启联网搜索后发送问题")
            route = "hybrid" if re.search(r"知识库|内部文档|内部资料", state["question"]) else "web"
            reason = "当前问题明确要求网页搜索" + (
                "，限制域名：" + ", ".join(domains) if domains else ""
            )
            return {
                "route": route,
                "route_reason": reason,
                "search_domains": domains,
                "trace": self.trace(state, "supervisor", f"选择 {route}：{reason}"),
            }
        raw = await self.llm.generate(
            [
                ChatMessage(
                    "system",
                    SUPERVISOR_PROMPT.format(
                        question=state["question"],
                        use_web_search=state.get("use_web_search", False),
                        history=json.dumps(state.get("history", []), ensure_ascii=False),
                    ),
                )
            ],
            json_mode=True,
        )
        try:
            decision = parse_decision(raw, RouteDecision)
            route, reason = decision.route, decision.reason
        except (ValueError, ValidationError):
            route, reason = "knowledge", "模型决策格式无效，采用内部检索"
        if route in {"web", "hybrid"} and web_search_denied(state["question"]):
            route, reason = "direct", "当前提问明确禁止联网，不执行网页搜索"
        elif route in {"web", "hybrid"} and not state.get("use_web_search"):
            route, reason = "knowledge", "未授权联网，使用内部检索"
        return {
            "route": route,
            "route_reason": reason,
            "search_domains": domains,
            "trace": self.trace(state, "supervisor", f"选择 {route}：{reason}"),
        }

    async def _research(self, state: AgentState, kind: str) -> dict:
        """给研究员独立初始 State，用父图事件写入器展示真实工具执行。"""
        self.emit("status", stage=kind, message="检索知识库" if kind == "knowledge" else "联网研究")
        researcher = ResearchAgent(
            self.llm,
            kind,
            self.retriever,
            get_stream_writer(),
            domains=state.get("search_domains", []) if kind == "web" else [],
            question=state["question"],
        )
        result = await researcher.compile().ainvoke(
            {
                "question": state["question"],
                "messages": [],
                "evidence": [],
                "iterations": 0,
                "pending_calls": [],
                "tool_events": [],
            }
        )
        if result.get("failures") and not result.get("evidence"):
            raise LLMProviderError("研究未取得证据：" + result["failures"][-1])
        return result

    async def knowledge_researcher(self, state: AgentState) -> dict:
        """本地研究员通过模型 tool_calls 执行知识库检索。"""
        result = await self._research(state, "knowledge")
        evidence = merge_evidence(result.get("evidence", []))
        return {
            "context": evidence,
            "sources": evidence,
            "tool_events": result.get("tool_events", []),
            "trace": self.trace(state, "knowledge_researcher", f"整理 {len(evidence)} 条内部资料"),
        }

    async def web_researcher(self, state: AgentState) -> dict:
        """联网研究员通过模型工具调用执行搜索，保留真实网页地址。"""
        result = await self._research(state, "web")
        evidence = merge_evidence(result.get("evidence", []))
        return {
            "context": evidence,
            "sources": evidence,
            "tool_events": result.get("tool_events", []),
            "trace": self.trace(state, "web_researcher", f"整理 {len(evidence)} 条网页资料"),
        }

    async def parallel_research(self, state: AgentState) -> dict:
        """Hybrid 并发运行两位研究员，再按确定顺序合并，避免并发改写共享 State。"""
        knowledge, web = await asyncio.gather(
            self._research(state, "knowledge"), self._research(state, "web")
        )
        evidence = merge_evidence(knowledge.get("evidence", []) + web.get("evidence", []))
        return {
            "context": evidence,
            "sources": evidence,
            "tool_events": knowledge.get("tool_events", []) + web.get("tool_events", []),
            "trace": self.trace(state, "parallel_research", f"合并 {len(evidence)} 条去重资料"),
        }

    async def _write(self, prompt: str, *, reset: bool = False) -> str:
        """直接转发模型原始内容增量，修订开始时显式清除旧草稿。"""
        if reset:
            self.emit("answer_reset", reason="依据校验意见修订")
        chunks = []
        async for text in self.llm.stream([ChatMessage("system", prompt)]):
            chunks.append(text)
            self.emit("token", content=text)
        answer = "".join(chunks).strip()
        if not answer:
            raise LLMProviderError("模型未生成可用回答")
        return answer

    async def answer_writer(self, state: AgentState) -> dict:
        """写作节点流式输出草稿，最终可靠性要等验证节点完成。"""
        from app.agents.prompts import ANSWER_PROMPT

        self.emit("status", stage="answer_writer", message="生成回答草稿")
        if state["route"] != "direct" and not state.get("context"):
            # 零结果属于证据不足，不让模型猜测资料或复用上一轮的来源编号。
            if state["route"] == "web":
                scope = "、".join(state.get("search_domains", [])) or "当前搜索条件"
                answer = (
                    f"已执行网页搜索，但在 {scope} 范围内没有取得可用证据。"
                    "不能据此认定相关资料不存在，也不会用其他来源代替。"
                    "请调整搜索条件或上传资料。"
                )
            else:
                answer = "已执行资料检索，但没有取得可用证据，暂时无法依据资料回答这个问题。"
            self.emit("token", content=answer)
            return {
                "answer": answer,
                "trace": self.trace(state, "answer_writer", "证据不足，明确说明检索结果"),
            }
        prompt = ANSWER_PROMPT.format(
            route=state["route"],
            history=json.dumps(state.get("history", []), ensure_ascii=False),
            question=state["question"],
            context=format_evidence(state.get("context", [])),
        )
        return {
            "answer": await self._write(prompt),
            "trace": self.trace(state, "answer_writer", "回答草稿已生成"),
        }

    async def verifier(self, state: AgentState) -> dict:
        """严格校验模型判定与引用编号；无效判定触发修订，不默认放行。"""
        from app.agents.prompts import VERIFY_PROMPT

        if state["route"] != "direct" and not state.get("context"):
            return {
                "answer_supported": False,
                "verification_feedback": "本次未取得可用证据",
                "trace": self.trace(state, "citation_verifier", "证据不足，不能标记为证据校验通过"),
            }
        errors = citation_errors(state["answer"], state.get("context", []), state["route"])
        try:
            raw = await self.llm.generate(
                [
                    ChatMessage(
                        "system",
                        VERIFY_PROMPT.format(
                            route=state["route"],
                            history=json.dumps(state.get("history", []), ensure_ascii=False),
                            question=state["question"],
                            context=format_evidence(state.get("context", [])),
                            answer=state["answer"],
                        ),
                    )
                ],
                json_mode=True,
            )
            result = parse_decision(raw, Verification)
            supported, feedback = result.supported and not errors, result.feedback
        except (ValueError, ValidationError):
            supported, feedback = False, "校验模型返回无效结构，不能确认回答可靠"
        if errors:
            feedback += "；" + "；".join(errors)
        return {
            "answer_supported": supported,
            "verification_feedback": feedback,
            "trace": self.trace(
                state,
                "citation_verifier",
                ("一般回答检查通过" if state["route"] == "direct" else "证据检查通过")
                if supported
                else "需要修订：" + feedback[:120],
            ),
        }

    async def revise_answer(self, state: AgentState) -> dict:
        """根据反馈流式修订，然后返回验证节点再次检查。"""
        from app.agents.prompts import REVISE_PROMPT

        answer = await self._write(
            REVISE_PROMPT.format(
                route=state["route"],
                history=json.dumps(state.get("history", []), ensure_ascii=False),
                question=state["question"],
                context=format_evidence(state.get("context", [])),
                answer=state["answer"],
                feedback=state["verification_feedback"],
            ),
            reset=True,
        )
        count = state.get("revision_count", 0) + 1
        return {
            "answer": answer,
            "revision_count": count,
            "trace": self.trace(state, "revise_answer", f"第 {count} 次修订完成"),
        }
