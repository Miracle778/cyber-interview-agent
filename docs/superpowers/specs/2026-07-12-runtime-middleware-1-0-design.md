# Runtime Middleware 1.0 设计

> **已被取代：** 本设计记录当时已实现的 Middleware 1.0 决策，但其中“自研
> RuntimeMiddleware pipeline 作为稳定产品边界”的方案已由
> `2026-07-13-agent-runtime-framework-convergence-design.md` 取代。后续不再扩展该
> pipeline，改用 `create_agent`、官方 `AgentMiddleware` 和 LangGraph 原生运行能力。

## 1. 目标

在 R2 多题复习前建立可由真实 Agent 消费的横切能力层，避免 token/context、压缩、标题、循环保护和普通工具审批散落到每个 Graph。

Middleware 1.0 使用已经完成的 `review.single` 作为第一个真实接入 Agent，交付：

- 可组合、可排序、可开关的 Runtime middleware pipeline；
- 模型调用 token/context、耗时和用量记录；
- context budget 与可恢复的会话压缩摘要；
- 首轮有效对话后的会话标题总结；
- 无限循环、重复调用和无进展保护；
- 普通工具审批到现有持久化 HITL 的 adapter；
- OpenTelemetry 抽象与本机 Langfuse v3 调试后端；
- `TodoCandidate` 类型与事件契约，不实现提取或正式 Todo Service。

## 2. 官方 Middleware 与当前 Runtime 的边界

LangChain `AgentMiddleware` 的 hook（`before_agent`、`before_model`、`wrap_model_call`、`wrap_tool_call`、`after_agent`）由 `create_agent(..., middleware=[...])` 组合。当前仓库的业务 Agent 使用手写 `StateGraph`，通过 `GraphBuildContext.invoke_model` 和 `invoke_tool` 调用项目网关，不经过 `create_agent`，因此不能假设把 `AgentMiddleware` 实例传给现有 Graph 就会生效。

Middleware 1.0 采用双层兼容设计：

1. **RuntimeMiddleware pipeline** 是跨所有 `StateGraph` 的稳定产品边界，由 `RunManager` 组装并包装 `GraphBuildContext`；
2. **LangChain AgentMiddleware adapter** 为后续使用 `create_agent` 的 Agent 提供官方 hook 接入，并复用同一 policy、telemetry 和 HITL service，不建立第二套规则。

这不是复制两套 middleware。业务策略、持久化 repository、错误码和事件只实现一次；两种 adapter 只负责把不同执行框架的 hook 转换为统一调用上下文。

官方参考：

- `AgentMiddleware` hooks：https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware
- `create_agent` middleware 参数：https://reference.langchain.com/python/langchain/agents/factory/create_agent
- LangGraph interrupt/resume：https://docs.langchain.com/oss/python/langgraph/interrupts

## 3. 三层 Pipeline

执行顺序固定为：

```text
Guard
  -> Invocation
    -> Graph / Model / Tool
  <- Invocation result
<- Post-processing
```

### 3.1 Guard

Guard 在 run、模型调用和工具调用前执行：

- 检查最大 run 时间、模型调用次数、工具调用次数和 token budget；
- 记录规范化节点/工具调用指纹和连续错误；
- 检测重复路径、重复调用、无产品状态进展和硬预算越界；
- 普通工具命中审批策略时创建持久化 action 并触发 interrupt；
- 软阈值只允许一次受控纠偏，硬阈值终止 run。

### 3.2 Invocation

Invocation 包装模型与工具调用：

- 记录模型角色、Provider/model 的非敏感标识、input/output/total token、context estimate、耗时和结果状态；
- Provider 返回原生 usage metadata 时以原生值为准；未返回时保存 `estimated=true` 的确定性估算；
- 流式调用累计最终 usage，不能把每个 chunk 重复计费；
- 统一发布 telemetry 事件，API key、原始敏感 prompt 和 Provider 异常正文不得进入事件或日志。

### 3.3 Post-processing

Post-processing 在成功生成持久化 assistant message 后执行：

- 判断 context budget 是否需要生成或更新压缩摘要；
- 首轮有效用户/assistant 消息后生成一次会话标题；
- 产生 `TodoCandidate` 的空契约事件能力，但 1.0 不调用模型提取；
- 标题或摘要失败不得把已成功的业务 run 改为 failed，改为记录稳定 warning event。

## 4. 核心接口

新增 `backend/app/runtime/middleware/`，按职责拆分：

- `types.py`：`MiddlewareContext`、`ModelInvocation`、`ModelUsage`、`ToolInvocation`、`TodoCandidate`；
- `pipeline.py`：pipeline 注册、排序、开关和 hook 调用；
- `telemetry.py`：用量与耗时记录；
- `context_budget.py`：预算判断和压缩策略；
- `session_title.py`：标题触发与写入策略；
- `loop_guard.py`：指纹、软/硬阈值和终止错误；
- `hitl_adapter.py`：普通工具审批策略到 `request_action`/`interrupt` 的适配；
- `langchain_adapter.py`：未来 `create_agent` 使用的 `AgentMiddleware` adapter。
- `observability.py`：`TraceContext`、`ObservabilitySink`、No-op 与 OpenTelemetry 实现。

稳定协议：

```python
@dataclass(frozen=True, slots=True)
class MiddlewareContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int

@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_tokens: int
    latency_ms: int
    estimated: bool

@dataclass(frozen=True, slots=True)
class TodoCandidate:
    source_message_ids: tuple[str, ...]
    suggested_title: str
    due_at: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    confidence: float
```

每个 middleware 还必须声明稳定的 `middleware_id`、所属 `layer` 和层内
`order`。Pipeline 同时支持整层开关和按 ID 单项关闭，并在启动时拒绝重复
ID、同层重复顺序或跨越层顺序区间。默认透传基类让新增 middleware 只覆盖
自己需要的 hook，无需实现空的 model/tool/message 方法。

Pipeline hook 不直接接收数据库 connection、API key 或 Workspace path；需要持久化时调用注入的窄 repository/service。

### 4.1 OpenTelemetry 与本机 Langfuse

业务代码只依赖项目协议 `ObservabilitySink`，不直接导入 Langfuse SDK。默认使用 `NoopObservabilitySink`；开发环境显式配置 OTLP/HTTP 后，使用 OpenTelemetry SDK 的批处理 exporter 把 spans 发送到本机 Langfuse v3：

```text
Cyber Interview Agent
  -> OpenTelemetry spans
  -> OTLP/HTTP
  -> http://127.0.0.1:3000/api/public/otel
  -> Langfuse UI http://127.0.0.1:3000
```

仓库维护 `infra/observability/langfuse/compose.yaml`、`.env.example` 和 `README.md`。Compose 固定经过验证的 v3 镜像版本，包含 Langfuse Web/Worker、PostgreSQL、ClickHouse、Redis/Valkey 和 MinIO，服务只绑定本机地址，数据使用 named volumes。普通 `down` 不删除 volumes；清理必须使用单独、显式标注会删除数据的命令。

Trace 结构：

```text
agent.run
├── graph.execute
├── model.invoke / model.stream
├── middleware.context_compression
├── middleware.session_title
├── middleware.loop_guard
├── tool.invoke
├── hitl.interrupt / hitl.resume
└── knowledge.publish
```

每个 span 允许记录 Workspace/session/run/graph 的安全 ID、Provider/model 非敏感 ID、token/context、耗时、工具名、scope、action ID、publication state 和稳定错误码。默认禁止记录 API key、完整 Prompt/回复、简历、JD、Vault 内容、工具参数正文和 Provider 原始异常。内容采样只能通过本地开发配置按 Workspace 显式开启，并在 export 前脱敏。

Langfuse/OTLP 不可用、队列满或 flush 超时时采用 fail-open：本地 Runtime SQLite usage、事件和业务 run 继续工作，只发布本地 warning。Exporter 使用有限队列和批处理；关闭应用时只允许短时间 flush。

进程重启后不伪造跨进程未结束 span。恢复创建新的 trace segment，复用相同 `session.id`/`run.id` 属性，并通过持久化的最后 span context 建立 OpenTelemetry Link。Langfuse 中按 session/run ID 聚合完整链路。

## 5. 持久化模型

新增 Runtime migration：

### 5.1 `model_invocation_usage`

- `id`, `workspace_id`, `session_id`, `run_id`；
- `role`, `provider_id`, `provider_model_id`；
- `input_tokens`, `output_tokens`, `total_tokens`, `context_tokens`；
- `latency_ms`, `estimated`, `status`, `error_code`, `created_at`；
- 唯一 operation key，防止 interrupt/resume 或 delivery retry 重复计数。

### 5.2 `runtime_guard_observations`

- `run_id`, `sequence`, `kind`, `fingerprint`, `state_hash`, `error_code`, `created_at`；
- 只保存规范化 hash 和稳定元数据，不保存工具密钥或完整 prompt；
- run 结束后可保留用于诊断，后续由 R7 决定清理策略。

### 5.3 `runtime_trace_segments`

- `run_id`, `segment_sequence`, `trace_id`, `span_id`, `created_at`, `finished_at`；
- 每次 start/resume 创建新 segment，记录非敏感 OTel context；
- 新 segment 使用上一 segment 的 span context 建立 Link，不跨进程伪造未结束 span；
- Langfuse 不可用时 segment 记录仍允许本地诊断，但不影响 run 状态。

现有 `agent_sessions.summary` 保存压缩摘要。`agent_sessions.title` 继续保存标题，不增加第二个标题字段。Repository 增加 expected-current-value 更新，避免用户已改标题后被后台总结覆盖。

## 6. Context Budget 与压缩

1. 每次模型调用前根据消息和已有摘要计算 `context_tokens`；
2. 低于软阈值时不处理；
3. 达到软阈值时，用报告总结角色模型把较早消息压缩为结构化摘要；
4. 保留 system 指令、当前任务状态、最近消息、未解决 action 和领域引用；
5. 新摘要写入 `agent_sessions.summary`，模型请求使用“摘要 + 保留消息”；
6. 达到硬阈值且压缩后仍超限时，以 `context_budget_exceeded` 终止本次模型调用。

默认阈值由配置提供，不能写死在 Graph。压缩调用本身计入 usage，但最多执行一次；摘要失败时本次调用继续使用未压缩上下文，只有硬阈值才阻断。

## 7. 会话标题

- 只在默认/占位标题且存在一组有效 user + assistant 消息时触发；
- 使用 `agent_chat` 或显式配置的 title role，输出短标题；
- 标题清理换行、引号和敏感信息，限制长度；
- 使用 compare-and-set 写入，用户或业务已设置标题时不覆盖；
- 标题失败发布 `middleware.warning`，不改变 run 成功状态；
- 同一 session 成功生成后不重复调用模型。

## 8. 无限循环与无进展检测

Guard 使用组合信号：

- 相同节点/工具调用指纹连续出现；
- 相同稳定错误连续出现；
- 多个步骤后 `state_hash` 不变；
- 模型/工具调用次数、运行时间、token 或费用超过预算。

软阈值产生 `runtime.guard.warning`，向 Agent 注入一次纠偏提示；相同问题再次出现或任何硬预算越界时抛出 `RuntimeGuardError`。RunManager 将其映射为 `run.failed`，只暴露稳定代码：`loop_detected`、`no_progress`、`step_budget_exceeded`、`token_budget_exceeded` 或 `run_timeout`。

恢复同一 run 时 guard 计数必须从 repository 恢复，不能通过重启绕过预算。

## 9. HITL Adapter

- 仅处理普通工具调用审批；策略按 graph/tool/scope 声明；
- adapter 复用现有 `request_action`、action version、resolution key、receipt 和 `Command(resume=...)`；
- `knowledge.publish`、草稿版本、Vault 和索引副作用继续由显式 Graph 节点与 handler 处理；
- adapter 不捕获 LangGraph interrupt 异常，不在 interrupt 前执行不可幂等副作用；
- 未来 `create_agent` Graph 使用官方 `HumanInTheLoopMiddleware` 或自定义 `AgentMiddleware` hook 时，仍通过现有 HitlService 持久化产品 action。

## 10. API 与前端

Session detail 增加：

- `summary`；
- `usage`：当前 session 累计 input/output/total/context、调用次数和 estimated 次数；
- `latestGuardWarning`；
- 标题继续使用现有 `title`。

Review 页面状态区展示紧凑用量和压缩状态，不新增独立设置页面。循环终止使用现有 actionable error 体系。TodoCandidate 在 1.0 只存在后端 schema/event，不新增 UI。

## 11. 测试与验收

### 11.1 单元与 repository

- pipeline 顺序、开关、异常传播和单一职责；
- No-op/OTLP sink、span 层级、脱敏、队列故障和短 flush；
- Provider 原生 usage 与 estimated fallback；
- 流式 usage 只计一次；
- usage operation key 幂等；
- 标题 compare-and-set；
- 摘要保留最近消息和领域引用；
- loop/no-progress/预算软硬阈值及重启恢复；
- HITL adapter 不改变 `knowledge.publish` 路径。

### 11.2 `review.single` 真实 Agent 集成

- 评价和报告两类模型调用都有 usage；
- 首轮完成后生成标题；
- 构造长上下文后生成摘要，刷新和重启仍可恢复；
- 关闭 middleware 后原业务输出和发布闭环不变；
- 普通工具审批通过 adapter，知识发布仍通过显式 action；
- 人为制造重复调用时 run 以稳定错误终止。
- 本机 Langfuse 可看到模型、middleware、HITL 和发布 spans；关闭 Langfuse 后业务仍完成。

### 11.3 最终验收

- 最终后端全量回归最多两次，前端全量/build 最多两次；
- 一次浏览器验收覆盖用量、标题、压缩提示、循环错误、刷新和后端重启；
- 一次本机可观测验收覆盖 Langfuse 健康检查、两个真实模型 spans、内容默认关闭、HITL/restart 关联和 exporter fail-open；
- 不要求 Todo 提取或 Todo UI；
- verification 不得把估算 token 描述为 Provider 原生 usage。

## 12. 非目标与阶段边界

- 不实现正式 Todo Service、待办提取模型或 Todo UI；
- 不实现 R2 多题复习行为；
- 不重写 `review.single` 领域 Graph；
- 不把知识发布迁入 middleware；
- 不引入 LangSmith、远程 telemetry SaaS 或生产级 Langfuse 高可用部署；本阶段只支持本机 Docker Compose；
- 不实现费用换算表，1.0 只保存 token 和可选 Provider 原始费用字段；
- 不顺带实现全部候选 middleware。

Middleware 1.0 完成后，R2 可以直接消费标题、usage、压缩和循环保护，但仍需在多题场景验证和调整阈值。
