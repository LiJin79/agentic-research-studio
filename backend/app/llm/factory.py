import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import BaseLLMClient, ChatMessage, LLMProviderError
from app.llm.catalog import get_model_profile
from app.llm.http import post_json


class OpenAICompatibleLLMClient(BaseLLMClient):
    """通义、DeepSeek 和自定义兼容服务的原生 tools/SSE 适配器。"""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        temperature: float,
    ) -> None:
        """保存客户端参数，密钥只进入 Authorization 请求头。"""
        self.provider_name = provider
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def _payload(self, messages: list[ChatMessage], **options: Any) -> dict:
        """构造兼容消息；工具结果保持原始 id，供下一轮模型识别。"""
        if not self.api_key:
            raise LLMProviderError(f"{self.provider_name} 尚未配置 LLM_API_KEY")
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature,
            "max_tokens": get_settings().llm_max_tokens,
        }
        if self.provider_name == "dashscope":
            payload["enable_thinking"] = False
        if self.provider_name == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        if self.provider_name == "zhipu":
            payload["thinking"] = {"type": "disabled"}
        if self.provider_name == "minimax":
            # MiniMax 的思考与正文分离，内部推理只在工具协议中往返，不显示给用户。
            payload.pop("max_tokens")
            payload["max_completion_tokens"] = get_settings().minimax_max_tokens
            payload["reasoning_split"] = True
            if self.model == "MiniMax-M3":
                payload["thinking"] = {"type": "disabled"}
        return payload | options

    async def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        """获取完整文本，JSON 模式用于经过校验的结构化决策。"""
        # MiniMax 公开兼容接口未承诺 response_format；由提示词和 Pydantic 校验 JSON。
        options = (
            {"response_format": {"type": "json_object"}}
            if json_mode and self.provider_name != "minimax"
            else {}
        )
        body = await post_json(
            f"{self.base_url}/chat/completions",
            payload=self._payload(messages, **options),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            return str(body["choices"][0]["message"].get("content") or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("模型响应缺少 choices/message") from exc

    async def chat(
        self, messages: list[ChatMessage], *, tools: list[dict], tool_choice: str | dict = "auto"
    ) -> ChatMessage:
        """传递工具 JSON Schema，让模型返回真实的 function tool_calls。"""
        options = {"tools": tools}
        if self.provider_name != "minimax":
            options["tool_choice"] = tool_choice
        body = await post_json(
            f"{self.base_url}/chat/completions",
            payload=self._payload(messages, **options),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            message = body["choices"][0]["message"]
            return ChatMessage(
                "assistant",
                message.get("content") or "",
                tool_calls=message.get("tool_calls") or [],
                reasoning_content=message.get("reasoning_content"),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("工具调用响应格式不正确") from exc

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """从上游 SSE 逐增量读取，已输出后不自动重试以免产生重复答案。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=self._payload(messages, stream=True),
                    headers={"Authorization": f"Bearer {self.api_key}"},
                ) as response:
                    response.raise_for_status()
                    completed = False
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            completed = True
                            break
                        chunk = json.loads(data)
                        if chunk.get("error"):
                            raise LLMProviderError("模型流返回错误")
                        choices = chunk.get("choices", [])
                        content = choices[0].get("delta", {}).get("content") if choices else None
                        if content:
                            yield content
                    # 正常 HTTP EOF 不代表正常模型结束；缺失终止帧时草稿不能入库。
                    if not completed:
                        raise LLMProviderError("模型流提前结束，回答未完整生成")
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(f"模型流返回 HTTP {exc.response.status_code}") from exc
        except (httpx.TransportError, ValueError, KeyError, TypeError) as exc:
            raise LLMProviderError("模型流连接中断或格式无效") from exc


class OllamaLLMClient(BaseLLMClient):
    """保留本地 Ollama 的工具调用和 NDJSON 流协议，默认部署不启动它。"""

    provider_name = "ollama"

    def __init__(self, *, base_url: str, model: str, timeout: float, temperature: float) -> None:
        """保存可替换的 Ollama 模型和连接参数。"""
        self.base_url, self.model = base_url.rstrip("/"), model
        self.timeout, self.temperature = timeout, temperature

    def _payload(self, messages: list[ChatMessage], **options: Any) -> dict:
        """将兼容消息转换为 Ollama 所需的字典工具参数。"""
        tool_names = {
            call["id"]: call["function"]["name"]
            for message in messages
            for call in message.tool_calls
        }
        values = []
        for message in messages:
            value = message.to_dict()
            if message.role == "tool":
                value.pop("tool_call_id", None)
                value["tool_name"] = tool_names.get(message.tool_call_id, "")
            if message.tool_calls:
                value["tool_calls"] = [
                    {
                        "function": {
                            "name": c["function"]["name"],
                            "arguments": json.loads(c["function"]["arguments"]),
                        }
                    }
                    for c in message.tool_calls
                ]
            values.append(value)
        return {
            "model": self.model,
            "messages": values,
            "stream": False,
            "options": {"temperature": self.temperature},
        } | options

    async def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        """调用本地完整生成；需要结构化结果时要求 JSON 格式。"""
        body = await post_json(
            f"{self.base_url}/api/chat",
            payload=self._payload(messages, **({"format": "json"} if json_mode else {})),
        )
        return str(body.get("message", {}).get("content") or "")

    async def chat(
        self, messages: list[ChatMessage], *, tools: list[dict], tool_choice: str | dict = "auto"
    ) -> ChatMessage:
        """将 Ollama 工具调用转换为统一协议，同时生成可匹配的调用 id。"""
        import uuid

        body = await post_json(
            f"{self.base_url}/api/chat", payload=self._payload(messages, tools=tools)
        )
        message = body.get("message", {})
        calls = [
            {
                "id": str(uuid.uuid4()),
                "type": "function",
                "function": {
                    "name": c["function"]["name"],
                    "arguments": json.dumps(c["function"]["arguments"], ensure_ascii=False),
                },
            }
            for c in message.get("tool_calls", [])
        ]
        return ChatMessage("assistant", message.get("content") or "", tool_calls=calls)

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """逐行解码 Ollama JSON 流，传回真实内容增量。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/chat", json=self._payload(messages, stream=True)
                ) as response:
                    response.raise_for_status()
                    completed = False
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise LLMProviderError("Ollama 返回错误，请检查模型是否下载")
                        text = chunk.get("message", {}).get("content")
                        if text:
                            yield text
                        if chunk.get("done"):
                            completed = True
                            break
                    if not completed:
                        raise LLMProviderError("Ollama 流提前结束，回答未完整生成")
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError("Ollama 流连接失败") from exc


class MockLLMClient(BaseLLMClient):
    """仅用于自动化测试和显式 demo 模式，界面明确标注不是云模型。"""

    provider_name = "mock"

    async def generate(self, messages: list[ChatMessage], *, json_mode: bool = False) -> str:
        """提供可预测决策，让无密钥测试也能验证数据库与图逻辑。"""
        prompt = messages[-1].content
        if "ROUTE_DECISION" in prompt:
            question = prompt.split("用户问题：")[-1]
            route = (
                "hybrid"
                if "对比" in question and "True" in prompt
                else (
                    "web"
                    if "最新" in question and "True" in prompt
                    else (
                        "knowledge"
                        if any(w in question.lower() for w in ("文档", "资料", "rag", "agent"))
                        else "direct"
                    )
                )
            )
            return json.dumps({"route": route, "reason": "演示模式规则"}, ensure_ascii=False)
        if "VERIFY_ANSWER" in prompt:
            return json.dumps({"supported": True, "feedback": "演示校验"}, ensure_ascii=False)
        return "演示模式：请配置真实模型 API Key。"

    async def chat(
        self, messages: list[ChatMessage], *, tools: list[dict], tool_choice: str | dict = "auto"
    ) -> ChatMessage:
        """测试时产生标准工具调用，工具仍由真实执行器调用。"""
        if any(m.role == "tool" for m in messages):
            return ChatMessage("assistant", "研究完成")
        query = messages[-1].content
        return ChatMessage(
            "assistant",
            "",
            tool_calls=[
                {
                    "id": "demo-call",
                    "type": "function",
                    "function": {
                        "name": tools[0]["function"]["name"],
                        "arguments": json.dumps({"query": query}, ensure_ascii=False),
                    },
                }
            ],
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """测试生成器本身产出增量，不经过完整生成后再切片。"""
        prompt = messages[-1].content
        yield "演示模式回答。"
        # 只检查实际证据区，提示词里的引用示例不是真正的资料。
        evidence = (
            prompt.split("检索证据：", 1)[1]
            if "检索证据：" in prompt
            else prompt.split("证据：", 1)[-1].split("原回答：", 1)[0]
        )
        if "[K1]" in evidence:
            yield "资料中的内容可作为参考 [K1]。"
        elif "[W1]" in evidence:
            yield "网页资料可作为参考 [W1]。"
        else:
            yield "填写 API Key 后将由真实模型回答。"


@lru_cache(maxsize=16)
def get_llm_client(model_id: str | None = None) -> BaseLLMClient:
    """按服务器模型目录创建独立客户端；切换不会改写全局 Settings。"""
    settings = get_settings()
    profile = get_model_profile(model_id)
    provider = profile.provider.lower()
    if provider == "mock":
        return MockLLMClient()
    if provider == "ollama":
        return OllamaLLMClient(
            base_url=profile.base_url,
            model=profile.model,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    if provider not in {"dashscope", "deepseek", "minimax", "zhipu", "openai-compatible"}:
        raise ValueError(
            "LLM_PROVIDER 必须为 dashscope、deepseek、minimax、zhipu、"
            "ollama、mock 或 openai-compatible"
        )
    return OpenAICompatibleLLMClient(
        provider=provider,
        base_url=profile.base_url,
        api_key=profile.api_key,
        model=profile.model,
        timeout=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )
