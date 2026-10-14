# 开发与验证

## 常规测试

Python 开发使用 3.11–3.13 和 uv。Docker 镜像使用 3.11，容器部署不依赖本机虚拟环境。

```powershell
uv sync --frozen
uv run pytest -p no:cacheprovider
```

默认排除 `integration`，常规测试使用模拟模型响应与 HTTP 传输，检查参数、状态、工具执行、引用和解析边界。不要把工程测试结果当作真实模型质量指标。

前端：

```powershell
cd frontend
npm ci
npm test
npm run build
```

基础设施测试位于 `backend/tests/integration`，会创建数据库、文档和会话记录，不要直接在重要工作空间上运行。

## 显式模拟环境

覆盖文件 `backend/tests/fixtures/env.demo.example` 设置 `mock/hash`，并清空云服务凭据，避免继承第一份配置中的真实 Key。结果只证明工程流程，不涉及真实语义向量或回答质量。

下列操作会切换同一 Compose 项目的运行配置。只在测试副本/工作空间中使用，不要在日常工作台执行。本项目固定了端口、容器名和数据路径，仅增加 `-p` 不足以隔离并行部署。

先准备测试副本自己的 `.env` 和数据库密码，再执行：

```powershell
docker compose --env-file .env --env-file backend/tests/fixtures/env.demo.example config --quiet
docker compose --env-file .env --env-file backend/tests/fixtures/env.demo.example up --build -d
uv run python scripts/verify_project.py
```

先加载 `.env` 保留数据库配置，再由测试文件覆盖模型设置。覆盖文件没有数据库密码。shell 中的环境变量优先于 env 文件，先确认终端没有覆盖模拟模式或重新注入云凭据。

本机集成测试也需与 Worker 使用同一测试配置：

```powershell
$env:LLM_PROVIDER='mock'
$env:LLM_MODEL='demo'
$env:EMBEDDING_PROVIDER='hash'
$env:EMBEDDING_MODEL='hash-test'
$env:EMBEDDING_DIMENSIONS='384'
$env:RETRIEVAL_MIN_SCORE='0'
uv run pytest -m integration -p no:cacheprovider
Remove-Item Env:LLM_PROVIDER,Env:LLM_MODEL,Env:EMBEDDING_PROVIDER,Env:EMBEDDING_MODEL,Env:EMBEDDING_DIMENSIONS,Env:RETRIEVAL_MIN_SCORE
```

这些变量仅影响当前终端。如果原先已有同名变量，应记录并恢复原值，而不是直接删除。访问口令、本机 DSN 和基础设施端口也必须与测试副本一致。

测试副本需恢复云配置时，清理终端覆盖后运行 `docker compose up -d`。不要将测试数据目录覆盖到日常部署。

## 验收入口与费用

| 脚本 | 用途 | 外部调用 |
| --- | --- | --- |
| `scripts/check_deployment.py` | 基础设施与脱敏配置 | 不主动调用收费模型 |
| `scripts/verify_project.py` | 上传、检索、聊天、SSE、幂等和持久化 | 云模式可能产生生成/向量费用 |
| `scripts/verify_search_office.py` | 搜索、域名约束、报告导出 | 可能调用搜索/生成服务 |
| `scripts/verify_utility_tools.py` | 工具探测 | 会访问外部 API，受网络、限额和计费影响 |
| `scripts/verify_boundaries.py` | 部署接口边界 | 先阅读脚本条件，不用于质量统计 |

脚本清理自己的记录，失败时仍需检查是否留下临时数据。本机输出写入被忽略的 `evaluation/`，不随仓库提交。不要将个人会话、私有文档或密钥当作展示数据。

## 质量声明

健康检查仅代表基础设施可达，工具有代码不代表持续可用。需要质量指标时，另建固定问题、参考答案与来源，记录模型和数据版本及测量条件，不以单元测试数量代替准确率。
