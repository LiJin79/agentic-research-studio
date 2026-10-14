from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """LangGraph 节点之间共享的数据；每个节点只更新自己负责的字段。"""

    question: str
    history: list[dict[str, str]]
    use_web_search: bool
    route: str
    route_reason: str
    context: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    answer: str
    verification_feedback: str
    answer_supported: bool
    revision_count: int
    trace: list[dict[str, str]]
    tool_events: list[dict[str, Any]]
    search_domains: list[str]
