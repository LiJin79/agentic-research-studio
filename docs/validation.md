# 本机验收记录

此记录区分工程验收与真实模型效果，避免把 mock 测试当成云模型测试。

## 2026 年 10 月 12 日更新

最新一轮扩大功能验收发现并修复了联网意图和会话校验记忆问题。当前结果为 43 个后端单元测试、6 个集成测试、8 个前端测试；真实跨轮记忆和 hybrid 两种工具调用也已通过。详细范围与未覆盖项见 [功能验收报告](function-audit-2026-10-12.md)。下表保留上一轮检查记录。

| 验收 | 结果 | 范围 |
| --- | --- | --- |
| 后端单元测试 | 39 项通过 | 增加联网权限、域名约束、旧历史隔离、零结果、工具失败、办公文件结构和错误脱敏 |
| 基础设施集成测试 | 6 项通过 | PostgreSQL、Redis、Qdrant 与 worker；生成模型显式 mock，向量模型使用当前已配置的云服务 |
| 前端测试 | 6 项通过 | 原有 SSE 加联网许可判断和校验状态标签 |
| 最终 Docker 部署 | 已完成 | API、worker、frontend 已重新构建并启动；保留已有数据 |
| 浏览器回归 | 通过 | 最终部署页面上的桌面 1440×1000、手机 390×844，字号切换、联网许可确认及持久化、Word/PPT 入口，无 JS 异常和横向溢出；接口使用测试 fixture |
| 真实云端 HTTP 链路 | 通过 | qwen-plus、博查限定 fastapi.tiangolo.com，获得 5 条官方域名来源；工具执行记录持久化 |
| 真实办公下载 | 通过 | Word/PPT 文件由当前部署生成，解析确认正文与幻灯片可编辑，随后用本机 Office 渲染检查 |
| 用户实际操作 | 已通过 | 用户确认生成回答、text-embedding-v4 文档入库、知识库查询均正常 |

真实搜索和办公下载报告为 `evaluation/search-office/report.json`，包含 route、真实 URL、工具观察及检查结果。不包含密钥。验收会话已删除，用户会话和 knowledge-test.txt 保留。

办公技能见 [检索与办公技能](search-and-office.md)。Word 不额外调用模型，PPT 需要调用当前生成模型整理大纲，会消耗额度。

这是有限样例的功能验收，不代表所有主题的回答质量、并发性能、安全审计或生产 SLA 已通过。模型检查也不等于事实认证。

## 2026 年 10 月 11 日初始记录

| 验收 | 结果 | 说明 |
| --- | --- | --- |
| 后端单元测试 | 26 项通过 | 路由、工具协议、供应商适配器、严格校验、向量批次、引用、上游流截断、SSE 背压取消 |
| 真实基础设施集成测试 | 6 项通过 | PostgreSQL 会话/消息/级联、Redis 原子限流/锁、取消终态、Qdrant 检索与后台入库；模型为显式 mock/hash |
| 前端解析测试 | 4 项通过 | CRLF、多行 SSE、中文 UTF-8 分片、截断、错误事件 |
| Docker 镜像构建与迁移 | 通过 | API、worker、frontend、migrate；migrate 正常退出 0 |
| 容器 HTTP 工程链路 | 通过 | 上传、后台入库、检索、tool_start/end、token/done、幂等、变更请求冲突、第二轮 State 重置、下载与专用测试数据清理 |
| 真实网页联调 | 通过 | Edge 桌面 1440x1000、手机 390x844；新会话、自动改名、聊天及知识库页面；无 JS 异常或横向溢出 |
| 默认云配置基础设施 | 通过 | 国内模型默认配置，模型/向量/搜索密钥均未填写；缺少生成密钥返回 502，并持久记录 failed，不退回 mock |
| 真实云模型、Embedding、网页搜索 | 尚未验收 | 需要填写 API Key，不能用离线协议测试替代 |
| Ollama GPU 推理 | 尚未验收 | 保留适配器与可选容器，不默认启动，未进行显存/效果承诺 |

自动报告：evaluation/docker-demo-http-report.json、evaluation/ui-report.json、evaluation/deployment-report.json。

当前依赖有一条 Starlette TestClient 的 AnyIO 别名弃用警告，不影响测试结果。升级依赖时应重新运行回归测试。

## 初始记录中的云端验收步骤

以下是尚未填写密钥时记录的步骤。密钥现在已由用户补齐，10 月 12 日已完成上述有限真实验收。

在 .env 填 LLM_API_KEY、EMBEDDING_API_KEY；需要联网时填 BOCHA_API_KEY。然后执行：

```powershell
docker compose up -d
uv run python scripts/verify_project.py
```

成功报告应为 mode=cloud。这个脚本验证知识库路线；网页路线还需在页面开启联网，提问具有时效性的问题，核对执行记录中的 search_web 和真实网页引用。Hybrid 路线还需核对两种工具均执行。

再用自己的典型文档和问题进行人工评估，记录回答正确性、引用是否支持结论、无相关资料时是否诚实说明。没有测量的数据不应写入简历。
