import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SourceReference(BaseModel):
    """描述回答所依据的一条检索证据，供前端显示引用来源。"""

    source_type: Literal["knowledge", "web"]
    title: str
    snippet: str
    score: float | None = None
    url: str | None = None
    document_id: uuid.UUID | None = None
    citation_id: str = ""
    chunk_index: int | None = None
    # 这些字段同时保留在接口与消息记录中，避免导出时丢失证据时间和代码版本。
    content_kind: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    commit_sha: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    units: str | None = None
    truncated: bool = False


class ChatRequest(BaseModel):
    """聊天接口输入；会话 ID 决定消息和 LangGraph 状态保存到哪里。"""

    session_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)
    use_web_search: bool = False
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        """拒绝仅空白的问题，并为幂等请求使用一致的规范文本。"""
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value


class AgentTraceStep(BaseModel):
    """记录图中一个节点的可公开执行摘要，不暴露模型内部思维链。"""

    node: str
    detail: str


class ChatResponse(BaseModel):
    """一次完整 Agent 调用的最终响应。"""

    session_id: uuid.UUID
    answer: str
    sources: list[SourceReference] = Field(default_factory=list)
    trace: list[AgentTraceStep] = Field(default_factory=list)
    provider: str
    metadata: dict[str, Any] = Field(default_factory=dict)
