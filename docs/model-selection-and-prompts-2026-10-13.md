# 字号、模型选择与角色提示词

## 页面使用

访问 http://localhost:8080/ ，必要时 Ctrl+F5 强制刷新。

- 右上角减号缩小正文，加号放大，中间的字号按钮恢复 18px。选择范围为桌面 16～22px；手机减 1px，但不低于 16px。不会改变浏览器缩放。
- 右上角模型菜单选择下一次提问的生成模型，生成中不能切换。选择保存在当前浏览器，不会更改其他用户的选择。
- 新回答记录实际使用的模型名称，刷新后仍可查看。旧消息没有该记录时不推测其模型。
- 生成模型切换不影响 Embedding 模型、Qdrant 集合或现有文档，不需要重建向量索引。

## 可选生成模型

| 选项 | 默认模型名 | 配置密钥 | 当前情况 |
| --- | --- | --- | --- |
| 当前默认 | 现有 `LLM_MODEL`，当前为 qwen-plus | 原有 `LLM_API_KEY` | 保留原配置 |
| 通义 Qwen Plus | qwen-plus | 可复用原有通义 `LLM_API_KEY` | 已配置 |
| 通义 Qwen Flash | qwen-flash | 可复用原有通义 `LLM_API_KEY` | 已完成一次真实切换验证 |
| DeepSeek | deepseek-flash | `DEEPSEEK_API_KEY` | 已接入候选目录，尚未填写 Key |
| MiniMax | MiniMax-M3 | `MINIMAX_API_KEY` | 已接入候选目录，尚未填写 Key |
| 智谱 GLM | glm-4.7 | `ZHIPU_API_KEY` | 已接入候选目录，尚未填写 Key |
| Ollama 本地 | qwen2.5:1.5b | 无需云端 Key；`OLLAMA_ENABLED=true` | 默认关闭；还需启动本地服务、下载模型 |

“已配置”只表示服务器存在 Key，不保证账户余额、模型权限、网络或调用配额正常。

各平台的 Key 不能互相替代。模型名和地址可通过对应的 `*_MODEL`、`*_BASE_URL` 配置更改。国内 MiniMax 默认地址为 `https://api.minimax.cn/v1`。MiniMax 的 JSON 决策由提示词和 Pydantic 校验，不冒充原生严格 JSON Schema 保证；其思考字段仅保留在工具消息协议中，不显示在回答里。

## 后续填 Key

项目 `.env` 的开头已经加入空白配置区。只填自己开通的平台：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
MINIMAX_API_KEY=你的MiniMax密钥
ZHIPU_API_KEY=你的智谱密钥
```

不用重填当前通义 Key，不要改 `EMBEDDING_API_KEY`，不要将真实 Key 发送到聊天或提交到版本库。填完后在项目目录执行：

```powershell
docker compose up -d --no-deps --force-recreate api worker
```

这条命令让两个后端进程重新读取 `.env`，不重建数据库、不重建向量库。刷新页面后，已配置选项即可选择。Ollama 仍需要 `--profile local-llm` 的服务配置，不会因出现菜单选项就自动占用 GPU。

## 提示词分工

参考本机 `open_deep_research-main/open_deep_research-main/src/open_deep_research/prompts.py` 的角色职责、输入信息、任务步骤和边界约束组织方式，而不是复制不存在的工具名称。

本项目集中在 `backend/app/agents/prompts.py`：

| 名称 | 消费位置 | 作用 |
| --- | --- | --- |
| `QUALITY_RULES` | 写作、校验、修订模板 | 区分证据、常识、假设与建议；限制虚构性能数字、绝对断言和生产就绪承诺 |
| `SUPERVISOR_PROMPT` | `AgentNodes.supervisor()` | 根据当前任务选资料路线；假设架构题不因出现“知识库”就强行检索内部文档 |
| `RESEARCH_SYSTEM_PROMPT` | `ResearchAgent.model()` | 工具检索、关键词改写、来源优先级和研究预算 |
| `ANSWER_PROMPT` | `AgentNodes.answer_writer()` | 简单题简洁，复杂题按要求展开职责、数据流、取舍、异常与验证 |
| `VERIFY_PROMPT` | `AgentNodes.verifier()` | 检查任务完成度、证据一致性和技术边界，不仅检查编号存在 |
| `REVISE_PROMPT` | `AgentNodes.revise_answer()` | 修正具体问题、保留有效细节，不通过删除全部内容逃避修订 |
| `PRESENTATION_PROMPT` | `ArtifactService.create()` | 将已有回答组织为 PPT 大纲，不增加新事实或引用 |

相近规则只定义一次，角色模板各自指定任务。新增提示词不意味着新增节点，本次没有把完整 Deep Research 图复制进项目。

## 代码与数据流

```text
App.vue 的 selectedModelId
  → streamChat({model_id, ...})
  → ChatRequest.model_id
  → ChatService._execute() 校验目录与配置
  → get_agent_graph(checkpointer, model_id)
  → 独立模型客户端执行各角色节点
  → 回答 metadata 保存 model_id/model
```

模型目录为 `backend/app/llm/catalog.py`。公开接口仅返回名称、模型 ID 和配置状态，不返回密钥或端点。选项参与图缓存键和请求幂等哈希，不能一边显示新模型一边复用旧客户端。同一请求 ID 更换模型返回 409。未配置选项返回 422，不留下新的用户消息。

PPT 根据该条回答记录的模型选项选择客户端；模型选项本身若被服务器管理员改配，后续导出使用其当前配置。Word 排版不消耗额外模型调用。

## 验证与限制

- 50 项后端单元测试、6 项真实 PostgreSQL/Redis 集成测试、9 项前端测试通过，Ruff 通过。
- 1440、390、320、1024、1920 五种宽度完成布局、字号边界、模型参数、偏好保存与弹窗键盘检查。
- 一次真实通义 Flash 验证通过 SSE、模型元数据、幂等回放、切换冲突与未配置选项拒绝检查。验证记录保存在 `evaluation/model-font-controls/live-model.json`，临时会话已删除。
- 本轮先验证连接，再针对暴露的技术边界补充提示词并确认。模型检查通过仍不是事实认证，不能保证所有新回答无错误。
- DeepSeek、MiniMax、智谱当前仅完成目录、参数和协议模拟测试，没有这些平台的真实 Key，不能宣称完成真实联调。
- 未改数据库表或迁移。新增 `.env` 的空配置项，原有模型、向量及搜索 Key 保持不变。
- 本次对模型的引用机械检查增加了加粗/下划线/链接编号检测，不能只改 Markdown 样式就绕过检查。

## 官方接口依据

- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- [MiniMax 国内 OpenAI SDK 接口](https://platform.minimax.cn/docs/api-reference/text-openai-api)
- [MiniMax 兼容参数说明](https://platform.minimax.io/docs/api-reference/text-chat-openai)
- [智谱 GLM-4.7](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7)
- [Redis 事务边界](https://redis.io/docs/latest/develop/using-commands/transactions/)

模型名、区域、权限与端点以后可能变化，应以自己的平台控制台和官方接口文档为准。
