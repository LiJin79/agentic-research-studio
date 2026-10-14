# 工具与界面部署记录

日期：2026-10-13。此次部署没有删除 PostgreSQL、Redis、Qdrant 或上传资料。

## 已实现并部署

- `read_webpage`：Trafilatura 提取公开网页正文与日期，限制响应体积与超时。
- `search_github`、`read_repo_file`：GitHub 只读 REST 适配；文件先固定提交 SHA，再返回行号。
- `search_papers`：arXiv Atom API，标注为预印本摘要，不声称读过全文。
- `list_documents`、`read_document`：通过数据库文档 ID 定位上传文件，拒绝任意路径。
- `analyze_table`：DuckDB 执行 CSV 的 count/sum/avg/min/max 和分组统计，不接受任意 SQL。
- DOCX 表格、PPTX 文字和表格解析。复用原有 Office 库，未额外安装 MarkItDown。
- 保留原有知识库检索、博查/Tavily 搜索与 Word/PPT 导出。导出仍由用户按钮确认，并非新增模型可调用的文件生成工具。

模型工具按角色和问题筛选，不会将所有工具一次绑定。前端“工具”页的“已启用”表示配置条件满足，不表示外部网络或供应商永远可用。

## 一次性真实探测

| 工具 | 实际结果 | 后续处理 |
| --- | --- | --- |
| GitHub 仓库查询 | 成功，返回 FastAPI 仓库 | 已启用；匿名请求限额较低，可补 GITHUB_TOKEN |
| CSV 聚合计算 | 成功，A=30、B=7 | 已启用，仅支持上传 CSV 的白名单统计 |
| FastAPI 网页正文 | 本次未成功取得正文，网络等待超时 | 无重试；保留接口，失败不能声称已读全文 |
| arXiv 论文查询 | HTTP 429 | 无重试；保留接口，不承诺当前网络中可用 |

原始探测记录见 `evaluation/utility-tools-live.json`。外网只探测一次，未使用云端大模型进行反复验证。

## 接口已准备但未启用

| 能力 | 需要填写 |
| --- | --- |
| 高德地点、路线 | AMAP_API_KEY：Web 服务类型 Key，当前为原生 REST 适配而非 JS SDK 或 MCP |
| 和风天气 | QWEATHER_API_KEY 与账户专属 QWEATHER_API_HOST |
| Context7 技术文档 | CONTEXT7_API_KEY |

当前配置统一见 `.env.example` 和 [工具能力](tools.md)。密钥仅进入 API/Worker，绝不返回浏览器。
OpenAlex 尚未接入，未使用的预留变量已移除。Crawl4AI、Firecrawl、Docling/OCR 未安装，以免增加浏览器和模型下载负担。

修改 .env 后，在项目目录执行：

```powershell
docker compose up -d --no-deps --force-recreate api worker
```

## 提示词归档

`docs/prompts/2026-10-13-tools-v1/` 保存 `prompts.zh.md`、`prompts.en.md` 和 SHA256 清单。
运行时使用中文；英文是对应职责与变量的档案，不会把两种语言重复拼接发送给模型。
新增约束覆盖：任务与工具预算、来源类型、发布时间与读取时间、代码提交、论文摘要、天气估算、统计计算和工具失败。
每条回答元数据保存 `prompt_version`，便于关联对应档案。

更新模板后执行 `scripts/archive_prompts.py`，不要手动把用户消息或密钥添加到档案。

## 界面

蓝色操作与代码研究，绿色资料，黄色出行，珊瑚色数据与报告。
新增彩色任务入口与工具配置目录；保留模型切换、字号加减、来源栏、导出及手机抽屉。
资源圆体下载超时，已停止并删除不完整下载。最终使用本地托管的 Noto Sans SC Variable；这是柔和中文无衬线字体，不宣称为资源圆体。
字体按 Unicode 范围分片，由项目自身提供，页面不依赖 Google Fonts 等外部字体服务。

## 验证与限制

- 后端单元测试覆盖安全 URL、私网 DNS、固定 IP/SNI、CSV、正文去重、双语变量和 Office 解析。
- 前端 9 项单元测试通过；5 种视口验证字号、模型请求、弹窗键盘操作与工具页布局。
- npm 安全审计已将本次发现的 source-map-js 告警修复，最终 0 个已报告漏洞。
- Docker API 健康检查通过，PostgreSQL/Redis/Qdrant 均正常。
- 本轮不把未经真实认证测试的高德、天气或 Context7 接口标为已经验证可用。
- 网页读取不会绕过登录或付费墙，GitHub 工具不会执行代码，表格工具不会执行生成的脚本。
