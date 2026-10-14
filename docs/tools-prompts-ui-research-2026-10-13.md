# 实用工具、研究提示词与前端重设计调研

调研日期：2026-10-13。本文是方案，不代表这些能力已经接入。未安装依赖、修改环境变量或重启服务。服务价格、配额、国内网络可达性需要在接入时再次确认。

## 1. 项目定位与当前基础

建议定位为“可追溯的信息研究与报告工作台”，先做好科技与代码研究、天气与出行规划两个场景，而不是一次加入大量没有明确用途的工具。

当前 `backend/app/agents/subgraphs/research.py` 中主要是知识库搜索与网页搜索两个模型可调用工具。网页正文读取与搜索不是同一件事：搜索摘要可能不完整，不能默认为完整网页证据。当前 Word/PPT 通过应用的导出接口生成，不等于模型已能主动调用导出工具。

当前 `backend/app/agents/prompts.py` 已有调度、研究、写作、校验与修订提示词。下一步应补齐证据结构与执行控制，而不只是增加提示词长度。

## 2. 候选工具

下表中的函数名是建议的应用包装接口，不保证与外部服务的原始工具名相同。

| 优先级 | 建议工具 | 适用场景与返回结果 | 项目或官方资料 | 配置与边界 |
| --- | --- | --- | --- | --- |
| 第一批 | `read_webpage(url)` | 读取搜索命中的正文，返回标题、URL、发布时间、抓取时间、正文片段 | [Trafilatura](https://github.com/adbar/trafilatura) | Python 库；普通网页读取不需要独立服务 Key；不能承诺处理全部动态网页 |
| 第一批 | `read_document(document_id)` | 读取上传的 Word、PPT、PDF 等资料，形成可检索文本 | [Microsoft MarkItDown](https://github.com/microsoft/markitdown) | 按格式安装可选依赖；转换文本，不负责创建 Word/PPT；扫描件另需 OCR |
| 第一批 | `search_repo()`、`read_repo_file()` | 查找仓库、读取代码、解释模块；返回仓库、提交版本、文件路径与内容 | [GitHub MCP Server](https://github.com/github/github-mcp-server) | GitHub 授权令牌；只读模式与工具白名单；不开放推送、删库、执行代码 |
| 第一批 | `search_places()`、`plan_route()` | 查景点、地理位置、出行路线，返回地点、坐标、路线等结构化信息 | [高德官方 MCP](https://lbs.amap.com/api/mcp-server/summary) | 高德 Key；优先使用官方推荐的 Streamable HTTP；路线查询不等于购票或订酒店 |
| 第一批或后续细化 | `get_weather(location, date_range)` | 天气现状、预报与旅游出行参考，返回时间、温度、降水等字段 | [和风天气](https://dev.qweather.com/docs/start/) | 使用账户对应的 API Host 与 API Key/JWT；按套餐计费；不能保证长期预报准确 |
| 第二批 | `lookup_library_docs(library, version, question)` | 按版本查询技术文档，辅助 API 用法与代码解释 | [Context7](https://github.com/upstash/context7) | 目前核心工具为 `resolve-library-id`、`query-docs`；Key 可提升配额；核验文档来源和版本 |
| 第二批 | `search_papers(query)` | 科技专题与论文综述；返回标题、作者、DOI、年份、摘要和链接 | [OpenAlex](https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/)、[arXiv API](https://info.arxiv.org/help/api/user-manual.html) | OpenAlex 2026 年已引入 Key 和按使用量计费；论文元数据不等于全文；预印本不等于同行评审 |
| 第二批 | `analyze_table(dataset_id, operation)` | 分析上传的 CSV/表格，返回聚合值、分组结果与计算依据 | [DuckDB](https://github.com/duckdb/duckdb) | 限定数据集与允许操作；不能把模型生成的任意 SQL/Python 直接放到 API 进程执行 |
| 共用输出 | `create_report()`、`create_presentation()` | 把核验后的研究结果导出 Word/PPT，返回文件 ID 与下载链接 | 复用本项目 ArtifactService | 先预览与确认；保留来源、日期、限制；不得将整份二进制文件放进模型上下文 |

### 有价值但不宜优先增加的依赖

- 动态页面：用 [Crawl4AI](https://github.com/unclecode/crawl4ai) 作为正文提取失败后的受限后备。浏览器运行会增加内存、下载体积与维护成本，不应每个 URL 都启浏览器。
- 搜索加抓取服务：[Firecrawl](https://github.com/firecrawl/firecrawl) 可作为托管方案候选；已有博查可保留，无需只为接入新工具而再购买一个搜索服务。
- 复杂 PDF/OCR/表格：[Docling](https://github.com/docling-project/docling) 提供文档布局、OCR、表格处理能力；需衡量模型下载和资源消耗。[官方模型说明](https://docling-project.github.io/docling/usage/model_catalog/)

和风天气的 API Host 是账户专属配置，不宜照抄旧公共地址。[官方 Host 说明](https://dev.qweather.com/docs/configuration/api-host/)

### 可真正展示的任务

1. 科技研究：“比较某三个开源 RAG 框架，引用官方文档和仓库资料，给出适合本项目的选择，导出 Word。”
2. 代码解读：“分析指定仓库的某个模块，固定提交版本，指出入口、数据流、依赖和错误处理；未运行的部分明确标注。”
3. 出行规划：“为某城市规划两天行程，结合指定日期天气与高德路线，说明预估路程，输出行程表。”
4. 数据报告：“分析用户上传的销量 CSV，计算月度趋势、异常与分组结果，生成图表和 PPT。”

票价、酒店余房、营业时间、路线费用等没有对应实时数据时，必须说明未知或给出估算依据，不能让模型填补成事实。

## 3. 工具接入的共同框架

推荐每个工具具有：输入结构、描述、超时、重试策略、最大结果大小、缓存期限、权限和返回结构。

```text
用户需求 -> 调度器选择能力包
          -> 对该研究节点仅绑定相关工具
          -> 后端校验参数、权限、配额
          -> HTTP / MCP / 本地受限函数
          -> 统一证据结构
          -> 状态更新、整理与核验
```

MCP 是工具对接协议，不是让模型自动获得正确数据的保证。本项目已稳定使用的博查 HTTP 接口可以保留；GitHub、高德等有适合的 MCP 服务时再采用 MCP，不强行把所有工具改写成 MCP。

工具成功、没有结果、超时、未授权、余额不足应是不同的状态。不要把“调用失败”包装成“没有这条事实”。密钥只保存在服务端，不交给模型和浏览器。

网页读取要防止 SSRF：禁止访问本机、内网与云元数据地址，检查重定向及 DNS 变化，并限制时长、体积和并发。网页、仓库 README、Issue 都是外部不可信数据，不能覆盖系统指令。不得绕过登录、付费墙或验证码。

GitHub 官方服务提供只读与工具选择配置；但只读标记本身不是完整安全边界，还要限制令牌权限和可访问仓库。[配置文档](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md)

## 4. 借鉴 Open Deep Research 的哪些部分

本地参考文件是 `open_deep_research-main/open_deep_research-main/src/open_deep_research/prompts.py`：

| 本地位置 | 借鉴内容 | 本项目应该增加的约束 |
| --- | --- | --- |
| 第 3 行 `clarify_with_user_instructions` | 信息不充分时澄清 | 简单问题不反复追问；旅游才问日期、预算、出行方式 |
| 第 44 行 `transform_messages_into_research_topic_prompt` | 转为研究简报 | 子问题、日期、地域、指定来源、交付格式 |
| 第 79 行 `lead_researcher_prompt` | 调度研究与控制资源 | 独立子任务、并发上限、工具调用与 Token 预算 |
| 第 138 行 `research_system_prompt` | 搜索与研究职责 | 查询改写、优先来源、正文读取、停止条件 |
| 第 186 行 `compress_research_system_prompt` | 压缩研究材料 | 保留原始证据 ID、事实、不确定性与矛盾，不能只留摘要结论 |
| 第 228 行 `final_report_generation_prompt` | 最终报告 | 区分事实、推断、建议，结论绑定证据 |
| 第 311 行 `summarize_webpage_prompt` | 网页整理 | 保留日期、出处、支持结论的原文片段 |

GitHub 上该参考仓库目前已归档，适合作为架构与提示词样本，不应把它当作持续维护中的新依赖。[仓库状态](https://github.com/langchain-ai/open_deep_research)

### 建议的新流程

```text
必要时澄清 -> 研究简报 -> 拆分独立子任务
-> 选择工具、搜索 -> 读取正文或结构化 API
-> 建立证据记录 -> 检查覆盖率与冲突
-> 在预算内补搜 -> 压缩但保留出处
-> 撰写报告 -> 逐条检查事实与引用 -> 导出
```

这一流程按任务裁剪：天气查询不需要先跑一整套多智能体；复杂技术对比才值得并行研究。多智能体不是数量越多越好。

### 不同提示词的分工

建议组织为角色提示词、领域提示词和共享规则，而不是每个角色重复整段长提示词：

```text
prompts/
  common.py       证据、安全、事实与推断的边界
  planner.py      研究简报、任务拆分、预算
  researcher.py   查询策略、读取、停止与缺口
  compressor.py   保留证据来源的压缩
  writer.py       报告层级、结论、限制
  verifier.py     事实支持检查、矛盾和引用
  domains.py      科技、代码、天气、旅游专属约束
```

文件拆分是后续建议，当前未创建上述目录。

研究节点提示词示例，下面是重新编写的方案，不是复制上一个项目：

```text
任务：回答 {subquestion}，限定时间 {date_range} 与地域 {region}。
工具：只能使用本次实际提供的工具，不得宣称调用未绑定工具。
来源：技术事实优先官方文档、官方仓库与原始论文；遵守指定域名。
步骤：先搜索，再读取最相关页面；不得把搜索摘要当成已读完整正文。
效率：去重 URL 与证据，只为尚未覆盖的子问题补搜；遵守外部执行预算。
输出：事实、支持片段、证据 ID、日期、未解决问题、来源冲突。
失败：明确区分无结果与服务失败；不足时停止，不虚构事实或来源。
```

调用预算必须由程序计数限制，不能只在提示词中写“最多调用 5 次”。不要求模型展示隐含推理过程，前端展示可验证的操作记录即可。

### 真实性需要证据结构，而不只是措辞

推荐每条证据记录以下字段：`source_id`、`source_type`、`url/document_id`、`title`、`published_at`、`retrieved_at`、`supporting_excerpt`、`supported_claims`。

代码补充提交 SHA、文件与行号；天气补充地点、预报日期、单位与时区；表格计算补充数据集版本与计算参数。没有发布时间时使用空值，不能用抓取日期冒充发布日。

“引用编号存在”只说明引用格式正确，不能说明那段资料真的支持结论。应检查结论与片段的支持关系；涉及精确数字或实时信息时更严格。自动校验也会出错，不能显示为绝对保证。

建议先建设 30 条人工可核对的样例，覆盖正文来源、日期混淆、无结果、超时、错误引用、代码版本与数据计算。记录来源支持率、调用次数、耗时和成本。可引入 [Ragas](https://github.com/vibrantlabsai/ragas) 的忠实性、上下文精度与工具调用指标，但模型打分不是事实真假的最终裁决。[指标说明](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)

## 5. 前端美化方向

前端保持 Vue，不为美化而改成 React。使用已安装的 taste 与 impeccable 原则时，应该重新设计工作台，不继续停留在绿色按钮、白底和灰色分隔线的微调。

### 三个候选方向

| 方向 | 配色与视觉特征 | 适合的体验 |
| --- | --- | --- |
| A：彩色研究工作台，推荐 | 白色主体；蓝色 `#2D63ED` 为操作主色；绿色 `#0F8B72` 为知识库；黄色 `#F1B741` 为天气与出行；珊瑚色 `#E87571` 为报告模块 | 有鲜明色块，但颜色对应功能；有辨识度的实用工具 |
| B：柔和圆润工作台 | 浅灰底，天蓝、薄荷绿、小面积珊瑚红；柔和中文字体与更宽松阅读间距 | 更亲和，适合长报告阅读，不做幼稚卡通 |
| C：深浅对比专业工作台 | 石墨色导航、白色文档区、蓝绿操作色和少量琥珀状态标记 | 研究与编辑重度使用；避免整个页面变成深蓝色 |

推荐 A 的功能配色加 B 的字体气质。色块放在场景入口、工具类别、任务状态与图表中，不给每一段正文铺彩色背景。颜色不能是唯一状态线索，仍需要文字与图标。

### 字体必须包含中文

- [资源圆体 Resource Han Rounded](https://github.com/CyanoHao/Resource-Han-Rounded)：真正圆润的中文字体，源自思源黑体，字体采用 SIL OFL。应优先使用预构建资源，确认版本、Web 格式与浏览器兼容性，不能为了字体在本机进行大规模构建。
- [MiSans 官方资源](https://hyperos.mi.com/font/zh/download/)：清晰、柔和的中文 UI 候选，有 Web 字体资源，但不是简单套用 OFL 的自由改造字体；必须遵守其授权条件，不能随意修改或拆分再分发。
- 仅替换英文字体不够：我们的主界面是中文，汉字会继续落到原系统字体。正文优先可读性，代码单独使用等宽字体。

建议正文默认 18px、可缩放，标题不必巨大；按钮与状态栏另设较紧凑的字号。圆角和圆润字体是两个不同概念。

### Vue 组件参考与选择

- 推荐候选：[PrimeVue](https://github.com/primefaces/primevue) 与官方 [Sakai 模板](https://github.com/primefaces/sakai-vue)，适合文件上传、数据表格、弹窗与设置页。主题通过设计变量统一颜色和组件，不必照搬整个后台模板。[主题说明](https://primevue.dev/theming/styled/)
- 较轻替代：[Reka UI](https://github.com/unovue/reka-ui)，补齐菜单、弹窗与焦点交互，保留本项目 CSS 自定义外观。
- 更大样式调整的候选：[shadcn-vue](https://github.com/unovue/shadcn-vue)，适合愿意引入其样式体系时；不能误用 React 组件源码。

只选一个主组件体系，避免混用三套按钮、弹窗和字体尺度。组件库负责稳定控件，不会自动产生有辨识度的设计。

### 页面结构需要一起调整

1. 导航区：对话、研究任务、知识库、报告；仍保留清晰的新会话入口。
2. 首屏：可直接输入问题，科技研究、代码解读、出行规划、数据报告作为可操作的任务入口；不新增营销首页。
3. 主工作区：回答、研究资料和报告预览分视图；长报告限制行宽，表格可横向滚动。
4. 右侧研究栏：来源、工具调用、错误与未解决事项。显示真实运行状态，不放虚构统计数字。
5. 场景结果：有工具数据后再显示天气、地图或图表，避免拿静态装饰图冒充查询结果。
6. 手机：研究栏改为抽屉；设置、模型选择与字体调整有稳定位置；保证正文、按钮与表格不重叠。

## 6. 建议实施顺序

1. 补通用核心：安全网页正文读取、统一证据结构、保留来源的压缩与事实支持检查。
2. 做科技与代码包：GitHub 只读、版本文档、论文元数据，并完成一个可导出的技术调研任务。
3. 做出行包：高德地点/路线，按需要补和风天气；所有实时信息标明查询日期与边界。
4. 前端以彩色研究工作台为方向重设计，串联真实工具状态、报告预览和导出。
5. 数据分析与复杂 PDF 按真实用户需求增加，避免提前安装大体积依赖。

工具质量、网络限制、账户价格与权限最终以官方接口实际返回为准。本文没有承诺所有候选都能直接在当前网络环境中使用，也没有将调研候选记为项目已实现的技能。
