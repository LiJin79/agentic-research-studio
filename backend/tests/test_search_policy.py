"""真实故障对应的回归测试：权限、域名、旧历史、零结果和工具失败。"""

import asyncio
import json

import pytest
from app.agents.graph import build_agent_graph
from app.agents.search_policy import domain_matches, requested_domains, requires_web_search
from app.agents.tools.web_search import WebSearchResult
from app.llm.base import ChatMessage, LLMProviderError
from app.llm.factory import MockLLMClient


class SearchLLM(MockLLMClient):
    """故意选择知识库，确保当前明确搜索请求可以纠正错误路由。"""

    async def generate(self, messages, *, json_mode=False):
        """只有调度错误固定返回，验证和写作沿用确定性的测试模型。"""
        if "ROUTE_DECISION" in messages[-1].content:
            return json.dumps({"route": "knowledge", "reason": "旧历史误导"})
        return await super().generate(messages, json_mode=json_mode)

    async def chat(self, messages, *, tools, tool_choice="auto"):
        """真实兼容 API 的 content 必须为字符串，不能把单元素元组当多模态内容。"""
        assert all(isinstance(message.content, str) for message in messages)
        return await super().chat(messages, tools=tools, tool_choice=tool_choice)


def initial(question="请进行网页搜索 site:fastapi.tiangolo.com FastAPI features", **kwargs):
    """每次请求独立初始状态，不需要实际数据库和收费 API。"""
    return {
        "question": question,
        "history": [{"role": "user", "content": "查询内部项目"}],
        "use_web_search": True,
        "context": [],
        "sources": [],
        "trace": [],
        "tool_events": [],
        "revision_count": 0,
    } | kwargs


def test_explicit_web_request_denied_without_permission():
    """关闭权限必须明确报错，不能假装已经搜索或自动转向无关知识库。"""

    async def run():
        graph = build_agent_graph(llm=SearchLLM())
        with pytest.raises(LLMProviderError, match="未执行网页搜索"):
            await graph.ainvoke(initial(use_web_search=False))

    asyncio.run(run())


def test_domain_constraints_and_current_question_reach_tool(monkeypatch):
    """当前问题覆盖旧历史，并将过滤后的实际网页和工具结果保存到状态。"""
    from app.agents.subgraphs import research

    seen = []

    async def search(query, *, include_domains):
        """故意混入第三方和伪装域名，研究员必须执行第二层过滤。"""
        seen.append((query, include_domains))
        return [
            WebSearchResult("Official", "https://fastapi.tiangolo.com/features/", "official"),
            WebSearchResult("Other", "https://blog.example.com", "blog"),
            WebSearchResult("Fake", "https://fastapi.tiangolo.com.evil.test", "fake"),
        ]

    async def no_cache(key, fetch):
        """测试不访问 Redis。"""
        return await fetch()

    monkeypatch.setattr(research, "search_web", search)
    monkeypatch.setattr(research, "cached_search", no_cache)
    result = asyncio.run(build_agent_graph(llm=SearchLLM()).ainvoke(initial()))
    assert result["route"] == "web"
    assert seen[0][1] == ["fastapi.tiangolo.com"]
    assert "查询内部项目" not in seen[0][0]
    assert len(result["sources"]) == 1
    assert result["sources"][0]["url"] == "https://fastapi.tiangolo.com/features/"
    assert result["tool_events"][0]["name"] == "search_web"
    assert result["tool_events"][0]["result_count"] == 1


def test_empty_search_does_not_claim_verified_or_repeat_revisions(monkeypatch):
    """真实零结果需要说明证据不足，不应浪费多轮模型修订来制造资料。"""
    from app.agents.subgraphs import research

    async def search(query, **kwargs):
        """模拟搜索 API 正常响应但没有资料。"""
        return []

    async def no_cache(key, fetch):
        """跳过 Redis。"""
        return await fetch()

    monkeypatch.setattr(research, "search_web", search)
    monkeypatch.setattr(research, "cached_search", no_cache)
    result = asyncio.run(build_agent_graph(llm=SearchLLM()).ainvoke(initial()))
    assert result["answer_supported"] is False
    assert result["revision_count"] == 0
    assert "已执行网页搜索" in result["answer"]
    assert "不能据此认定" in result["answer"]


def test_search_failure_is_not_empty_success(monkeypatch):
    """网络或配额错误不允许转换成成功的无结果回答。"""
    from app.agents.subgraphs import research

    async def search(query, **kwargs):
        """模拟上游失败。"""
        raise LLMProviderError("搜索额度不足")

    async def no_cache(key, fetch):
        """跳过 Redis。"""
        return await fetch()

    monkeypatch.setattr(research, "search_web", search)
    monkeypatch.setattr(research, "cached_search", no_cache)
    with pytest.raises(LLMProviderError, match="搜索额度不足"):
        asyncio.run(build_agent_graph(llm=SearchLLM()).ainvoke(initial()))


def test_no_native_tool_call_is_not_search_success():
    """上游忽略必选工具时，不能声称完成了研究。"""

    class NoTools(SearchLLM):
        """不遵守工具选择要求的测试供应商。"""

        async def chat(self, messages, *, tools, tool_choice="auto"):
            """模拟没有工具调用的文本回复。"""
            return ChatMessage("assistant", "我已经搜索")

    with pytest.raises(LLMProviderError, match="没有执行必需"):
        asyncio.run(build_agent_graph(llm=NoTools()).ainvoke(initial()))


def test_domain_match_uses_hostname_boundaries():
    """允许子域名，但拒绝字符串包含、用户信息和非 HTTP 链接。"""
    domains = requested_domains("只使用 fastapi.tiangolo.com 域名下的官方资料")
    assert domains == ["fastapi.tiangolo.com"]
    assert domain_matches("https://fastapi.tiangolo.com/features", domains)
    assert domain_matches("https://docs.fastapi.tiangolo.com/", domains)
    assert not domain_matches("https://fastapi.tiangolo.com.evil.test/", domains)
    assert not domain_matches("https://fastapi.tiangolo.com@evil.test/", domains)
    assert not domain_matches("javascript:alert(1)", domains)


def test_bocha_include_parameter_and_defensive_filter(monkeypatch):
    """供应商请求传 include，site: 不作为普通词；返回结果继续校验。"""
    from app.agents.tools import web_search
    from app.core.config import get_settings

    settings, seen = get_settings(), {}
    monkeypatch.setattr(settings, "web_search_provider", "bocha")
    monkeypatch.setattr(settings, "bocha_api_key", "test-only")

    async def post(url, *, payload, headers):
        """只记录非密钥参数，不向网络发送请求。"""
        seen.update(payload)
        return {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "official",
                            "url": "https://fastapi.tiangolo.com",
                            "summary": "data",
                        },
                        {"name": "other", "url": "https://example.com", "summary": "other"},
                    ]
                }
            },
        }

    monkeypatch.setattr(web_search, "post_json", post)
    result = asyncio.run(web_search.search_web("site:fastapi.tiangolo.com FastAPI features"))
    assert seen["query"] == "FastAPI features"
    assert seen["include"] == "fastapi.tiangolo.com"
    assert len(result) == 1


def test_negated_and_conceptual_search_are_not_execution_requests():
    """关键词出现不代表需要搜索，否定句和概念解释应保持正常聊天。"""
    assert not requires_web_search("你好，不需要查询资料或联网搜索。")
    assert not requires_web_search("请解释网页搜索是什么。")
    assert requires_web_search("请进行网页搜索 FastAPI 官方文档")


def test_current_denial_overrides_enabled_preference():
    """即使开关开启，错误的模型 web 决策也不能覆盖本轮拒绝。"""

    class WebLLM(SearchLLM):
        """模拟调度模型忽视否定句。"""

        async def generate(self, messages, *, json_mode=False):
            """选择 web，其余行为保持一致。"""
            if "ROUTE_DECISION" in messages[-1].content:
                return '{"route":"web","reason":"wrong"}'
            return await super().generate(messages, json_mode=json_mode)

    result = asyncio.run(
        build_agent_graph(llm=WebLLM()).ainvoke(
            initial(question="你好，不需要查询资料或联网搜索。", use_web_search=True)
        )
    )
    assert result["route"] == "direct"
    assert not result["tool_events"]
