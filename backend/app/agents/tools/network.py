"""受限网络读取：固定连接已校验公网 IP，禁止代理、内网访问和无限响应。"""

import asyncio
import ipaddress
import json
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from app.agents.search_policy import domain_matches
from app.core.config import get_settings


async def public_address(host: str, port: int) -> str:
    """验证所有 DNS 结果为公网地址；返回用于实际连接的 IP，避免二次解析。"""
    answers = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("工具禁止访问本机、内网或非公网地址")
    return addresses[0]


def validate_url(url: str, domains: list[str] | None = None) -> httpx.URL:
    """只接受 HTTP(S) 的标准端口 URL；域名限制同时作用于重定向目标。"""
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
        or not domain_matches(url, domains or [])
    ):
        raise ValueError("URL 协议、端口或来源域名不符合工具限制")
    return httpx.URL(url)


async def _fetch(
    url: str, *, params: dict | None, headers: dict | None, domains: list[str] | None
) -> tuple[bytes, str, str]:
    """逐跳检查重定向，连接固定 IP 时仍以原域名进行 Host 和 TLS SNI 校验。"""
    settings = get_settings()
    current = str(httpx.URL(url, params=params)) if params else url
    async with httpx.AsyncClient(
        timeout=settings.tool_timeout_seconds, trust_env=False, follow_redirects=False
    ) as client:
        for _ in range(4):
            original = validate_url(current, domains)
            port = original.port or (443 if original.scheme == "https" else 80)
            address = await public_address(original.host, port)
            pinned = original.copy_with(host=address)
            request_headers = {"User-Agent": "KnowledgeStudio/1.0", **(headers or {})}
            request_headers["Host"] = original.host
            async with client.stream(
                "GET",
                pinned,
                headers=request_headers,
                extensions={"sni_hostname": original.host},
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页重定向缺少目标")
                    next_url = urljoin(current, location)
                    # 认证数据不跨主机转发；模型无法利用重定向获取服务密钥。
                    if urlsplit(next_url).hostname != original.host and headers:
                        raise ValueError("禁止携带凭据跨域重定向")
                    current = next_url
                    continue
                if response.status_code >= 400:
                    # 不输出上游带 Key 的请求 URL 或响应体。
                    raise ValueError(f"上游服务返回 HTTP {response.status_code}")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    size += len(chunk)
                    if size > settings.tool_max_response_bytes:
                        raise ValueError("工具响应超过体积上限")
                    chunks.append(chunk)
                return b"".join(chunks), current, response.headers.get("content-type", "")
    raise ValueError("网页重定向次数超过上限")


async def fetch_bytes(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    domains: list[str] | None = None,
) -> tuple[bytes, str, str]:
    """整次调用有墙钟超时，慢速响应与 DNS 解析不能无限等待。"""
    return await asyncio.wait_for(
        _fetch(url, params=params, headers=headers, domains=domains),
        timeout=get_settings().tool_timeout_seconds,
    )


async def fetch_json(url: str, *, params: dict | None = None, headers: dict | None = None):
    """固定供应商接口复用限长网络读取，不保留响应中的认证信息。"""
    body, _, _ = await fetch_bytes(url, params=params, headers=headers)
    return json.loads(body)
