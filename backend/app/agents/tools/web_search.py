from dataclasses import dataclass

from app.agents.search_policy import domain_matches, normalize_search_query, requested_domains
from app.core.config import get_settings
from app.llm.base import LLMProviderError
from app.llm.http import post_json


@dataclass(slots=True)
class WebSearchResult:
    """联网搜索的一条标准结果，两种供应商都转成相同形状。"""

    title: str
    url: str
    content: str
    score: float | None = None


async def search_web(
    query: str, *, include_domains: list[str] | None = None
) -> list[WebSearchResult]:
    """默认调用国内博查，保留 Tavily；没有密钥时明确报错而不伪造资料。"""
    settings = get_settings()
    domains = include_domains if include_domains is not None else requested_domains(query)
    query = normalize_search_query(query)
    if settings.web_search_provider == "bocha":
        if not settings.bocha_api_key:
            raise LLMProviderError("联网搜索尚未配置 BOCHA_API_KEY")
        body = await post_json(
            f"{settings.bocha_base_url.rstrip('/')}/v1/web-search",
            headers={"Authorization": f"Bearer {settings.bocha_api_key}"},
            payload={
                "query": query,
                "count": settings.web_search_max_results,
                "summary": True,
                "freshness": "noLimit",
                **({"include": "|".join(domains)} if domains else {}),
            },
        )
        if body.get("code") != 200:
            raise LLMProviderError("博查搜索返回业务错误，请检查密钥与配额")
        try:
            pages = body["data"].get("webPages", {}).get("value", [])
            return [
                WebSearchResult(
                    title=str(p.get("name") or "网页结果"),
                    url=str(p.get("url") or ""),
                    content=str(p.get("summary") or p.get("snippet") or ""),
                )
                for p in pages
                if domain_matches(str(p.get("url") or ""), domains)
            ]
        except (KeyError, TypeError, AttributeError) as exc:
            raise LLMProviderError("博查搜索响应结构无效") from exc
    if settings.web_search_provider != "tavily":
        raise LLMProviderError("WEB_SEARCH_PROVIDER 必须为 bocha 或 tavily")
    if not settings.tavily_api_key:
        raise LLMProviderError("联网搜索尚未配置 TAVILY_API_KEY")
    body = await post_json(
        "https://api.tavily.com/search",
        payload={
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": settings.web_search_max_results,
            "search_depth": "advanced",
            **({"include_domains": domains} if domains else {}),
        },
    )
    return [
        WebSearchResult(
            title=str(p.get("title") or "网页结果"),
            url=str(p.get("url") or ""),
            content=str(p.get("content") or ""),
            score=float(p["score"]) if p.get("score") is not None else None,
        )
        for p in body.get("results", [])
        if domain_matches(str(p.get("url") or ""), domains)
    ]
