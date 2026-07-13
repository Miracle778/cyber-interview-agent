# Agent Runtime 框架收敛设计

## 1. 背景与决策

R1 已经验证真实 Provider、LangGraph checkpoint、SSE、工具安全、持久化
HITL、知识草稿和发布闭环，但 Runtime Middleware 1.0 在 LangGraph 外又建立了
一套模型/工具调用协议、middleware pipeline、运行管理和事件发布机制。当前执行链
因此同时受项目 Runtime 与 LangChain/LangGraph 两套抽象控制，新增 Agent 时需要
重复接入模型、工具、middleware、usage、HITL、stream 和 observability。

本阶段在 R2 前完成一次不兼容的框架收敛：

- LangChain `create_agent` 与官方 `AgentMiddleware` 成为 Agent 调用循环的唯一扩展点；
- LangGraph `StateGraph` 继续表达用户必须理解的领域状态机；
- Agent 可以作为节点或子图嵌入领域 Graph，不再把手写 `StateGraph` 视为自建
  middleware pipeline 的理由；
- 项目只保留领域状态、产品投影、安全策略和框架缺失的窄扩展；
- 旧测试数据、API、checkpoint、内部 Python 协议和数据库 schema 不保持兼容；
- 当前代码通过归档 tag 保留，不维护新旧 Runtime 双栈。

归档基线为 `archive/pre-agent-runtime-refactor-2026-07-13`，指向
`main@8e1b500`。

官方依据：

- `create_agent`：https://reference.langchain.com/python/langchain/agents/factory/create_agent
- Middleware：https://docs.langchain.com/oss/python/langchain/middleware/overview
- 内置 Middleware：https://docs.langchain.com/oss/python/langchain/middleware/built-in
- LangGraph Persistence：https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph Streaming：https://docs.langchain.com/oss/python/langgraph/streaming
- LangGraph Interrupts：https://docs.langchain.com/oss/python/langgraph/interrupts

## 2. 目标与成功标准

### 2.1 目标

1. 删除项目与 LangChain/LangGraph 重叠的通用 Runtime 能力；
2. 让所有真实 Agent 通过同一套模型、工具、middleware 和 stream 协议运行；
3. 让领域 Graph 只描述复习、审核、发布等显式业务状态转换；
4. 缩小运行服务，使其只承担应用生命周期和产品投影；
5. 建立可直接承载 R2 多题复习 Agent 的清晰扩展边界。

### 2.2 成功标准

- 生产代码只存在一套 middleware 调度协议，即官方 `AgentMiddleware`；
- Agent 工具使用 `BaseTool`/`StructuredTool`，不再经过项目 `ToolRegistry`；
- Provider resolver 返回标准 `BaseChatModel`，不再维护通用调用 envelope；
- `review.single` 的模型/工具能力由 `create_agent` Agent 节点或子图承载；
- LangGraph checkpoint、interrupt/resume 和 stream 是执行状态的唯一事实；
- 产品数据库只保存产品资源与投影，不镜像完整 Graph 执行内部状态；
- 知识发布、草稿版本、Vault、索引和 receipt 仍是显式领域状态机；
- 真实 Provider、HITL、发布、刷新、重启、移动端和 Langfuse 验收不回退；
- 旧 Runtime、pipeline、gateway、registry 和遗留 Graph 被实际删除，而不是被
  新 adapter 包裹后继续保留。

## 3. 不兼容边界

本阶段是开发期架构重建，仓库没有需要保留的真实用户数据。实施时允许：

- 删除本机 Runtime SQLite 数据库并从新 schema 初始化；
- squash 或重写尚未对外发布的 Runtime migrations；
- 使旧 checkpoint、run、pending action、usage 和 trace segment 失效；
- 调整后端 API 路径、请求/响应 schema 和 SSE 事件；
- 同步修改前端调用和自动化测试；
- 删除旧 Python 类、协议、模块与针对内部实现的测试。

不兼容不等于降低产品标准。以下用户能力必须由新验收重新证明：

- Provider 配置和真实模型调用；
- 单题复习评价、报告与流式反馈；
- 普通工具审批和知识发布审批；
- 拒绝、批准、重复决定、刷新和后端重启；
- Workspace 路径隔离、工具审计、草稿版本与发布幂等；
- token/context、标题、压缩、循环保护和可观测性。

归档 tag 是旧实现唯一恢复入口；新分支不提供运行时兼容桥。

## 4. 目标架构

```text
FastAPI routes
  -> Application services
    -> Domain StateGraph
      -> create_agent node/subgraph
        -> BaseChatModel
        -> BaseTool / StructuredTool
        -> AgentMiddleware
      -> explicit domain nodes
        -> draft / action / publication / Vault / index
    -> LangGraph checkpointer + stream
    -> Product projections
      -> session / message / action / publication / audit
```

### 4.1 领域 Graph 与 Agent

`StateGraph` 只保留必须显式表达的业务拓扑，例如：

- 选择或校验复习输入；
- 调用评价 Agent；
- 调用报告 Agent；
- 创建草稿；
- 请求知识发布确认；
- 根据决定进入发布、拒绝或修订分支。

模型推理、工具循环、结构化输出和普通工具审批由 `create_agent` 生成的 Agent
负责。领域 Graph 通过稳定输入/输出 schema 调用 Agent，不直接拼装 Provider
参数、middleware invocation 或工具注册表。

### 4.2 Agent Factory

新增唯一的 Agent 构建入口，按角色构建 Agent：

```python
class AgentFactory:
    def create(
        self,
        *,
        role: str,
        tools: Sequence[BaseTool],
        middleware: Sequence[AgentMiddleware],
        response_format: type[BaseModel] | None = None,
    ) -> CompiledStateGraph: ...
```

Factory 负责取得模型、组合标准 middleware、绑定工具和 response format。
领域 Graph 不持有 API key，不感知 Provider adapter。

### 4.3 Provider 与模型

Provider 层收敛为 `ModelResolver`：

- 从用途绑定和 Provider 配置中解析 role；
- 临时取得 secret；
- 返回配置完成的 `ChatOpenAI`、`ChatAnthropic` 或其他 `BaseChatModel`；
- 统一安全的连接错误映射；
- 不重新包装 `ainvoke`、`astream`、structured output 或 usage metadata。

结构化输出使用 `create_agent(response_format=...)` 或模型原生
`with_structured_output()`。流式输出使用 Agent/LangGraph stream，不建立
`ProviderStreamChunk`。

### 4.4 工具

所有 Agent 工具使用 LangChain 标准工具类型：

- Pydantic args schema 定义输入；
- `ToolRuntime` 提供 workspace/session/run context；
- 返回 JSON-safe 领域结果；
- Workspace path policy 在工具 handler 内执行最后一道边界检查；
- allowlist、scope、审批、审计、脱敏和限流通过 `wrap_tool_call` middleware 统一执行。

文件访问、Vault 写入和索引操作仍由项目实现；只删除重复的注册、schema 调用和
通用执行协议。

### 4.5 Middleware

不再维护 Guard → Invocation → Post-processing 三层自定义调度器。顺序由传给
`create_agent` 的官方 middleware 列表和官方 hook 语义确定。

优先采用官方实现：

- `SummarizationMiddleware`；
- `ContextEditingMiddleware`；
- `ModelCallLimitMiddleware`；
- `ToolCallLimitMiddleware`；
- `HumanInTheLoopMiddleware`；
- 后续需要时采用 `ModelFallbackMiddleware`、PII 与 Todo middleware。

保留的项目 middleware 必须直接实现 `AgentMiddleware`，并仅处理官方缺失的
产品策略：

- Workspace scope 与工具审计；
- 产品 usage/session projection；
- 标题 compare-and-set；
- 语义级重复调用和无产品状态进展检测；
- OpenTelemetry 安全属性与本地 Langfuse fail-open；
- HITL interrupt 到产品 action/receipt 的投影。

项目 middleware 不得持有领域 repository 全集，不得隐藏知识发布、草稿状态、
Vault 或索引副作用。

### 4.6 HITL

普通工具审批使用官方 `HumanInTheLoopMiddleware` 的 interrupt/decision 协议。
应用层监听 interrupt 输出并投影为用户可查询的 pending action；用户决定后用
`Command(resume=...)` 恢复同一 LangGraph thread。

知识发布继续使用显式领域节点，因为它包含 draft version/content hash、receipt、
Vault 写入、publication journal、索引和补偿语义。它可以使用相同 interrupt
机制，但不能被隐藏为通用工具 middleware。

### 4.7 运行服务与状态所有权

旧 `AgentRuntime`/`RunManager` 收敛为小型应用服务：

- `AgentSessionService`：产品会话和消息入口；
- `AgentExecutionService`：调用、取消和恢复 Graph；
- `AgentEventProjector`：把 LangGraph stream 映射为浏览器事件；
- `ApprovalService`：action projection 与 resume decision；
- 领域服务：draft、publication、Vault、index、audit。

状态所有权固定为：

| 状态 | 唯一事实 |
|---|---|
| Graph 节点、interrupt、恢复位置 | LangGraph checkpoint |
| 模型/工具消息 | LangGraph messages state |
| 用户会话列表与展示元数据 | 产品 session projection |
| 待用户决定的业务记录 | pending action projection |
| 草稿、版本、发布结果 | Knowledge domain repository |
| Vault 内容 | Workspace filesystem |
| 浏览器重连游标 | 产品 event projection |
| trace | OpenTelemetry/Langfuse，失败时不影响业务 |

产品 run 只作为用户可见执行投影，不再独立重演 LangGraph 内部状态机。

### 4.8 Streaming 与事件

执行服务使用 `astream` 的 `messages`、`updates`、`custom` 和必要的 task/checkpoint
模式获取框架事件。`AgentEventProjector` 只生成前端真正消费的稳定产品事件：

- execution started/completed/failed/interrupted；
- assistant text delta；
- approval required/resolved；
- artifact/draft/publication changed；
- recoverable warning。

模型和工具生命周期不再在多层 wrapper 中手工重复发布。浏览器断线续传仍使用
产品事件表和 cursor，因为这是 UI 传输需求，不是 Agent 执行协议。

### 4.9 Observability

保留 OpenTelemetry 与本机 Langfuse，但优先使用 LangChain callback/Agent
middleware/LangGraph stream 产生 span。业务代码只添加安全的领域 span：action、
publication、Vault 和 index。

继续执行 metadata-only、secret/正文禁止记录、有限 flush 和 exporter fail-open。
不再为追踪建立第二套模型/工具 invocation 对象。

## 5. 包结构与命名

目标目录按职责组织：

```text
backend/app/
  agents/             # Agent factories, prompts, response schemas
  graphs/             # Explicit domain StateGraphs
  middleware/         # Official AgentMiddleware implementations/configuration
  tools/              # BaseTool/StructuredTool and workspace handlers
  application/        # Session, execution, event projection, approval services
  domain/             # Knowledge, HITL, publication state and policies
  infrastructure/     # SQLite, providers, checkpoints, telemetry
  api/                # FastAPI transport only
```

命名规则：

- `session_id` 仅指产品会话；
- `thread_id` 仅指 LangGraph thread；
- `run_id` 仅指一次用户可见执行投影；
- `interrupt` 是框架暂停机制；
- `action` 是用户可见待决定实体；
- `receipt` 是决定或副作用结果；
- 避免无边界的 `Runtime`、`Manager`、`Context`、`Service` 名称。

迁移期间优先按垂直切片移动文件，不先进行全仓库机械目录重排。

## 6. 重构顺序

### 6.1 行为冻结与新骨架

- 保留重构前后端全量基线；
- 新增面向用户行为的 characterization tests；
- 建立 ModelResolver、AgentFactory、标准 middleware/tool context；
- 建立全新测试数据库 schema，不迁移旧本机执行数据。

### 6.2 `review.single` 纵向迁移

- 评价和报告迁入标准 Agent；
- 领域 Graph 只保留输入、草稿和发布节点；
- 使用 LangGraph stream 产生文本和状态事件；
- 完成真实 Provider 的结构化与流式验收。

### 6.3 工具、HITL 与安全迁移

- 工具转换为 `BaseTool`/`StructuredTool`；
- 普通工具审批切换到官方 HITL middleware；
- scope、路径安全、审计与脱敏切换到标准 tool hook；
- 知识发布路径保持显式并重新验证幂等和重启。

### 6.4 Context、用量、保护与观测迁移

- 使用官方 summary/context/call limit middleware；
- 将产品 usage、标题和语义 loop guard 改为窄 `AgentMiddleware`；
- tracing 改从标准 hooks、callbacks 和 stream 采集；
- Langfuse 关闭时业务继续完成。

### 6.5 Runtime 与事件收敛

- 用 application services 替换 `AgentRuntime`/`RunManager`；
- 明确 checkpoint 与产品 projection 的单向关系；
- 重写简化后的 API 与前端 query/event 消费；
- 完成刷新、取消、审批和后端重启验收。

### 6.6 删除与命名收尾

确认无生产引用后删除：

- `RuntimeMiddlewarePipeline`、自定义 middleware types/layers；
- `LangChainRuntimeMiddlewareAdapter`；
- `_BoundModelInvoker`、`ChatModelGateway` 与通用 Provider envelope；
- `ToolRegistry`、`BoundToolInvoker` 的通用调用职责；
- 旧 `AgentRuntime`/`RunManager`；
- legacy `review_graph.py`、`review_state.py`、`agents/tools.py`；
- 只验证旧内部结构的测试。

最后统一包名和领域术语，运行静态引用扫描，禁止保留“未来再迁移”的双栈。

## 7. 错误、安全与失败策略

- Provider 原始错误只在安全边界内映射为稳定错误码；
- middleware 不吞业务异常，不把 telemetry 故障升级为业务失败；
- interrupt 前的副作用必须幂等或延迟到 resume 后执行；
- 工具必须在 handler 内再次验证 Workspace path，middleware allowlist 不是唯一防线；
- 发布继续使用 draft version、content hash 和 operation key；
- summary、title、usage、trace 投影失败采用 fail-open 并产生可诊断 warning；
- schema/Graph 变化导致旧数据库不可用时明确提示重建，不自动静默解释旧数据。

## 8. 测试与验收

### 8.1 针对性 TDD 与旧测试处置

重构前的 281 项后端和 75 项前端测试只证明归档版本可运行，不是新架构的兼容
门禁。每个纵向任务先写失败的能力或安全不变量测试，再实现最小迁移。旧测试按
以下规则处理：

- `KEEP`：与内部结构无关、仍然成立的领域或安全行为；
- `REWRITE`：能力仍保留，但测试改为通过新 Agent/Graph/API 观察；
- `DELETE`：只约束旧 API、旧数据库、旧 checkpoint 或旧 Runtime 内部实现。

删除 `DELETE` 测试不要求等价替代；删除 `REWRITE` 测试前必须先有新的行为测试
接管。最终不以旧测试数量作为质量指标。

重点覆盖：

- AgentFactory 组合模型、工具、response format 和 middleware；
- 模型用途绑定与 secret 不进入 Graph state；
- 工具 scope/path/audit/HITL；
- interrupt/resume、重复 decision 和重启；
- summary/call limit/semantic loop guard；
- stream 到产品事件的唯一映射；
- publication version/hash/idempotency；
- telemetry fail-open。

### 8.2 集成与最终验收

- 跨层能力接通后至多一次后端/前端集成回归；
- 最终验收前一次全量后端、前端、typecheck 和 build；
- 一条最小浏览器 happy path 在最终文档前执行；
- 一次完整浏览器验收覆盖桌面、375px、刷新、批准、拒绝、重启和发布；
- 真实 OpenAI-compatible 与 Anthropic-compatible 调用；
- 本机 Langfuse 可见标准 Agent/Graph spans，关闭后业务仍成功；
- 最终文档门禁和架构删除清单必须通过。

基线证据：重构前后端 `281 passed`，前端 `75 passed`。

## 9. 非目标

- 不在本阶段实现 R2 多题复习、题库治理或全局掌握度；
- 不实现正式 Todo Service；
- 不重做知识库和设置页视觉设计；
- 不改变现有页面信息架构、布局和视觉体系；前端只重写 API、query、stream 和
  Agent 状态接入，必要的状态文案调整除外；
- 不迁移真实用户数据；
- 不维护旧 API 或 checkpoint 兼容层；
- 不把所有领域服务塞入 Agent tool；
- 不因为采用官方组件而移除 Workspace 安全、领域幂等和产品审计。

## 10. 阶段位置

本阶段命名为 **Pre-R2 Agent Runtime Framework Convergence**。它取代“直接在
Middleware 1.0 自研 pipeline 上进入 R2”的旧顺序。完成后才开始 R2，R2 只扩展
多题复习和掌握度业务，不再承担 Runtime 迁移。
