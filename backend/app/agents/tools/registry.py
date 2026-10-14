"""按角色与任务绑定工具，不将所有能力和未配置的服务交给每个模型。"""

import re
from collections.abc import Callable

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents.tools import utility
from app.core.config import get_settings


class QueryInput(BaseModel):
    """限制搜索文本长度，兼容现有搜索工具调用约定。"""

    query: str = Field(min_length=1, max_length=500)


class PageInput(BaseModel):
    """公开网页地址，不接受本地文件或任意协议。"""

    url: str = Field(min_length=8, max_length=2000)


class RepoInput(BaseModel):
    """固定仓库与文件，可指定版本，默认读取 HEAD 对应的提交。"""

    repo: str = Field(min_length=3, max_length=160)
    path: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="HEAD", min_length=1, max_length=120)


class LibraryInput(QueryInput):
    """技术文档查询需要库名称，可显式限定版本。"""

    library: str = Field(min_length=1, max_length=100)
    version: str = Field(default="", max_length=80)


class CityInput(BaseModel):
    """城市必须包含必要行政区划，不能用模型猜测的坐标。"""

    city: str = Field(min_length=1, max_length=100)


class PlaceInput(CityInput):
    """地点查询使用城市与关键词。"""

    keywords: str = Field(min_length=1, max_length=100)


class RouteInput(BaseModel):
    """经纬度必须来自真实地点查询结果，路线模式在函数中白名单校验。"""

    origin: str = Field(min_length=3, max_length=80)
    destination: str = Field(min_length=3, max_length=80)
    mode: str = Field(default="walking", max_length=20)


class DocumentInput(BaseModel):
    """只接收资料目录或检索结果中实际存在的 UUID。"""

    document_id: str = Field(min_length=36, max_length=36)


class TableInput(DocumentInput):
    """只允许预定义聚合函数，不接收 SQL、Python 或文件路径。"""

    operation: str = Field(default="count", max_length=10)
    column: str = Field(default="", max_length=200)
    group_by: str = Field(default="", max_length=200)


def tool_catalog() -> list[dict]:
    """返回脱敏能力目录；ready 表示可调用条件满足，不承诺外网服务实时可用。"""
    settings = get_settings()
    specifications = [
        ("search_knowledge", "知识库搜索", "knowledge", True, ""),
        ("read_document", "读取上传文档", "knowledge", True, ""),
        ("analyze_table", "CSV 数据统计", "data", True, ""),
        (
            "search_web",
            "网页搜索",
            "web",
            settings.web_search_configured,
            "BOCHA_API_KEY/TAVILY_API_KEY",
        ),
        ("read_webpage", "网页正文读取", "web", True, ""),
        ("search_github", "GitHub 仓库查询", "code", True, "GITHUB_TOKEN（可选，提升限额）"),
        ("read_repo_file", "只读代码解读", "code", True, "GITHUB_TOKEN（可选）"),
        ("search_papers", "arXiv 论文摘要", "science", True, ""),
        (
            "lookup_library_docs",
            "版本技术文档",
            "code",
            bool(settings.context7_api_key),
            "CONTEXT7_API_KEY",
        ),
        (
            "get_weather",
            "天气预报",
            "travel",
            bool(settings.qweather_api_key and settings.qweather_api_host),
            "QWEATHER_API_KEY + QWEATHER_API_HOST",
        ),
        ("search_places", "地点查询", "travel", bool(settings.amap_api_key), "AMAP_API_KEY"),
        ("plan_route", "出行路线", "travel", bool(settings.amap_api_key), "AMAP_API_KEY"),
    ]
    return [
        {
            "name": name,
            "label": label,
            "category": category,
            "configured": bool(ready),
            "key_env": key,
        }
        for name, label, category, ready, key in specifications
    ]


def extra_tools(kind: str, question: str, domains: list[str]) -> list[StructuredTool]:
    """只提供与问题有关的只读工具，未配置凭据的能力不绑定给模型。"""
    settings = get_settings()
    tools = []

    def add(name: str, description: str, function: Callable, schema=None) -> None:
        """把校验 Schema 和异步实现注册为真实模型函数工具。"""
        tools.append(
            StructuredTool.from_function(
                name=name,
                description=description,
                coroutine=function,
                args_schema=schema,
            )
        )

    if kind == "knowledge":
        add("list_documents", "列出已上传文档 ID 和名称，仅用于发现资料。", utility.list_documents)
        add(
            "read_document",
            "按真实文档 ID 读取文本，不能传服务器路径。",
            utility.read_document,
            DocumentInput,
        )
        if re.search(r"CSV|表格|统计|销量|平均|求和|聚合|数据分析", question, re.I):
            add(
                "analyze_table",
                "计算上传 CSV 的 count/sum/avg/min/max，可按列分组。",
                utility.analyze_table,
                TableInput,
            )
        return tools

    async def page(url: str) -> list[dict]:
        """将本轮来源范围固定在闭包中，模型不能修改域名约束。"""
        return await utility.read_webpage(url, domains=domains)

    add("read_webpage", "读取公开网页正文；搜索摘要不足时调用，保留来源。", page, PageInput)
    # 限定来源时不附加绕过该域名的其他数据源。
    if domains:
        return tools
    if re.search(r"github|仓库|代码|开源|框架|API|编程|库版本", question, re.I):
        add(
            "search_github",
            "搜索公开 GitHub 仓库，不写入、不运行代码。",
            utility.search_github,
            QueryInput,
        )
        add(
            "read_repo_file",
            "读取固定提交的仓库文件，返回行号和 SHA，未执行代码。",
            utility.read_repo_file,
            RepoInput,
        )
        if settings.context7_api_key:
            add(
                "lookup_library_docs",
                "查询库的版本技术文档片段。",
                utility.lookup_library_docs,
                LibraryInput,
            )
    if re.search(r"论文|文献|arxiv|研究进展|科研", question, re.I):
        add(
            "search_papers",
            "搜索 arXiv 预印本摘要，结果并非全文或同行评审结论。",
            utility.search_papers,
            QueryInput,
        )
    if re.search(r"天气|气温|下雨|预报|旅游|旅行|行程|出行|景点|路线", question):
        if settings.qweather_api_key and settings.qweather_api_host:
            add(
                "get_weather",
                "查询指定城市三日天气预报，保留查询时间。",
                utility.get_weather,
                CityInput,
            )
        if settings.amap_api_key:
            add(
                "search_places",
                "查询高德地点，返回坐标，不能查询订票库存。",
                utility.search_places,
                PlaceInput,
            )
            add(
                "plan_route",
                "使用已查到的坐标规划步行或驾车估算路线。",
                utility.plan_route,
                RouteInput,
            )
    return tools
