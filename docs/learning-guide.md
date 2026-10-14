# 项目学习路线

2026-10-11 升级后的新增技术请先读 [upgrade-learning.md](upgrade-learning.md)。下面保留原始基础路线；以新版代码的方法名与行为为准。

这份路线按“一条请求经过哪些层”组织，不要求逐文件背代码。

## 第一阶段：HTTP 与分层

先读 `app/main.py`、`api/router.py`、`api/v1/sessions.py`、`services/session_service.py` 和 `repositories/session_repository.py`。

目标是能说清：HTTP 请求怎样经过 Endpoint、Service、Repository，最后进入 PostgreSQL；为什么 API 层不直接写 SQL。

## 第二阶段：知识库入库

依次读 `api/v1/documents.py`、`services/document_service.py`、`vector/parsing.py`、`chunking.py`、`embeddings.py` 和 `indexing.py`。

重点跟踪同一份数据的形态变化：`UploadFile -> bytes -> str -> list[TextChunk] -> list[float] -> Qdrant PointStruct`。

## 第三阶段：LangGraph

依次读 `agents/state.py`、`agents/graph.py`、`agents/nodes/workflow.py` 和 `agents/prompts.py`。

先手画节点和边，再跟踪 `AgentState` 字段。Supervisor 只选路线，研究节点只收集证据，Writer 只组织回答，Verifier 只做质量检查。

## 第四阶段：聊天编排与记忆

阅读 `services/chat_service.py`、`db/checkpointer.py` 和消息 Repository。

区分两类记忆：`messages` 是用户可见的业务历史；LangGraph Checkpoint 是图恢复所需的内部状态。两者都在 PostgreSQL，但职责不同。

## 第五阶段：Vue 与 Docker

阅读 `frontend/src/api.js`、`App.vue`、`nginx.conf` 和 `docker-compose.yml`。

重点理解浏览器只认识 HTTP/SSE；Nginx 负责页面和反向代理；Compose 负责服务发现、启动依赖和端口映射。

## 建议练习

1. 在 Swagger 创建会话、上传 Markdown、测试检索，再调用 `/chat`。
2. 在 `graph.py` 画出 direct、knowledge、web、hybrid 四条路线。
3. 把 `CHUNK_SIZE` 从 800 改为 400，重新上传并比较 chunk 数量。
4. 把 mock 切换到 Ollama 或通义，观察业务代码为何无需修改。
5. 为 `citation_verifier` 增加一个失败后重新检索的分支，并补测试。
