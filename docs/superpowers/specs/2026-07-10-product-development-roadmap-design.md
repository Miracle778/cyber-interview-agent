# Cyber Interview Agent 产品开发路线设计

## 1. 文档目的

本文档以 `docs/my_idea.md` 为原始产品意图，重新定义 Cyber Interview Agent 的开发主线、阶段边界和依赖关系。

项目不是单一的复习工具，也不是通用知识库管理器，而是一个由多个场景 Agent 共同组成的个人面试准备工作台：

- 配置与运行底座负责模型、工作区、沙箱和知识库。
- 复习 Agent 负责题库整理、练习、追问和掌握度更新。
- 个人信息 Agent 负责简历、个人材料和个人画像。
- 岗位追踪负责把 JD、个人画像、复习、复盘和模拟面试组织到同一个目标岗位下。
- 复盘 Agent 负责把真实面试转化为可审核的经验和知识资产。
- 模拟面试 Agent 负责岗位定向的技术面和 HR 面练习。
- 移动端 Channel 负责碎片化复习和快速记录。

本路线只记录需求顺序，不估算日期、工时或人天。

## 2. 路线修正原则

### 2.1 共享底座先行，业务闭环紧随

Provider、模型选择、LangGraph Runtime、会话恢复、HITL 和知识库发布协议属于所有 Agent 共用的底座，应在继续扩展页面前完成第一版。

底座只做到能够支撑下一条纵向闭环，不单独堆叠长期没有用户价值的基础设施。

### 2.2 按纵向产品闭环推进

每个阶段都要形成可人工验证的场景闭环，而不是只完成数据库、接口或页面骨架。

推荐顺序为：

```text
技术切片基线
  -> 共享 Agent 与知识库底座
  -> 完整复习 Agent
  -> 个人信息 Agent
  -> 岗位与 JD 追踪
  -> 面试复盘 Agent
  -> 模拟面试 Agent
  -> 知识库与本地产品化增强
  -> 移动端 Channel
```

### 2.3 知识库是共享能力，不是独立终点

知识库从共享底座阶段开始存在，并由每个业务阶段逐步扩充文档类型和关系：

- 复习阶段写入 source、question、review session、mastery。
- 个人信息阶段写入 resume、profile、project experience 等经过审核的内容。
- 岗位阶段写入 job target 和 JD 分析。
- 复盘阶段写入 interview retrospective 和项目经验。
- 模拟面试阶段写入 mock interview report。

所有业务产物默认先生成草稿，只有用户显式确认“推送到知识库”后才参与检索和后续 Agent 推理。

### 2.4 Dashboard 和学习建议嵌入场景

掌握度、薄弱点、岗位差距、下一步建议和待审核内容，优先作为对应 Agent 页面的状态区域和报告能力实现，不再单独挡在核心业务页面之前。

## 3. 默认技术架构

### 3.1 前端

- React + TypeScript + Vite。
- 负责设置、资料管理、会话交互、状态展示和 HITL 确认。
- API key 不写入浏览器持久化存储。

### 3.2 后端

- Python + FastAPI。
- 负责 Provider 调用、Agent 编排、文件沙箱、知识库读写、索引和持久化。
- 所有文件工具必须把可访问路径限制在用户配置的 workspace 内。

### 3.3 Agent Runtime

- LangGraph 作为 Agent 工作流和状态机框架。
- 每类 Agent 使用独立 graph、tool allowlist 和状态 schema。
- 使用 checkpoint 持久化会话状态，支持暂停、恢复和 HITL interrupt。
- 长会话保存结构化状态与压缩摘要，不依赖无限增长的完整上下文。
- 模拟面试由主 Agent 委派面试子 Agent，面试结束后只把结构化总结交回主 Agent。

### 3.4 Middleware 架构规则

Runtime 使用 LangChain 官方 `AgentMiddleware` 承载跨 Graph、跨 Agent、与具体业务节点无关的横切能力。Agent 通过 `create_agent` 构建，并可作为节点或子图嵌入显式业务 `StateGraph`；不得因为业务 Graph 是手写拓扑而建立平行的 middleware 调度器。满足以下多数条件的能力优先实现为 middleware：多个 Agent 使用相同触发时机和规则；关注模型、消息、工具或 run 生命周期而非领域状态转换；可通过官方 hook 或调用包装完成；可统一降级；具有稳定、可组合、可测试的窄契约。

概念上按以下三类能力组织，但执行协议、hook 与顺序以官方 `AgentMiddleware` 为唯一实现：

1. **Guard middleware**：权限和 scope、HITL 拦截、最大节点步数、工具调用数、运行时间、token/费用预算、无限循环和无进展检测；
2. **Invocation middleware**：模型/工具调用包装、token/费用/耗时统计、超时、限流、重试、fallback、schema 校验、tracing、错误归一化和脱敏；
3. **Post-processing middleware**：会话标题、阶段摘要、待办事项候选、主题标签、关键结论、长期记忆候选和下一步建议。

候选能力包括：

- **模型治理**：token/context/费用/耗时、context budget、压缩、限流、重试、fallback 和响应格式校验；
- **运行保护**：无限循环、最大步骤、重复工具调用、无状态进展、连续错误、超时、费用熔断和取消传播；
- **会话增强**：标题、摘要、待办候选、主题分类、关键结论、偏好和记忆候选；
- **工具治理**：参数 schema、scope、审批、频率限制、只读缓存、敏感参数清理和重复副作用拦截；
- **可观测性**：tracing、审计、质量评分、低置信度标记、模型/Prompt 版本和统一指标；
- **体验事件**：长任务进度、失败恢复建议、预算预警和统一状态说明。

无限循环检测综合重复节点路径、工具名与规范化参数、连续相同错误、token 增长、连续无产品状态变化、运行时间和费用预算。软阈值产生诊断事件并允许一次受控纠偏；硬阈值终止 run，保存稳定错误码和恢复说明。Middleware 不得自动重复启动新 run。

待办事项采用“候选提取 + 领域服务确认”：post-processing middleware 只输出带来源、置信度、建议标题、截止时间和关联对象的候选；Todo Service 负责去重、持久化、状态转换、撤销和用户确认。Middleware 不得静默创建不可撤销的正式待办。

HITL 采用分层方案：普通工具审批由官方 `HumanInTheLoopMiddleware` 产生 interrupt，应用层把 interrupt 投影为 pending action，并用 `Command(resume=...)` 恢复同一 thread；知识发布等包含 version/hash、receipt、Vault 和补偿语义的复杂审批继续使用显式 Graph 节点与领域 handler。不得再为 HITL 建立项目级 middleware adapter 协议。

以下能力不得仅由 middleware 隐藏实现：知识发布、草稿状态转换、Vault 写入、索引更新、用户必须理解的业务分支、长事务和补偿流程，以及依赖领域 version/hash/operation id 的副作用。它们必须保留在显式 Graph 或应用服务中。

每个 middleware 必须声明适用范围、执行顺序、持久化边界、失败/降级策略、幂等键、事件与指标，以及禁止承载的领域副作用。

Middleware 随 Agent 能力分阶段落地：

- **Pre-R2 Middleware 1.0（历史阶段，已被收敛）**：曾用自研 pipeline 验证 token/context、压缩、标题、循环保护、HITL 和 observability 行为；其行为证据保留，但实现协议不再作为后续模板。
- **Pre-R2 Agent Runtime Framework Convergence（已完成）**：已删除平行 RuntimeMiddleware pipeline，把 `review.single` 迁到 `create_agent` 子图、官方 middleware、标准工具、标准模型和 LangGraph stream；旧测试数据、API 和 checkpoint 不兼容。
- **R2 完整复习 Agent**：直接复用收敛后的 Agent Harness，验证长会话压缩、多题循环保护、标题和用量展示；根据真实运行校准重复工具调用、无进展检测和预算预警。
- **R3 个人信息 Agent**：定义用户偏好、长期记忆和待办候选的安全输入边界，完善敏感信息脱敏；仍不创建正式 Todo 状态机。
- **R4 岗位追踪**：实现正式 Todo Service，并启用待办候选提取、用户确认、去重、截止时间和岗位关联。
- **R5 面试复盘**：扩展行动项、关键结论和经验候选提取，并增加质量与置信度标记。
- **R6 模拟面试**：为主 Agent/子 Agent 委派链增加更严格的时间、费用、步骤预算、循环检测和 tracing。
- **R7-R8 产品化与 Channel**：根据真实使用数据增加缓存、跨 Agent 指标、移动端预算和降级策略。

这样安排保证 middleware 始终由真实 Agent 消费：Pre-R2 不建设脱离业务的完整平台，R2 也不需要在多题状态机中重复实现横切能力。

采用 middleware 的收益是一次实现供全部 Agent/Graph 复用、业务节点保持聚焦、安全成本质量规则统一、新 Agent 默认获得治理能力，并支持独立测试、替换、开关和观测。代价是执行顺序、共享状态、额外模型调用和失败传播更复杂，因此禁止形成持有全部 Runtime 状态的“大中间件”。

Agent 可观测性统一采用 OpenTelemetry 抽象，业务代码只依赖项目 `ObservabilitySink`；首个后端为本机自托管 Langfuse，通过 OTLP/HTTP 接收 spans。默认只记录安全 ID、模型/工具名、token、耗时、状态和稳定错误码，不记录 Prompt、回复、个人资料、Vault 正文或工具参数。可观测后端不可用时必须 fail-open，不影响 Agent、HITL 和知识发布。

#### 3.4.1 后续阶段 Agent Harness 设计模板

R2-R8 的独立 spec 必须逐项回答以下问题；某阶段不需要 Agent 时必须明确写“不适用”，不得为了套模板强行 Agent 化：

1. **领域目标与状态所有权**：用户可见流程是什么；哪些事实属于 LangGraph state/checkpoint、产品数据库、领域 repository、Vault、前端缓存和外部系统；
2. **Agent roles**：每个 role 的职责、模型用途绑定、system prompt 边界、结构化 `response_format`、输入输出和禁止访问的数据；
3. **领域 Graph**：哪些节点是确定性业务节点，哪些节点调用 `create_agent`；暂停、恢复、分支、取消和失败如何表达；
4. **工具与权限**：使用哪些标准 `BaseTool`/`StructuredTool`，`ToolRuntime` 注入哪些可信身份，allowlist、scope、路径和审计如何配置；
5. **Middleware 组合**：复用哪些官方 middleware，保留哪些直接继承 `AgentMiddleware` 的窄项目扩展，其顺序、幂等、硬/软失败和 fail-open 边界是什么；
6. **Thread 与 checkpoint**：产品 session、外层 Graph thread、role Agent thread、派生讨论或子 Agent thread 如何稳定映射和隔离；
7. **HITL 与领域副作用**：普通工具 interrupt 如何投影为 action；哪些 draft/version/hash/Vault/index/Todo 副作用必须保留在显式 Graph 或领域 service；
8. **产品投影与 API**：前端只消费哪些 session、execution、message、action、usage、artifact 和 product event，不暴露内部 checkpoint 或 Graph state；
9. **安全与可观测性**：secret、正文、个人信息和工具参数的信任边界；OTel/Langfuse 记录什么、禁止记录什么、不可用时如何降级；
10. **验收**：至少包含 targeted TDD、重启恢复、真实 Provider、浏览器闭环、响应式、失败路径和与阶段风险匹配的文档证据。

#### 3.4.2 后续阶段任务骨架

每个 Agent 产品阶段默认压缩为 3-4 个纵向任务，而不是按基础设施类型横向拆散：

1. **领域契约与状态**：输入输出、领域记录、状态所有权和确定性选择/合并逻辑；
2. **Agent 能力与 Graph 编排**：role Agent、标准工具、middleware 组合、thread/checkpoint 和 HITL；
3. **应用/API/前端闭环**：产品投影、session/execution/action/event 资源和用户交互；
4. **验收收尾**：真实 Provider、浏览器/重启、全量回归、verification 和 learning。

非 Agent 阶段可以删去第二项，但不得建立替代 Runtime。一个纵向任务由同一 Agent 负责到底；只有文件不重叠且状态独立时才并行。

#### 3.4.3 Agent Harness 禁止项

- 禁止新增项目级 Agent loop、RunManager、Graph registry、通用 Runtime 状态机或 middleware pipeline；
- 禁止新增模型调用 Gateway、invocation envelope 或重新包装 `ainvoke`/`astream` 的通用协议；
- 禁止新增 ToolRegistry、BoundToolInvoker 或与标准 `BaseTool` 平行的 schema/executor；
- 禁止用 adapter 把旧协议包起来冒充官方 `AgentMiddleware`；项目扩展必须直接实现官方 hook；
- 禁止在产品数据库镜像完整 Graph 节点、消息或 checkpoint 内部状态；只保存用户可见产品投影；
- 禁止把知识发布、草稿状态、Vault、索引、Todo、长事务或补偿副作用隐藏进通用 middleware；
- 禁止由模型、前端或 Channel 自报 workspace/session/scope 身份，可信 context 必须由服务端注入；
- 禁止 R8 等外部 Channel 绕过同一 application service、HITL、工具权限和发布规则。

### 3.5 数据与知识库

- Markdown + YAML frontmatter 是用户可读、可迁移的长期可信数据。
- Obsidian-compatible Vault 可以脱离本项目独立阅读、编辑、搜索和备份。
- SQLite 保存可重建索引、运行状态、会话元数据和 checkpoint。
- 第一版检索使用 metadata、关键词搜索和关系索引；语义检索按实际质量需求后加。
- Pydantic schema 约束 Provider 输出和 Agent 结构化产物。

### 3.6 Provider

- 支持保存多个 Provider，并在 Provider 下保存多个模型。
- 第一版同时定义 OpenAI-compatible 和 Anthropic-compatible 的 Provider 配置与连通性 adapter；Agent 模型调用由服务端解析为标准 `BaseChatModel`，不得引入模型 Gateway。
- 支持自定义 `base_url`，兼容火山、GLM 等提供兼容协议的服务。
- 支持连通性测试、Provider 切换和按用途选择模型。
- 模型用途至少包括题库生成、回答评估、报告总结和普通 Agent 对话。
- API key 只保存在后端受限配置中，不写入 Vault、前端缓存、日志或生成文档。

## 4. 跨阶段产品契约

### 4.1 会话契约

所有 Agent 页面统一具备：

- 左侧会话列表和 Agent 生成标题。
- 中间对话区。
- 右侧当前对象、上下文、token 用量、产物和待确认动作。
- 会话持久化、恢复和归档。
- 场景需要时支持会话派生。

### 4.2 HITL 契约

以下动作必须显式确认：

- 修改已保存的用户资料。
- 激活 Agent 生成的题目。
- 更新全局掌握度。
- 将个人资料、复盘或模拟面试产物推送到知识库。
- 覆盖用户在 Obsidian 中手工修改的内容。
- 解决冲突或归档长期数据。

### 4.3 知识库发布契约

业务页面只生成领域草稿，统一发布服务负责：

1. 展示即将写入的内容、来源和关系。
2. 允许用户接受、编辑、拒绝或要求重写。
3. 用户确认后写入 Markdown 和 frontmatter。
4. 更新 manifest、关键词索引和关系索引。
5. 记录来源、版本、checksum 和确认动作。

## 5. 开发阶段

## R0：技术切片与质量基线

定位：证明 React、FastAPI、Workspace、Vault 和单轮复习链路可以跑通。

当前已有：

- 前后端工程骨架。
- Workspace 与 Vault 初始化。
- 资料上传和粗糙题目草稿。
- 单题单轮回答、评估、报告确认。
- Vault rescan 和 SQLite FTS 技术切片。
- 后端健康状态、流程状态和基础错误建议。

成熟度结论：这是可验证技术切片，不代表完整复习 Agent 已完成。

## R1：共享 Agent 与知识库底座

目标：建立后续所有 Agent 共用且真实可用的运行能力。

需求：

- 多 Provider、多模型保存和切换。
- OpenAI-compatible 与 Anthropic-compatible 的 Provider 配置与连通性 adapter；Agent 执行只消费标准 `BaseChatModel`。
- 真实连通性测试和可理解的错误分类。
- 按用途选择模型。
- 后端安全读取 API key。
- LangGraph graph、state、tool 和 checkpoint 基线。
- 会话创建、列表、恢复、归档和标题生成。
- Workspace 文件沙箱和每类 Agent 的 tool allowlist。
- 上下文压缩摘要和 token/context 用量记录。
- HITL interrupt、待确认动作和恢复执行。
- 统一知识库草稿、审核、发布、重建索引协议。
- Fake Provider 和确定性 Agent 测试基线。

验收：

- 可以保存并切换至少两个 Provider、多个模型。
- 两种兼容协议都能进行真实连接测试。
- 一个 LangGraph 示例会话可以中断、重启后恢复、确认后继续。
- Agent 无法读写 workspace 外文件。
- 草稿未经确认不会进入 active knowledge scope。

## R2：完整复习 Agent

目标：实现原始 idea 中真正可持续使用的辅助复习页面。

需求：

- 导入一份或多份零散问题资料。
- Agent 补充、纠错、优化答案并生成分类题库草稿。
- 题目包含来源、答案、关键点、常见错误、难度、topic、追问和审核状态。
- 用户接受、编辑、拒绝或要求重写候选题。
- 选择复习 topic、难度、模式和题量，例如 10 题或 20 题。
- 支持薄弱点优先、随机混合、单主题和最近错误复现。
- 一次只问一道题，根据回答进行评估和必要追问。
- 会话列表、自动标题和从具体问题派生深入讨论会话。
- 一轮结束生成单会话掌握度报告。
- 多次生成同一会话报告时进行合并，冲突交给用户处理。
- 新会话参考当前全局报告和最近三份已确认单会话报告。
- 更新全局掌握度并给出下一轮建议。
- 状态区展示当前范围、进度、掌握度、上下文和产物。
- 复用收敛后的官方 Agent middleware stack 展示 token/context、标题和预算状态，并在多题循环中验证压缩、调用上限与无进展保护。

验收：

- 用户能完成一轮至少 10 题的可恢复复习。
- 追问和派生会话不会污染主复习轮次。
- 单会话报告和全局掌握度都有可追溯证据。
- 下一轮出题会实际参考已确认的掌握度报告。
- 长会话触发压缩后仍能恢复；重复步骤或无进展达到阈值时能安全停止并给出恢复建议。

## R3：个人信息 Agent

目标：建立可由用户控制的个人画像和材料空间。

需求：

- 简历上传、删除和版本管理。
- 结构化提取技能、项目、经历、教育和作品链接。
- 简历评估、润色建议和逐项确认。
- 管理 GitHub 贡献说明、技术博客、研究内容和项目文档。
- 个人信息 Agent 只能访问个人资料目录和允许的工具。
- 支持围绕简历和个人经历持续对话。
- 用户通过“推送到知识库”选择哪些个人资料参与后续检索。
- 为偏好、长期记忆和待办候选提供安全提取边界与脱敏规则，但不在本阶段创建正式待办。

验收：

- 用户能看到原始简历、结构化画像和修改建议之间的关系。
- Agent 不会未经确认改写简历或发布个人资料。
- 已确认个人画像可以供岗位分析、复盘和模拟面试引用。

## R4：岗位与 JD 追踪

目标：以岗位为一级索引组织定向面试准备。

需求：

- 创建岗位目标，保存公司、岗位、轮次、日期和状态。
- 上传或粘贴 JD，提取技能、职责和经验要求。
- 结合个人画像和知识库生成匹配度、竞争力、优势、风险和缺口分析。
- 岗位详情聚合相关资料、复习会话、复盘、模拟面试和产出文档。
- 根据岗位差距推荐复习范围，但允许用户调整。
- 岗位 Agent 具有独立会话和受限工具。
- 实现正式 Todo Service，把 middleware 产生的候选经用户确认后关联到岗位，支持去重、截止时间、完成和撤销。

验收：

- 用户能围绕一个岗位看到自己会什么、缺什么、下一步准备什么。
- 分析结论可以追溯到 JD、个人资料和知识库证据。
- 不再存在重复的“面试准备工作台”和“JD 追踪”两个阶段。

## R5：面试复盘 Agent

目标：把真实面试经历沉淀成可审核、可复用的经验资产。

需求：

- 在岗位下导入转写文本或手动记录。
- 清理说话人和语句结构；缺少面试官发言时倒推问题并标记推断。
- 分析回答表现、知识缺口和表达问题。
- 提炼个人项目经验并单独保存草稿。
- 支持围绕复盘结果继续与 Agent 对话。
- 用户审核后选择题目、经验或复盘总结推送到知识库。
- 通过 post-processing middleware 生成行动项、关键结论和经验候选，并展示来源与置信度。

验收：

- 一场面试记录可以形成结构化复盘。
- 推断问题和原始转写有明确区分。
- 知识缺口能进入后续复习，项目经验能进入个人资料候选区。

## R6：模拟面试 Agent

目标：围绕岗位、JD 和个人经历进行可恢复的技术面或 HR 面模拟。

需求：

- 载入岗位、JD、简历、题库、知识库和历史薄弱点。
- 选择技术面、HR 面和面试官风格。
- 选择固定题量，或由用户主动结束。
- 主 Agent 委派面试子 Agent，隔离模拟上下文。
- 支持暂停、恢复和继续。
- 结束后由主 Agent 汇总表现、风险和建议。
- 用户审核后选择总结内容推送到知识库。
- 主 Agent 与面试子 Agent 统一受时间、费用、步骤、循环检测和 tracing middleware 约束。

验收：

- 模拟面试不会无限循环，并能在中断后恢复。
- 问题与目标岗位和个人背景有关，而不是通用随机题。
- 模拟上下文不会污染岗位主会话。

## R7：知识库与本地产品化增强

目标：让系统适合长期本地使用，并确保 Vault 脱离应用仍可管理。

需求：

- 完整文档列表、筛选、搜索、详情和关系查看。
- 稳定各领域 Markdown 模板、frontmatter 和双向链接。
- Obsidian 手工修改检测、冲突提示和人工编辑优先策略。
- 重建 manifest、关键词索引和关系索引。
- Workspace 切换、备份建议、运行日志和诊断。
- API key 更安全的本地存储方案。
- 汇总掌握度、岗位进度、待审核内容和近期产出的首页状态。

验收：

- 只使用 Obsidian 也能读懂题库、个人资料、岗位、复习和复盘之间的关系。
- 删除派生索引后可以从 Vault 重建。
- 外部编辑不会被应用静默覆盖。

## R8：移动端 Channel

目标：通过微信、飞书等入口完成碎片化准备。

需求：

- 每日轻量复习和快速答题。
- 面试后快速记录并归入指定岗位。
- 查看薄弱点、岗位差距和下一步建议。
- 选择进入复习、复盘或模拟面试 Agent。
- 移动端产生的内容同步回同一套会话和知识库审核流程。

验收：

- 用户能在手机上完成短时复习或快速记录。
- Channel 不绕过 HITL、权限和知识库发布规则。

## 6. 原始 idea 映射

| 原始模块 | 新路线阶段 |
|---|---|
| 配置设置、Provider、Workspace、知识库初始化 | R1，R7 增强 |
| 辅助复习页面 | R2 |
| 个人信息页面 | R3 |
| JD、岗位索引和竞争力分析 | R4 |
| 实际面试复盘 | R5 |
| 模拟面试 | R6 |
| Obsidian 三层知识库与跨模块摄取 | R1 起持续建设，R7 完整增强 |
| Agent harness、独立工具、恢复、记忆、HITL | R1 基线，各阶段按场景扩展 |
| 微信、飞书等移动端入口 | R8 |

## 7. 执行规则

- 每个阶段先写独立 spec，经确认后再写 implementation plan。
- 每个任务使用测试驱动，并在完成后由 Codex 审阅和验收。
- 自动测试使用 Fake Provider；真实模型调用只用于明确的手动或可选集成验证。
- 任何 Agent 生成内容默认是草稿，未经用户确认不进入 active knowledge scope。
- 每个阶段都必须提供“改了什么、代码在哪里、如何人工验证、还有哪些粗糙边界”。
- 不用“完成”掩盖技术切片；状态区分为设计、骨架、技术切片、可人工验证、场景可用和产品可用。

## 8. 当前下一步

当前已完成 R1、Pre-R2 Middleware 行为验证和 Agent Runtime Framework Convergence。下一步是审阅 R2“完整复习 Agent”独立设计；设计确认后再按 3-4 个纵向任务编写 implementation plan，不重新建设 Agent Runtime 基础设施。
