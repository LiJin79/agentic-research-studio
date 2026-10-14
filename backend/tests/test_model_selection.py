"""模型菜单与供应商协议测试，全部使用假密钥和假响应，不访问云端。"""

import asyncio
import json
import uuid

import pytest
from app.agents import prompts
from app.agents.evidence import citation_errors
from app.core.config import get_settings
from app.core.exceptions import ModelSelectionError
from app.llm import factory
from app.llm.base import ChatMessage
from app.llm.catalog import get_model_profile, model_catalog, validate_model_selection
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from pydantic import ValidationError


def test_catalog_is_public_and_does_not_cross_use_provider_keys(monkeypatch):
    """前端目录只包含配置状态，不能获得密钥或用阿里 Key 访问其他供应商。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "dashscope")
    monkeypatch.setattr(settings, "llm_api_key", "qwen-secret-test")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "minimax_api_key", "")
    monkeypatch.setattr(settings, "zhipu_api_key", "")
    public = json.dumps([profile.public() for profile in model_catalog()])
    assert "qwen-secret-test" not in public
    assert "base_url" not in public and '"api_key"' not in public
    assert get_model_profile("qwen-plus").configured
    assert get_model_profile("deepseek").configured is False
    assert get_model_profile("minimax").configured is False
    with pytest.raises(ModelSelectionError):
        validate_model_selection("deepseek")
    with pytest.raises(ModelSelectionError):
        get_model_profile("not-a-server-model")


def test_clients_are_per_model_and_leave_default_and_embedding_unchanged(monkeypatch):
    """切换模型只创建另一个客户端，不修改默认配置或向量空间。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "dashscope")
    monkeypatch.setattr(settings, "deepseek_api_key", "deepseek-secret-test")
    fingerprint, default = settings.embedding_fingerprint, settings.llm_model
    factory.get_llm_client.cache_clear()
    try:
        qwen, deepseek = factory.get_llm_client(), factory.get_llm_client("deepseek")
        assert qwen is not deepseek
        assert deepseek.provider_name == "deepseek"
        assert deepseek.api_key == "deepseek-secret-test"
        assert factory.get_llm_client("deepseek") is deepseek
        assert settings.llm_model == default
        assert settings.embedding_fingerprint == fingerprint
    finally:
        factory.get_llm_client.cache_clear()


def test_unconfigured_selection_does_not_touch_database(monkeypatch):
    """未配置模型在读取或写入会话前就失败，避免留下未完成用户消息。"""
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "")
    monkeypatch.setattr(get_settings(), "llm_provider", "dashscope")

    async def run():
        """不提供数据库；若校验顺序错误，测试会触发数据库访问异常。"""
        execution = ChatService(None)._execute(
            uuid.uuid4(), "问题", False, uuid.uuid4(), "deepseek"
        )
        with pytest.raises(ModelSelectionError):
            await anext(execution)
        await execution.aclose()

    asyncio.run(run())


def test_model_id_is_not_an_endpoint():
    """客户端只能提交短 ID，不能通过地址字段发起任意服务器请求。"""
    request = ChatRequest(session_id=uuid.uuid4(), message="你好", model_id="deepseek")
    assert request.model_id == "deepseek"
    with pytest.raises(ValidationError):
        ChatRequest(session_id=uuid.uuid4(), message="你好", model_id="https://example.com")


def test_minimax_preserves_tool_reasoning_but_uses_its_own_parameters(monkeypatch):
    """MiniMax 参数不能机械照搬 JSON 模式或 tool_choice，思考字段必须保留往返。"""
    seen = []

    async def fake_post(url, *, payload, headers):
        """捕获供应商请求，返回含虚构测试思考字段的标准工具调用。"""
        seen.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "test-private",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "search_web", "arguments": '{"query":"test"}'},
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(factory, "post_json", fake_post)
    client = factory.OpenAICompatibleLLMClient(
        provider="minimax",
        model="MiniMax-M3",
        base_url="https://api.minimax.cn/v1",
        api_key="test",
        timeout=10,
        temperature=0.2,
    )

    async def run():
        """工具观察后再次调用，检查协议字段保留且不会变成正文。"""
        result = await client.chat([ChatMessage("user", "问题")], tools=[{}])
        assert result.content == ""
        assert result.reasoning_content == "test-private"
        await client.chat([result, ChatMessage("tool", "资料", tool_call_id="c1")], tools=[{}])
        await client.generate([ChatMessage("system", "输出 JSON")], json_mode=True)

    asyncio.run(run())
    assert seen[0]["thinking"] == {"type": "disabled"}
    assert seen[0]["reasoning_split"] is True
    assert "max_completion_tokens" in seen[0] and "max_tokens" not in seen[0]
    assert "tool_choice" not in seen[0]
    assert seen[1]["messages"][0]["reasoning_content"] == "test-private"
    assert "response_format" not in seen[2]


def test_role_prompt_templates_render_and_keep_quality_constraints():
    """各角色输入边界可以正常 format，复杂回答与引用规则不会被遗漏。"""
    values = dict(
        route="direct",
        history="[]",
        question="设计方案",
        context="无证据",
        answer="回答",
        feedback="修订",
    )
    for template in [prompts.ANSWER_PROMPT, prompts.VERIFY_PROMPT, prompts.REVISE_PROMPT]:
        assert "无依据" in template.format(**values)
    assert "复杂问题充分展开" in prompts.ANSWER_PROMPT
    assert "3 轮" in prompts.RESEARCH_SYSTEM_PROMPT.format(
        role="研究员", domains="未限定", max_iterations=3
    )
    assert "slides" in prompts.PRESENTATION_PROMPT.format(max_pages=3, content="{}")
    assert "ROUTE_DECISION" in prompts.SUPERVISOR_PROMPT.format(
        question="设计知识库系统", history="[]", use_web_search=False
    )


def test_styled_and_linked_invalid_citations_are_detected():
    """旧编号不能通过加粗或链接样式逃避后端的机械检查。"""
    for text in ["[W10]", "[**W10**](https://example.com)", "[__W10__]"]:
        assert citation_errors(text, [], "direct")
