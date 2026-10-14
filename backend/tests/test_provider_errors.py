"""错误信息能够解释参数问题，但不回显密钥。"""

import httpx
from app.core.config import get_settings
from app.llm.http import safe_provider_error


def test_provider_error_masks_configured_and_key_shaped_secrets(monkeypatch):
    """即便供应商错误正文包含凭据，也只能显示脱敏说明。"""
    monkeypatch.setattr(get_settings(), "llm_api_key", "private-test-value")
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "invalid content type private-test-value sk-fake-secret",
            }
        },
    )
    result = safe_provider_error(response)
    assert "invalid content type" in result
    assert "private-test-value" not in result
    assert "sk-fake-secret" not in result


def test_invalid_error_body_does_not_leak_html():
    """非 JSON 错误页面不直接展示给用户。"""
    assert safe_provider_error(httpx.Response(502, text="<html>private gateway dump</html>")) == ""
