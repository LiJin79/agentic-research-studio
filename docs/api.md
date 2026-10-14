# API 和事件协议

基础前缀 /api/v1，可选 Authorization: Bearer APP_ACCESS_TOKEN。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health/live | API 存活 |
| GET | /health/ready | PostgreSQL、Redis、Qdrant 可达性 |
| GET | /runtime | 不含密钥的模型、索引与搜索配置 |
| POST | /sessions | 创建会话 |
| GET | /sessions | 会话分页 |
| GET | /sessions/{id} | 会话详情 |
| PATCH | /sessions/{id} | 重命名，body 为 title |
| DELETE | /sessions/{id} | 消息、ChatRun 与 Checkpoint 生命周期清理 |
| GET | /sessions/{id}/messages | 消息分页及来源/轨迹元数据 |
| POST | /documents/upload | multipart 文件排队，返回 202 |
| GET | /documents | 文档与实时进度分页 |
| GET | /documents/{id} | 持久入库状态 |
| POST | /documents/{id}/reindex | 重试或模型版本重建，返回 202 |
| GET | /documents/{id}/download | 原文下载 |
| DELETE | /documents/{id} | 删除原文、已登记版本向量和业务记录 |
| POST | /documents/search/test | 仅执行向量检索 |
| POST | /chat | 一次完整最终回答 |
| POST | /chat/stream | 真正增量 SSE |

聊天输入：
~~~json
{
  "session_id": "真实会话 UUID",
  "request_id": "每次新请求生成的 UUID",
  "message": "请根据文档解释报销期限",
  "use_web_search": false
}
~~~

相同请求 ID 与相同参数会复用已完成结果；更改参数或使用其他会话会被拒绝。request_id 不提供时后端生成，前端始终明确生成。

SSE 事件：
- status：stage 和 message，公开节点进度。
- tool_start：name、agent，模型工具调用开始。
- tool_end：name、agent、detail，工具结果摘要或错误。
- token：content，来自上游的真实文字增量。
- answer_reset：丢弃旧草稿，开始流式修订。
- done：完整 ChatResponse，含最终 answer、sources、trace、provider、metadata。
- error：message 与 retryable。HTTP 头发送后的错误通过此事件报告。
- : keepalive 为空闲心跳，客户端不作为 JSON 事件处理。

完成必须以 done 为准，token 只是草稿。metadata.verified=false 表示修订达到上限仍未通过检查，页面需要提示核对依据。
