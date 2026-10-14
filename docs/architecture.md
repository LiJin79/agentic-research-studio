# 项目架构

## 请求路径

~~~mermaid
flowchart TD
  UI[Vue 工作台] --> NG[Nginx 静态文件与 API 转发]
  NG --> API[FastAPI]
  API --> CHAT[ChatService 请求幂等/会话锁/历史]
  CHAT --> GRAPH[LangGraph 主图]
  GRAPH --> PG[PostgreSQL 消息/运行/Checkpoint]
  GRAPH --> REDIS[Redis 限流/租约/缓存]
  GRAPH --> KB[Knowledge Research 子图]
  GRAPH --> WEB[Web Research 子图]
  KB --> QDRANT[Qdrant 文档索引]
  WEB --> SEARCH[博查或 Tavily]
  GRAPH --> LLM[通义/DeepSeek/可选 Ollama]
~~~

## 图和工具调用

supervisor 通过严格 RouteDecision JSON 选择 direct、knowledge、web、hybrid。工具不是固定 Python 函数冒充模型决策：研究子图将 StructuredTool 的 Schema 发给模型，模型返回原生 tool_calls，执行器校验工具名和 SearchInput，执行后生成 role=tool 消息并配对 tool_call_id。下一轮模型依据观察决定是否继续搜索。

每位研究员有独立 State。Hybrid 使用 asyncio.gather 并发执行内部与网页研究，完成后合并去重证据，不并发写同一个共享字段。

~~~text
START → supervisor
  direct → writer
  knowledge → knowledge researcher → writer
  web → web researcher → writer
  hybrid → parallel research（两个独立研究子图）→ writer

writer → verifier
verifier → END（通过或达到上限）
verifier → revise → verifier（未通过且未达到上限）

研究子图：
START → model → tools → model … → END
~~~

## State 和记忆

AgentState 每轮由 ChatService 显式重置全部字段，避免复用 thread_id 时残留旧答案或资料。历史来自 PostgreSQL messages，并限制最近消息字符预算；失败和取消的待回答问题不进入模型历史。

messages：用户可见长期记录。
chat_runs：请求幂等、执行结果和失败终态。
Checkpoint：LangGraph 内部快照，用于状态与执行追踪；进程级 psycopg 连接池支持多会话。
同一 session_id 用 Redis 原子租约串行运行。会话删除清理以上三类数据及快照。

## 证据与回答

统一证据包含 source_type、title、snippet、url/document_id、score 和 citation_id（K1/W1）。规范 URL 与文本片段去重，限制来源数量、单片段字符与总字符。writer 从模型 SSE/NDJSON 真正读取内容增量。

verifier 使用 StrictBool 校验结果，并机械核对引用编号。无效 JSON 不放行，修订后再次验证。达到次数上限仍不可靠时，最终响应 metadata.verified=false，页面明确展示反馈。

## SSE

status、tool_start、tool_end、token、answer_reset、done、error 为公开事件。写作阶段是草稿，必要时 answer_reset 清除旧草稿并流式输出修订；done 中的 answer 为最终版本。队列有背压，15 秒空闲心跳；客户端取消会取消服务任务并记录终态。前端使用 TextDecoder + buffer，支持分块中文、CRLF 和多行 data，缺少 done 不能误判完成。

## 入库与索引版本

上传只建立持久 job，worker 用 PostgreSQL SKIP LOCKED 领取任务。解析在后台线程，网络向量请求异步执行；云端 Embedding 最多十段一批，校验数量、顺序、维度和有限数值。

collection 名称带 embedding provider/model/dimensions 指纹。更换模型隔离旧索引，通过 reindex 原文件重建，不混用向量空间。检索限制为 PostgreSQL ready 且模型指纹匹配的文档。失败清理当前部分索引，重试使用稳定 point id 不产生重复点。

## 边界

当前是单个私有共享工作空间，不是多租户 SaaS，不包含用户权限隔离。APP_ACCESS_TOKEN 可保护 API；端口默认本机绑定。生产公网部署还需 TLS、正式认证与按业务设计的备份策略。没有云密钥时只验证工程协议与明确 demo 模式，不宣称已评估云模型质量。
