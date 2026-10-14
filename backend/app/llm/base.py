from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ChatMessage:
    """可往返传输 tool_calls 和 tool_call_id 的供应商无关消息。"""

    role: str
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    reasoning_content: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """仅发送协议接受的字段；工具观察与调用通过 id 配对。"""
        value: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            value["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            value["tool_call_id"] = self.tool_call_id
        if self.reasoning_content is not None:
            value["reasoning_content"] = self.reasoning_content
        return value


class BaseLLMClient(ABC):
    """所有模型客户端必须遵守的最小异步接口。"""

    provider_name: str

    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = False,
    ) -> str:
        """把消息发给模型并返回纯文本；json_mode 请求结构化 JSON。"""

    async def chat(
        self, messages: list[ChatMessage], *, tools: list[dict], tool_choice: str | dict = "auto"
    ) -> ChatMessage:
        """供应商实现原生工具协议，研究节点通过该方法让模型选择工具。"""
        raise LLMProviderError("当前模型客户端不支持工具调用")

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """供应商实现逐增量读取，禁止将完整答案事后切片伪装成流。"""
        raise LLMProviderError("当前模型客户端不支持流式输出")
        yield ""


class LLMProviderError(RuntimeError):
    """表示上游模型不可用、超时或返回了无法解析的数据。"""
