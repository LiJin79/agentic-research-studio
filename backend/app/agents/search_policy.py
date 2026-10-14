"""从本轮问题提取检索约束；权限和来源范围不交给模型随意改写。"""

import re
from urllib.parse import urlsplit

DOMAIN_PATTERN = r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,63}"
WEB_TERM = r"(?:网页搜索|联网搜索|网上搜索|搜索网页|web\s*search)"
NEGATED_WEB = (
    r"(?:不要|不需要|无需|不用|禁止|不允许|不得|不进行|不使用)"
    r"[^。！？\n,，;；]{0,24}?(?:网页搜索|联网搜索|网上搜索|搜索网页|联网|访问互联网|web\s*search)"
)


def web_search_denied(question: str) -> bool:
    """识别本轮明确的禁止联网；开关偏好不能覆盖用户本轮的拒绝。"""
    return bool(re.search(NEGATED_WEB, question, re.I))


def requested_domains(question: str) -> list[str]:
    """识别 site: 搜索条件或明确的域名限定，保持子域名边界。"""
    domains = re.findall(rf"\bsite:\s*({DOMAIN_PATTERN})", question, re.IGNORECASE)
    if not domains and re.search(r"只使用|仅使用|只根据|仅根据|仅限|只搜索|限定|域名下", question):
        domains = re.findall(DOMAIN_PATTERN, question)
    return sorted({domain.lower().rstrip(".") for domain in domains})[:10]


def requires_web_search(question: str) -> bool:
    """仅判断当前提问的明确搜索意图，不从旧消息继承联网指令。"""
    if web_search_denied(question):
        return False
    if requested_domains(question):
        return True
    if re.search(
        r"(?:查询|查一下|搜索|分析|解读).{0,30}(?:github\.com/|arxiv\.org/)", question, re.I
    ):
        return True
    if re.search(r"(?:今天|明天|未来|本周|查询).{0,15}(?:天气|气温|天气预报)", question):
        return True
    # 解释工具概念不等于授权调用工具；必须匹配使用、进行等实际动作。
    if re.search(
        rf"(?:解释|介绍|什么是|含义|原理).*{WEB_TERM}|{WEB_TERM}.*(?:是什么|什么含义|如何工作)",
        question,
        re.I,
    ):
        return False
    return bool(
        re.search(
            rf"(?:请|帮我|需要|使用|进行|通过|开启|执行|利用).{{0,16}}{WEB_TERM}|搜索词|^{WEB_TERM}",
            question,
            re.I,
        )
    )


def domain_matches(url: str, domains: list[str]) -> bool:
    """只接受指定域名和其子域名，拒绝 example.com.evil.test 等伪装。"""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    return (
        parts.scheme in {"http", "https"}
        and bool(host)
        and (
            not domains or any(host == domain or host.endswith("." + domain) for domain in domains)
        )
    )


def normalize_search_query(query: str) -> str:
    """site: 由供应商专用过滤参数实现，不让它作为普通关键词降低召回率。"""
    query = re.sub(rf"\bsite:\s*{DOMAIN_PATTERN}", "", query, flags=re.I)
    return " ".join(query.split()) or "官方介绍"
