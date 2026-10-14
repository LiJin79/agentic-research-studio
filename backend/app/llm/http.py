import asyncio
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.base import LLMProviderError


def safe_provider_error(response: httpx.Response) -> str:
    """只提取供应商错误说明，不回显请求头或正文，并再次遮盖已配置密钥。"""
    try:
        body = response.json()
        error = body.get("error") or body
        if not isinstance(error, dict):
            return ""
        detail = str(error.get("message") or error.get("msg") or error.get("code") or "")
    except (ValueError, AttributeError):
        return ""
    settings = get_settings()
    for secret in [
        settings.llm_api_key,
        settings.dashscope_api_key,
        settings.deepseek_api_key,
        settings.minimax_api_key,
        settings.zhipu_api_key,
        settings.embedding_api_key,
        settings.bocha_api_key,
        settings.tavily_api_key,
        settings.app_access_token,
    ]:
        if secret:
            detail = detail.replace(secret, "[密钥隐藏]")
    detail = re.sub(r"(?:sk-|tvly-)[A-Za-z0-9_-]+", "[密钥隐藏]", detail)
    return detail[:240]


async def post_json(url: str, *, payload: dict, headers: dict | None = None) -> dict[str, Any]:
    """仅对临时网络故障、429 和 5xx 重试，鉴权和参数错误立即返回。"""
    settings = get_settings()
    for attempt in range(settings.llm_max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("响应不是 JSON 对象")
                return result
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code not in {429, 500, 502, 503, 504} or attempt == settings.llm_max_retries:
                detail = safe_provider_error(exc.response)
                message = f"上游接口返回 HTTP {code}" + (
                    "：" + detail if detail else "，请检查配置或配额"
                )
                raise LLMProviderError(message) from exc
        except httpx.TransportError as exc:
            if attempt == settings.llm_max_retries:
                raise LLMProviderError("上游网络连接失败或超时") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMProviderError("上游返回的数据格式不正确") from exc
        await asyncio.sleep(min(2**attempt, 4))
    raise LLMProviderError("上游请求失败")
