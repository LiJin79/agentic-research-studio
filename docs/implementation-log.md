# 实施记录

## 2026-09-18 第一阶段 工程底座

### 已完成

- 创建后端分层目录和前端、评估、脚本目录。
- 使用应用工厂创建FastAPI，避免在导入模块时连接外部服务。
- 建立统一的Pydantic Settings配置入口。
- 建立`/api/v1`路由前缀。
- 实现存活检查和初始就绪检查。
- 建立pytest测试入口。
- 记录目标架构、模块职责和旧代码迁移映射。

### 当前可验证范围

- FastAPI可以独立启动。
- 根接口可以返回项目名称、版本和文档地址。
- 健康检查不依赖模型或数据库。

### 尚未实现

- 聊天接口和SSE。
- 模型Factory。
- LangGraph主图与子图。
- 文档上传、后台解析、混合检索和重排。
- Vue页面迁移。

## 2026-09-18 第二阶段 数据基础设施

### 已完成

- Docker Compose加入PostgreSQL、Redis、Qdrant、迁移容器和API容器。
- 使用固定宿主机端口，避免与旧学习项目冲突。
- 使用项目内`data`目录固定保存数据库数据。
- 增加SQLAlchemy异步连接和请求级Session工厂。
- 建立用户、会话、消息、文档和文档处理任务模型。
- 增加Alembic初始迁移及升级、降级逻辑。
- 使用`AsyncPostgresSaver.setup()`创建LangGraph Checkpoint表。
- 使用`LANGGRAPH_STRICT_MSGPACK=true`限制Checkpoint反序列化范围。
- Redis与Qdrant使用异步客户端，并在FastAPI关闭时释放连接。
- `/api/v1/health/ready`并发检查三个依赖，故障时返回503。

### 集成验证

- PostgreSQL、Redis、Qdrant和API容器均通过健康检查。
- 一次性迁移容器正常以状态码0退出。
- PostgreSQL中存在5张业务表、Alembic版本表和4张Checkpoint表。
- Redis返回`PONG`。
- Qdrant报告版本`1.19.1`。
- Ruff检查通过，pytest共6项通过。

### 解决的问题

最初迁移程序在已有事件循环中调用Alembic，而Alembic又执行`asyncio.run()`，产生嵌套事件循环错误。现在改为先同步调用Alembic，再单独启动异步Checkpoint初始化。

验收时还发现上一阶段的本地Uvicorn进程与Docker同时监听8001端口。停止遗留进程后，宿主机请求已正确进入Docker API容器。

### 下一小步

1. 建立Repository和Session Service。
2. 提供会话创建、列表、消息查询和删除接口。
3. 用真实数据库集成测试验证事务与级联删除。
4. 随后实现模型Factory和带Checkpoint的最小LangGraph聊天图。

## 2026-09-18 第四阶段 完整 Agentic RAG

### 已完成

- 实现 mock、Ollama、通义和 DeepSeek 模型适配层。
- 实现 Hash、Ollama 和 OpenAI 兼容 Embedding 适配层。
- 实现六节点 LangGraph：调度、内部研究、联网研究、写作、校验、修订。
- 使用 PostgreSQL Checkpointer 按会话保存图状态。
- 实现六种文档格式解析、重叠切分、Qdrant 入库、检索与删除。
- 使用 Redis 保存限流计数和短期入库进度。
- 实现普通聊天接口和 POST SSE 流式接口。
- 完成 Vue 3 工作台和 Nginx 反向代理。
- 全部类和函数补充职责说明，关键数据变化补充行内注释。

### 验证结果

- Ruff 静态检查通过。
- 12 项普通测试通过。
- 4 项真实基础设施集成测试通过。
- Vue 生产构建通过，npm 审计无漏洞。
- API、PostgreSQL、Redis、Qdrant 和前端容器正常启动。

### 教学与生产边界

- mock 模型和 Hash Embedding 用于零配置教学，不代表生产效果。
- SSE 已稳定定义前后端协议，目前文本块由完整回答切分；真实 token 流可在 LLM 层继续实现。
- 文档在请求内同步处理，适合小文件演示；生产环境可把同一 Service 调用迁移到 Celery、Dramatiq 或 Arq worker。

## 2026-09-18 第三阶段 会话业务层

### 已完成

- 创建Session和User Repository，集中管理SQLAlchemy查询。
- 创建Session Service，由业务层统一提交事务。
- 增加统一的资源不存在异常和FastAPI异常处理器。
- 实现会话创建、分页列表、详情、消息列表和删除接口。
- 保留内部`append_message()`，供后续ChatService保存用户和AI消息。
- 用户ID存在时先验证用户，避免依赖数据库异常表达业务规则。
- 会话删除通过PostgreSQL外键级联删除消息。
- 分离普通测试与需要Docker的集成测试。

### 验证结果

- 6项默认测试通过。
- 3项PostgreSQL集成测试通过。
- HTTP全链路完成会话创建、查询、消息读取和删除。
- 真实写入消息后能够重新读取；删除会话后消息数量归零。
- Ruff静态检查通过。

### 解决的问题

Repository定义了名为`list()`的方法，后续类体中的`list[Message]`被Python解释为该方法，而不是内置列表类型。通过启用延迟类型标注解决了类作用域名称遮蔽问题。

### 下一小步

1. 建立Qwen、DeepSeek和Ollama统一模型Factory。
2. 定义第一版AgentState。
3. 创建带PostgreSQL Checkpointer的最小聊天图。
4. 实现非流式聊天接口，验证跨请求会话记忆。
# 完整改造记录

2026-10-11：新增原生工具研究子图、Hybrid 并发、真实 SSE、严格引用校验与修订循环。
新增 ChatRun 幂等与失败记录、Redis 原子限流和会话租约、Checkpoint 连接池与删除生命周期。
上传改为持久后台任务，新增 worker、模型指纹集合、分批向量化、重试/重建/下载。
默认云模型 qwen-plus + text-embedding-v4，网页搜索支持国内博查与可选 Tavily，Ollama 保留可选 profile。
前端重建为知识工作台，新增安全 Markdown、引用详情、工具进度、取消/重试和移动布局。
验证记录与限制见 evaluation 下报告及 docs/runbook.md。以下旧记录反映初始教学版本。
