# 工具能力与限制

## 调用方式

研究子图将结构化工具的名称、说明和参数 Schema 发给生成模型。模型返回原生 `tool_calls`，执行节点校验名称、参数、调用预算与来源范围后运行函数，再用匹配的 `tool_call_id` 返回观察结果。不是让模型仅用文字声称搜索成功。

工具按研究角色、问题内容和配置条件筛选。前端“已配置”表示配置条件满足，不代表网络、配额或外部服务实时可用，也不代表每次问答都调用。

## 能力目录

| 工具 | 作用与配置 | 验证边界 |
| --- | --- | --- |
| `search_knowledge` | 搜索 ready 文档片段，需要有效向量配置与匹配索引 | 有真实入库与检索验收记录 |
| `list_documents`、`read_document` | 按真实文档 ID 列出/读取资料，不接收任意服务器路径 | 已接入，依赖已上传的可解析资料 |
| `analyze_table` | 用 DuckDB 对上传 CSV 做 count/sum/avg/min/max 和分组统计 | 有计算验收记录，不接收任意 SQL 或脚本 |
| `search_web` | 博查或 Tavily 搜索，按 provider 填对应 Key | 博查有真实调用记录，Tavily 为可选适配 |
| `read_webpage` | 读取公开网页正文，保留最终 URL，受域名和安全检查限制 | 已接入，既有外网探测发生超时，不保证每个网站可读 |
| `search_github`、`read_repo_file` | 公开仓库查询、固定提交文件读取，Token 可选 | 仓库查询有真实调用记录，受匿名额度和网络限制，不执行代码 |
| `search_papers` | arXiv 预印本标题、摘要和日期 | 接口/映射已实现，既有外网探测遇到 429，不声称读过全文 |
| `lookup_library_docs` | Context7 技术文档，需要 `CONTEXT7_API_KEY` | 可选适配，尚无真实认证验收记录 |
| `get_weather` | 和风天气，需要 Key 与账户专属 API Host | 可选适配，尚无真实认证验收记录 |
| `search_places`、`plan_route` | 高德地点和路线，需要 Web 服务类型 Key | 可选适配，尚无真实认证验收记录，不查询订票库存 |

记录来自有限样例，不是回答正确率或持续服务保证。工具出错与搜索零结果分别反馈，失败时不能描述为已取得正文或证据。

## 添加凭据

在现有 `.env` 中填写 `.env.example` 对应项，不覆盖整份文件。Key 只进入 API/Worker，不返回前端。修改后重新创建后端容器：

```powershell
docker compose up -d --no-deps --force-recreate api worker
```

OpenAlex 尚未接入，因此不提供配置变量。OCR、Crawl4AI、Firecrawl 也不是当前交付能力。Word/PPT 导出由用户按钮确认，不是模型可随意调用的服务器文件操作。

## 代码入口

- `backend/app/agents/tools/registry.py`：目录、Schema、任务筛选与条件注册。
- `backend/app/agents/tools/utility.py`：网页、仓库、论文、文档、统计及可选 API 实现。
- `backend/app/agents/tools/network.py`：公开 URL、DNS、重定向、响应大小和超时约束。
- `backend/app/agents/subgraphs/research.py`：工具 Schema、调用记录与执行循环。
