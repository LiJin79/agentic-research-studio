import re
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings


def canonical_url(value: str) -> str:
    """仅保留可点击 HTTP(S) 来源，去除 fragment 用于去重。"""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def merge_evidence(items: list[dict]) -> list[dict]:
    """按来源去重并限制条目与字符总量，为每条证据分配稳定引用编号。"""
    settings = get_settings()
    seen, result, used = set(), [], 0
    counters = {"knowledge": 0, "web": 0}
    for original in items:
        item = dict(original)
        kind = item.get("source_type")
        if kind not in counters:
            continue
        if kind == "web":
            item["url"] = canonical_url(item.get("url") or "")
            if not item["url"]:
                continue
        key = (
            (kind, item.get("url"))
            if kind == "web"
            else (kind, item.get("document_id"), item.get("chunk_index"), item.get("snippet"))
        )
        if key in seen or not str(item.get("snippet", "")).strip():
            # 同一 URL 后读取到的正文优先于搜索摘要，不丢失更完整的证据。
            if key in seen and item.get("content_kind") == "page_text":
                previous = next((r for r in result if r.get("url") == item.get("url")), None)
                if previous and previous.get("content_kind") != "page_text":
                    old_length = len(previous["snippet"])
                    available = settings.context_max_characters - used + old_length
                    previous.update({k: v for k, v in item.items() if k != "citation_id"})
                    previous["snippet"] = str(item["snippet"])[
                        : min(settings.evidence_max_characters, available)
                    ]
                    previous["truncated"] = bool(item.get("truncated")) or len(
                        str(item["snippet"])
                    ) > len(previous["snippet"])
                    used += len(previous["snippet"]) - old_length
            continue
        snippet = str(item["snippet"]).strip()[: settings.evidence_max_characters]
        if len(result) >= settings.context_max_sources or used >= settings.context_max_characters:
            break
        item["snippet"] = snippet[: settings.context_max_characters - used]
        item["truncated"] = bool(item.get("truncated")) or len(str(original["snippet"])) > len(
            item["snippet"]
        )
        used += len(item["snippet"])
        counters[kind] += 1
        item["citation_id"] = ("K" if kind == "knowledge" else "W") + str(counters[kind])
        seen.add(key)
        result.append(item)
    return result


def format_evidence(items: list[dict]) -> str:
    """把编号、标题和原文一起放入提示词，资料明确作为不可信数据使用。"""
    return (
        "\n\n".join(
            f"[{item['citation_id']}] {item['title']}\n"
            + (f"来源链接：{item['url']}\n" if item.get("url") else "")
            + (f"资料类型：{item['content_kind']}\n" if item.get("content_kind") else "")
            + (f"发布时间：{item['published_at']}\n" if item.get("published_at") else "")
            + (f"读取时间：{item['retrieved_at']}\n" if item.get("retrieved_at") else "")
            + ("片段已截断，不代表完整资料。\n" if item.get("truncated") else "")
            + item["snippet"]
            for item in items
        )
        or "没有检索到可用证据。"
    )


def citation_errors(answer: str, items: list[dict], route: str) -> list[str]:
    """机械核对引用编号，防止模型校验器漏掉虚构或缺失的引用。"""
    # Markdown 加粗编号或链接形式也要检查，不能靠改样式绕过引用校验。
    used = set(re.findall(r"\[(?:\*\*|__)?([KW]\d+)(?:\*\*|__)?\]", answer))
    allowed = {item["citation_id"] for item in items}
    errors = []
    if used - allowed:
        errors.append("出现不存在的来源编号：" + "、".join(sorted(used - allowed)))
    if route != "direct" and items and not used:
        errors.append("基于检索资料的回答缺少来源引用")
    return errors
