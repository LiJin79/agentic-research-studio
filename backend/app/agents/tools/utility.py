"""真实只读工具：网页、代码、论文、天气、路线和受限文档计算。"""

import asyncio
import base64
import csv
import io
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import duckdb
import trafilatura
from sqlalchemy import select

from app.agents.tools.network import fetch_bytes, fetch_json
from app.core.config import get_settings
from app.db.models import Document
from app.db.session import session_factory
from app.vector.parsing import extract_text


def evidence(title: str, content: str, url: str, **metadata) -> list[dict]:
    """所有联网结果统一为带查询时间的证据，额外数据不会丢弃出处。"""
    return [
        {
            "source_type": "web",
            "title": title,
            "snippet": content,
            "url": url,
            "retrieved_at": datetime.now(UTC).isoformat(),
            **metadata,
        }
    ]


async def read_webpage(url: str, domains: list[str] | None = None) -> list[dict]:
    """提取公开网页的正文与发布信息；不绕过登录，也不把解析失败当空结果。"""
    body, final_url, content_type = await fetch_bytes(url, domains=domains)
    if "html" not in content_type and "text/plain" not in content_type:
        raise ValueError("正文工具仅支持 HTML 或纯文本页面")
    if "text/plain" in content_type:
        text, title, date = body.decode("utf-8", errors="replace"), final_url, None
    else:
        extracted = await asyncio.to_thread(
            trafilatura.bare_extraction,
            body,
            url=final_url,
            include_tables=True,
            include_comments=False,
            with_metadata=True,
        )
        if not extracted or not extracted.text:
            raise ValueError("未能提取网页正文，可能需要动态渲染或登录")
        text, title, date = extracted.text, extracted.title or final_url, extracted.date
    return evidence(title, text[:10000], final_url, published_at=date, content_kind="page_text")


async def search_github(query: str) -> list[dict]:
    """使用 GitHub REST 查询公开仓库；只搜索和读取，不执行任何写操作。"""
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    data = await fetch_json(
        "https://api.github.com/search/repositories",
        params={"q": query, "per_page": 4},
        headers=headers,
    )
    return [
        evidence(
            item["full_name"],
            json.dumps(
                {
                    "description": item.get("description"),
                    "language": item.get("language"),
                    "updated_at": item.get("updated_at"),
                    "default_branch": item.get("default_branch"),
                },
                ensure_ascii=False,
            ),
            item["html_url"],
            content_kind="repository_metadata",
        )[0]
        for item in data.get("items", [])
    ]


async def read_repo_file(repo: str, path: str, ref: str = "HEAD") -> list[dict]:
    """先解析提交 SHA 再读文件，返回带行号的代码；永远不运行仓库代码。"""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("仓库名应为 owner/repo")
    if path.startswith("/") or ".." in path.split("/") or "\\" in path:
        raise ValueError("文件路径必须是仓库内相对路径")
    settings, headers = get_settings(), {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    root = f"https://api.github.com/repos/{repo}"
    commit = await fetch_json(f"{root}/commits/{quote(ref, safe='')}", headers=headers)
    sha = commit["sha"]
    data = await fetch_json(
        f"{root}/contents/{quote(path, safe='/')}",
        params={"ref": sha},
        headers=headers,
    )
    if not isinstance(data, dict) or data.get("type") != "file" or not data.get("content"):
        raise ValueError("请选择可读取的小型文本文件，而不是目录或二进制文件")
    raw = base64.b64decode(data["content"]).decode("utf-8")
    lines = raw.splitlines()[:300]
    text = "\n".join(f"{index}: {line}" for index, line in enumerate(lines, 1))
    return evidence(
        f"{repo}/{path}",
        text,
        f"https://github.com/{repo}/blob/{sha}/{quote(path, safe='/')}",
        content_kind="code",
        commit_sha=sha,
        line_start=1,
        line_end=len(lines),
    )


async def search_papers(query: str) -> list[dict]:
    """搜索 arXiv 预印本，保留作者、发表时间和摘要，明确不代表全文阅读。"""
    body, _, _ = await fetch_bytes(
        "https://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "max_results": 4, "sortBy": "relevance"},
    )
    if b"<!DOCTYPE" in body or b"<!ENTITY" in body:
        raise ValueError("不接受带自定义实体的 XML")
    root, ns = ElementTree.fromstring(body), {"a": "http://www.w3.org/2005/Atom"}
    results = []
    for item in root.findall("a:entry", ns):
        url = item.findtext("a:id", "", ns).replace("http://", "https://")
        title = " ".join(item.findtext("a:title", "", ns).split())
        if "arxiv.org/abs/" not in url:
            continue
        authors = [node.findtext("a:name", "", ns) for node in item.findall("a:author", ns)]
        results += evidence(
            title,
            "预印本摘要，未读取全文。\n作者："
            + ", ".join(authors)
            + "\n"
            + item.findtext("a:summary", "", ns),
            url,
            published_at=item.findtext("a:published", None, ns),
            content_kind="paper_abstract",
        )
    return results


async def lookup_library_docs(library: str, query: str, version: str = "") -> list[dict]:
    """按库与可选版本读取 Context7 文档片段，缺少 Key 时拒绝调用。"""
    settings = get_settings()
    if not settings.context7_api_key:
        raise ValueError("未配置 CONTEXT7_API_KEY")
    params = {"query": query, "library": library, "type": "json"}
    if version:
        params["version"] = version
    data = await fetch_json(
        "https://context7.com/api/v3/search",
        params=params,
        headers={"Authorization": f"Bearer {settings.context7_api_key}"},
    )
    results = []
    for item in (data.get("infoSnippets", []) + data.get("codeSnippets", []))[:5]:
        url = item.get("pageUrl") or item.get("codeLink")
        if not url:
            continue
        text = item.get("content") or "\n".join(x.get("code", "") for x in item.get("codeList", []))
        results += evidence(item.get("codeTitle") or library, text, url, content_kind="docs")
    return results


async def get_weather(city: str) -> list[dict]:
    """通过城市匹配和经纬度查询和风三日预报，保留原始预报与来源链接。"""
    settings = get_settings()
    host = settings.qweather_api_host.strip().removeprefix("https://").rstrip("/")
    if not settings.qweather_api_key or not re.fullmatch(r"[a-z0-9-]+\.qweatherapi\.com", host):
        raise ValueError("请配置 QWEATHER_API_KEY 与账户专属 QWEATHER_API_HOST")
    headers = {"X-QW-Api-Key": settings.qweather_api_key}
    geo = await fetch_json(
        f"https://{host}/geo/v2/city/lookup",
        params={"location": city, "number": 3},
        headers=headers,
    )
    matches = geo.get("location", [])
    if len(matches) != 1:
        names = [f"{x.get('adm1', '')}/{x.get('adm2', '')}/{x.get('name', '')}" for x in matches]
        raise ValueError("城市位置有歧义或未找到，请指定省市区：" + ", ".join(names))
    location = matches[0]
    lat, lon = float(location["lat"]), float(location["lon"])
    data = await fetch_json(
        f"https://{host}/weather/v1/daily/{lat:.2f}/{lon:.2f}",
        params={"days": 3},
        headers=headers,
    )
    if data.get("code") not in {None, "200", 200}:
        raise ValueError("和风天气未返回有效预报，请检查权限与额度")
    return evidence(
        f"{city}天气预报（和风天气）",
        json.dumps({"location": location, "forecast": data}, ensure_ascii=False),
        location["fxLink"],
        content_kind="weather",
        units="metric",
    )


async def search_places(city: str, keywords: str) -> list[dict]:
    """查询高德 POI，返回实际地点；不将地点数据当作可订库存或实时票价。"""
    settings = get_settings()
    if not settings.amap_api_key:
        raise ValueError("未配置 AMAP_API_KEY")
    data = await fetch_json(
        "https://restapi.amap.com/v3/place/text",
        params={
            "key": settings.amap_api_key,
            "city": city,
            "keywords": keywords,
            "offset": 5,
            "citylimit": "true",
        },
    )
    if data.get("status") != "1":
        raise ValueError("高德地点查询失败，请检查服务权限与额度")
    return [
        evidence(
            poi.get("name", keywords),
            json.dumps(
                {k: poi.get(k) for k in ["name", "address", "location", "type", "cityname"]},
                ensure_ascii=False,
            ),
            "https://uri.amap.com/marker?position=" + poi["location"],
            content_kind="place",
        )[0]
        for poi in data.get("pois", [])
        if poi.get("location")
    ]


async def plan_route(origin: str, destination: str, mode: str = "walking") -> list[dict]:
    """使用地点查询返回的经度纬度规划步行或驾车路线，保留估算性质。"""
    if mode not in {"walking", "driving"}:
        raise ValueError("路线只支持 walking/driving")
    for coordinate in (origin, destination):
        if not re.fullmatch(r"-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?", coordinate):
            raise ValueError("请使用地点工具返回的经度,纬度，不要猜坐标")
        lon, lat = map(float, coordinate.split(","))
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("经纬度超出范围")
    settings = get_settings()
    if not settings.amap_api_key:
        raise ValueError("未配置 AMAP_API_KEY")
    data = await fetch_json(
        f"https://restapi.amap.com/v3/direction/{mode}",
        params={
            "key": settings.amap_api_key,
            "origin": origin,
            "destination": destination,
        },
    )
    if data.get("status") != "1":
        raise ValueError("高德路线查询失败")
    paths = data.get("route", {}).get("paths", [])
    if not paths:
        return []
    path = paths[0]
    summary = {k: path.get(k) for k in ["distance", "duration", "tolls"]}
    summary["steps"] = [step.get("instruction") for step in path.get("steps", [])][:30]
    return evidence(
        "高德路线估算",
        json.dumps(summary, ensure_ascii=False),
        f"https://uri.amap.com/navigation?from={origin}&to={destination}&mode=car",
        content_kind="route",
        units="distance:m,duration:s",
    )


async def list_documents() -> list[dict]:
    """列出当前工作台可用的上传资料 ID；仅用于工具发现，不作为事实证据。"""
    async with session_factory() as database:
        rows = (
            await database.scalars(
                select(Document)
                .where(Document.status == "ready")
                .order_by(Document.created_at.desc())
                .limit(20)
            )
        ).all()
        return [
            {"source_type": "catalog", "document_id": str(row.id), "filename": row.filename}
            for row in rows
        ]


async def _document_bytes(document_id: str) -> tuple[str, bytes]:
    """模型只提供数据库 ID；实际路径必须位于该文档的上传目录，不接受任意路径。"""
    identifier = uuid.UUID(document_id)
    async with session_factory() as database:
        item = await database.get(Document, identifier)
        if not item or not item.source_uri or item.status != "ready":
            raise ValueError("文档不存在或尚未就绪")
        root = (get_settings().upload_dir / str(identifier)).resolve()
        path = Path(item.source_uri).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("文档存储路径不符合安全限制")
        if path.stat().st_size > get_settings().max_upload_bytes:
            raise ValueError("文档超出读取体积上限")
        return item.filename, await asyncio.to_thread(path.read_bytes)


async def read_document(document_id: str) -> list[dict]:
    """按 ID 读取上传文档，保留原文件来源；文本过长时返回明确的截断标记。"""
    name, body = await _document_bytes(document_id)
    text = await asyncio.to_thread(extract_text, name, body)
    return [
        {
            "source_type": "knowledge",
            "document_id": document_id,
            "title": name,
            "snippet": text[:10000],
            "chunk_index": None,
            "url": None,
            "content_kind": "document_text",
            "truncated": len(text) > 10000,
        }
    ]


def calculate_csv(body: bytes, operation: str, column: str = "", group_by: str = "") -> dict:
    """仅编译白名单聚合，DuckDB 禁止外部访问；模型不能提交任意 SQL。"""
    allowed = {"count", "sum", "avg", "min", "max"}
    if operation not in allowed:
        raise ValueError("只允许 count/sum/avg/min/max")
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    columns = reader.fieldnames or []
    if not columns or len(columns) > 100 or len(set(columns)) != len(columns):
        raise ValueError("CSV 表头为空、重复或列数过多")
    if (operation != "count" and column not in columns) or (group_by and group_by not in columns):
        raise ValueError("聚合列或分组列不存在，请先读取文档确认表头")
    rows = []
    for row in reader:
        if len(rows) >= 50000:
            raise ValueError("表格超过 50000 行的安全上限")
        rows.append([row.get(key) for key in columns])

    def identifier(value: str) -> str:
        """数据库标识符来自真实表头，并始终使用双引号转义。"""
        return '"' + value.replace('"', '""') + '"'

    with duckdb.connect(
        config={"enable_external_access": "false", "memory_limit": "64MB", "threads": "1"}
    ) as connection:
        connection.execute(
            "CREATE TABLE input_data ("
            + ",".join(identifier(name) + " VARCHAR" for name in columns)
            + ")"
        )
        if rows:
            connection.executemany(
                "INSERT INTO input_data VALUES (" + ",".join("?" for _ in columns) + ")", rows
            )
        if operation != "count":
            invalid = connection.execute(
                f"SELECT count(*) FROM input_data WHERE {identifier(column)} IS NOT NULL "
                f"AND trim({identifier(column)}) != '' "
                f"AND TRY_CAST({identifier(column)} AS DOUBLE) IS NULL"
            ).fetchone()[0]
            if invalid:
                raise ValueError("数值列包含非数字，拒绝静默忽略后生成错误统计")
        value = (
            "count(*)"
            if operation == "count"
            else (f"{operation}(TRY_CAST({identifier(column)} AS DOUBLE))")
        )
        select = f"{identifier(group_by)}, " if group_by else ""
        sql = f"SELECT {select}{value} AS result FROM input_data"
        if group_by:
            sql += f" GROUP BY {identifier(group_by)} ORDER BY {identifier(group_by)}"
        output = connection.execute(sql + " LIMIT 101").fetchall()
    return {
        "columns": columns,
        "row_count": len(rows),
        "operation": operation,
        "column": column,
        "group_by": group_by,
        "results": output[:100],
        "truncated": len(output) > 100,
    }


async def analyze_table(
    document_id: str, operation: str = "count", column: str = "", group_by: str = ""
) -> list[dict]:
    """对上传 CSV 进行有限聚合，输出计算参数和可复核结果，不运行生成代码。"""
    name, body = await _document_bytes(document_id)
    if Path(name).suffix.lower() != ".csv":
        raise ValueError("当前统计工具仅支持 CSV，Excel 请先导出 CSV")
    output = await asyncio.to_thread(calculate_csv, body, operation, column, group_by)
    return [
        {
            "source_type": "knowledge",
            "document_id": document_id,
            "title": name,
            "snippet": json.dumps(output, ensure_ascii=False),
            "chunk_index": None,
            "url": None,
            "content_kind": "calculation",
        }
    ]
