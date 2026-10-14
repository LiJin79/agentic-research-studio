# 配置说明

## 入口与优先级

根目录只保留 `.env.example` 作为使用者样例。首次部署复制为 `.env` 后填写真实值，已有配置不要覆盖。`.example` 不会自动加载。

直接运行 Python 时，`Settings` 读取项目根目录 `.env`，进程环境变量优先。Docker Compose 默认读取根目录 `.env`，再显式将配置注入 API 和 Worker。容器连接数据库使用 `postgres:5432` 等服务名，本机直连使用 `localhost:5433` 等映射端口。

修改 `.env` 后要重新创建对应容器，仅 `restart` 不会更新环境变量：

```powershell
docker compose config --quiet
docker compose up -d --no-deps --force-recreate api worker
```

不要将 API Key 放入前端变量，也不要发布展开的 `docker compose config` 输出。

## 数据库

| 变量 | 用途 |
| --- | --- |
| `POSTGRES_USER`、`POSTGRES_DB` | 用户和数据库名称 |
| `POSTGRES_PASSWORD` | 首次部署自行设置，样例为占位值 |
| `POSTGRES_DSN` | 本机异步 SQLAlchemy 连接串 |
| `LANGGRAPH_POSTGRES_DSN` | 本机 LangGraph Checkpoint 连接串 |

本机连接串中的密码应与数据库用户一致。容器连接串由 Compose 构造，不直接采用样例的 localhost 地址。

已有数据目录时，更换 `.env` 中的密码不会修改 PostgreSQL 用户密码。需要同步更新数据库角色和运行配置，不能通过删除数据目录来修复。复杂密码在 URI 中需做百分号编码，Compose 变量中的 `$` 也需要正确转义。

## 云模型

默认使用百炼生成模型和向量模型，二者可以使用不同 API Key。区域、工作空间、地址与模型权限必须和供应商控制台一致。

| 变量 | 用途 |
| --- | --- |
| `LLM_PROVIDER`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_API_KEY` | 默认生成模型 |
| `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY` | 向量模型 |
| `EMBEDDING_DIMENSIONS` | 与向量响应维度一致 |
| `DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、`MINIMAX_API_KEY`、`ZHIPU_API_KEY` | 模型菜单的可选凭据 |

可选供应商默认模型名是适配配置，需按账户实际可用模型调整。存在适配代码不等于每种模型都做过真实认证测试。生成 Key 不会自动用于其他供应商的向量接口。

## 搜索和扩展工具

`WEB_SEARCH_PROVIDER=bocha` 使用 `BOCHA_API_KEY`，改成 `tavily` 后使用 `TAVILY_API_KEY`，只配置需要的服务即可。

`GITHUB_TOKEN`、`CONTEXT7_API_KEY`、`AMAP_API_KEY` 和 `QWEATHER_API_KEY/QWEATHER_API_HOST` 已统一收录到 `.env.example`。未配置凭据的受限工具不会交给模型，状态见 [工具能力](tools.md)。

## Ollama 可选入口

默认不启用本地模型，也不会自动下载模型。下面是可选运行方式，不代表已经在当前硬件上验收。操作前备份配置，修改现有 `.env` 的对应项目：

```dotenv
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:1.5b
LLM_BASE_URL=http://localhost:11435
LLM_BASE_URL_DOCKER=http://ollama:11434
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://localhost:11435
EMBEDDING_BASE_URL_DOCKER=http://ollama:11434
EMBEDDING_DIMENSIONS=768
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen2.5:1.5b
```

显式启动 profile：

```powershell
docker compose --profile local-llm up --build -d
```

当前 Compose 声明 GPU 设备，需满足 Docker NVIDIA GPU 运行条件。模型需要支持工具调用，小模型不一定可靠。接口支持与向量维度需要按实际返回核对。

仅在菜单中增加本地生成候选时，可以保持云生成/向量配置，设置 `OLLAMA_ENABLED=true`、`OLLAMA_MODEL` 和 Ollama 地址，然后只启动 Ollama 服务并手动拉取模型：

```powershell
docker compose --profile local-llm up -d ollama
docker compose exec -T ollama ollama pull qwen2.5:1.5b
docker compose up -d --no-deps --force-recreate api worker
```

该方式不启动 `ollama-init`，因为初始化服务从默认 `LLM_MODEL/EMBEDDING_MODEL` 读取下载名称，云模型名不适用于 Ollama。

更换向量模型会选择新的指纹集合，旧文档需重建索引。恢复云模式时，要恢复模型、向量和 Docker 专用地址，不能遗留 Ollama 地址覆盖云地址。确认不再依赖 Ollama 后可停止它，不删除数据。

## 测试覆盖

模拟配置在 `backend/tests/fixtures/env.demo.example`，不是日常运行配置。只有显式加载才生效，不会自动回退到模拟模型。步骤见 [开发与验证](development.md)。
