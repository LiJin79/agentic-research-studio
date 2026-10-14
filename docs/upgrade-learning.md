# 新版代码学习入口

之前的数据库、缓存和请求链路基础仍然适用。此次重点不是重学所有文件，而是理解以下新增的工程行为。

## 1. 真实模型与工具协议

先看 .env.example 和 backend/app/core/config.py 的 Settings，再看 llm/factory.py。

- OpenAICompatibleLLMClient.generate()：完整模型请求，用于 JSON 路由和校验。
- chat()：传送工具 JSON Schema，获取模型生成的 tool_calls，但不执行工具。
- stream()：读取上游真实 SSE 增量，收到结束帧才认定输出完整。
- ResearchAgent.model()、tools()：位于 agents/subgraphs/research.py，前者决定工具及参数，后者检查参数、执行 StructuredTool.ainvoke()，用相同 tool_call_id 返回观察。

先跟踪一个问题：question -> messages -> tool_calls.function.arguments -> SearchInput -> 搜索结果 -> role=tool -> 模型下一轮。不要把工具调用消息误认为工具已经执行。

## 2. 独立研究子图与证据

看 agents/graph.py 的 build_agent_graph()，以及 nodes/workflow.py 的 AgentNodes。

- supervisor()：选择 direct、knowledge、web、hybrid，代码强制执行用户的联网许可。
- _research()：给每个研究员独立初始 State，不直接修改父图。
- parallel_research()：并发等待两份结果，再合并，不让两条支线同时覆盖同一个列表。
- evidence.py 的 merge_evidence()：去重、限制资料长度、分配 K/W 引用编号。
- answer_writer()、verifier()、revise_answer()：草稿、严格结构与引用校验、有限次修订。verified 表示校验结果，不等于事实百分百正确。

## 3. 一次聊天的完整生命周期

按顺序看 frontend/src/App.vue 的 sendQuestion() -> api.js 的 streamChat() -> frontend/nginx.conf -> api/v1/chat.py 的 stream_chat() -> services/chat_service.py 的 _execute()。

重点追踪这些新增操作：

1. request_id 用于同一个请求的幂等，而 session_id 标识一整段会话。
2. Redis 会话锁和原子限流先保护入口。
3. PostgreSQL 先保存 pending 用户消息及 running 的 ChatRun，然后释放事务。
4. 从已完成业务消息整理 history，并重置本轮 context、sources、trace 等 State，避免旧证据污染下一轮。
5. 图的 custom 事件通过有界队列、SSE、Nginx 到浏览器，token 是草稿，answer_reset 清除待修订内容，done 才是最终确认。
6. 成功后保存助手消息及 completed；失败/取消保存终态，下一轮历史跳过这些失败问题。
7. 显式 aclose() 逐层关闭生成器，即使断开恰好发生在队列背压中，也释放会话锁和运行资源。

## 4. 入库从同步操作变成持久任务

按 upload_document() -> DocumentService.upload()/process_job() -> workers/ingestion.py 的 claim_job()/run_worker() -> vector 模块阅读。以实际文件中的方法定义为准。

- 202 表示任务已受理，不表示文档已可以检索。
- PostgreSQL IngestionJob 是持久任务记录；SKIP LOCKED 让多个 worker 不领取同一条任务。
- Redis 只缓存进度，任务是否完成仍以数据库状态为准。
- Embedding 分批后检查数量与维度，Qdrant 使用稳定 point id，重试不会无条件追加重复片段。
- 模型指纹隔离 collection；切换模型后旧文档必须重新入库。
- KnowledgeRetriever.search() 只查询数据库中 ready、且模型版本匹配的文档。

## 5. 通过故障理解工程代码

最后结合 backend/tests/test_production_agent.py、integration/test_reliability.py、frontend/tests/sse.test.mjs 阅读测试。

每次只回答一个问题：如果模型输出错误 JSON、工具参数非法、上游流截断、用户取消、重复提交、Redis 不可用，代码怎样防止把失败误报成成功？

运行和密钥配置见 runbook.md；实测与尚未验证部分见 validation.md。旧学习计划的基础内容可以保留，本文件对应本次升级后的新增行为。
