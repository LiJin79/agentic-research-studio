# 运行和验收指南

## 配置模型

默认使用国内云 API，不启动本地 GPU 模型。首次部署从统一的 `.env.example` 创建本机 `.env`，已有配置不要覆盖。数据库与模型配置的完整说明见 [配置说明](configuration.md)。主要模型项目如下：

| 环境变量 | 含义 | 默认 |
| --- | --- | --- |
| LLM_PROVIDER | 生成模型供应商 | dashscope |
| LLM_MODEL | 生成模型名称 | qwen-plus |
| LLM_BASE_URL | 兼容 API 根地址 | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| LLM_API_KEY | 百炼生成 API Key | 留空待填 |
| EMBEDDING_PROVIDER | 向量模型供应商 | dashscope |
| EMBEDDING_MODEL | 向量模型 | text-embedding-v4 |
| EMBEDDING_DIMENSIONS | 输出向量维度 | 1024 |
| EMBEDDING_BASE_URL | 向量 API 根地址 | 同百炼兼容地址 |
| EMBEDDING_API_KEY | 向量 API Key | 留空待填 |
| WEB_SEARCH_PROVIDER | 网页搜索供应商 | bocha |
| BOCHA_BASE_URL | 博查 API 根地址 | https://api.bocha.cn |
| BOCHA_API_KEY | 网页搜索 Key | 留空待填 |
| TAVILY_API_KEY | 可选国外搜索 Key | 仅 provider=tavily 使用 |
| APP_ACCESS_TOKEN | 可选私有工作台访问口令 | 空表示本机无需口令 |

同一个百炼 Key 如果拥有两种模型的权限，可填入 LLM_API_KEY 和 EMBEDDING_API_KEY 两处。地域、工作空间和模型权限必须与控制台一致。工作空间专属根地址可直接填写 BASE_URL；代码不强行覆盖它。

生成模型备选 DeepSeek：
- LLM_PROVIDER=deepseek
- LLM_MODEL=deepseek-flash（以自己控制台可用模型为准）
- LLM_BASE_URL=https://api.deepseek.com/v1
- LLM_API_KEY=自己的 DeepSeek Key
- 向量模型仍保持百炼，DeepSeek 生成 Key 不用于 Embedding。

## 每条命令的用途

先 cd 到项目目录，Docker Desktop 必须已运行：

~~~powershell
cd "D:\jupyter_notebook_file\AI项目学习\AI_agent"
docker info --format '{{.ServerVersion}} | {{.OperatingSystem}}'
docker compose config --quiet
docker compose up --build -d
docker compose ps -a
~~~

- docker info：确认后台引擎可访问。
- config --quiet：检查 YAML 和变量语法，不打印包含密钥的完整配置。
- up --build -d：构建镜像并启动后台服务；数据库迁移成功后才启动 API/worker。
- ps -a：列出包含已退出 migrate 的所有服务。
- 修改 .env 后运行 docker compose up -d，让发生配置变化的容器重新创建。仅 restart 无法更新容器环境变量。

访问 http://localhost:8080。运行配置面板显示模型与密钥是否配置，不显示密钥值。若设置了 APP_ACCESS_TOKEN，在工作台口令对话框输入对应口令。

## 文件入库

上传接口返回 202，仅表示任务进入 PostgreSQL 队列。worker 解析文件、切块、批量 Embedding 和 Qdrant upsert。页面轮询真实进度，ready 才能参与检索。

支持 TXT、Markdown、CSV、JSON、PDF、DOCX、PPTX，默认最大 10 MB。扫描版 PDF 没有文本层，需要先 OCR；本项目不会伪造扫描文字。

更换向量模型会使用新的模型指纹 collection。旧向量保留，页面显示“需要重建”；点击重建后原文重新向量化。ready 文档才参与检索，处理到一半或失败的索引不会成为引用。

## 真实调用验收

只检查部署与配置、不调用收费模型：

~~~powershell
uv run python scripts/check_deployment.py
~~~

它检查前端、基础设施和脱敏运行配置；生成密钥尚未填写时，验证 502 与失败记录，不会自动调用演示模型。报告在 evaluation/deployment-report.json。

Windows 直接运行 Python API（容器部署无需这个参数）：

~~~powershell
uv run uvicorn app.main:app --app-dir backend --loop app.core.event_loop:selector_loop_factory --host 127.0.0.1 --port 8001
~~~

新版 Uvicorn 的默认 Windows Proactor 循环不适合 psycopg 异步连接；显式 loop 工厂避免只设置 policy 仍失效的情况。

~~~powershell
uv run python scripts/verify_project.py
~~~

脚本通过真实 HTTP 上传自己生成的唯一内容文件，等待 worker 完成，检索、执行 Agent tool_calls、读取 SSE、测试请求幂等与消息持久化、下载原文，并清理自己创建的记录。报告在 evaluation/http-report.json。

基础设施集成测试需要 Worker 与本机 Python 使用一致的测试模型和向量配置，会创建临时记录。详细步骤和云服务费用边界见 [开发与验证](development.md)，不要直接在重要工作空间运行。

模拟结果只证明工程流程，真实请求成功也不等于完整回答质量评估。建议用自己的典型问题人工核验正确性、引用和无答案时的说明。

## 明确的无密钥测试模式

覆盖配置移到 `backend/tests/fixtures/env.demo.example`，不会默认加载。必须先加载测试副本自己的 `.env` 以保留数据库凭据，再加载该覆盖文件。此操作会切换运行中的模型配置，仅在测试工作空间使用，命令见 [开发与验证](development.md)。

## 保留 Ollama 技术入口

默认不启用，配置方式已统一写入 [配置说明](configuration.md#ollama-可选入口)。模型需支持工具调用，小模型不能保证与云端相同的效果。更换向量模型后需重建索引。

## 排错与数据

~~~powershell
Invoke-RestMethod "http://localhost:8001/api/v1/health/ready"
docker compose logs --tail 80 api
docker compose logs --tail 80 worker
docker compose logs --tail 80 migrate
~~~

- health/ready 只检查 PostgreSQL、Redis、Qdrant，不调用收费模型。
- 聊天返回 502/SSE error：检查模型名称、Key、配额、网络和上游服务。
- 文件 failed：检查 worker 日志、文本格式与向量 API Key。
- 409：同会话运行中、重复请求 ID 或文档处理中的冲突。
- 429：聊天超过该会话的分钟限额。
- 同一已完成 request_id 重发会返回已存结果，不重复产生消息。
- 用户取消或失败时，user 消息记录终态，不加入下一轮模型历史。
- 会话删除同时清理消息、ChatRun 和 LangGraph Checkpoint。

数据位于项目 data/postgres、data/redis、data/qdrant、data/uploads。停止可用 docker compose down；它不会删除这些绑定目录。备份时要同时保存 PostgreSQL、Qdrant 和原文件，才能完整恢复引用。

Docker Desktop 无法访问 .sock 时，先检查进程与具体运行时路径，不要直接恢复出厂设置或删除项目数据。涉及数据库的清理前先备份并核对目标目录。
