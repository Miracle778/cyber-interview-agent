# R1 共享 Agent 与知识库底座设计

## 1. 文档目的

R1 为 Cyber Interview Agent 的复习、个人信息、岗位追踪、面试复盘和模拟面试 Agent 建立共享运行底座。

本阶段不追求一次完成所有业务 Agent，而是提供一套可以被后续纵向场景复用的基础能力：

- 多 Provider、多模型和 Workspace 模型用途绑定。
- OpenAI-compatible 与 Anthropic-compatible 真实调用。
- API Key 安全保存。
- LangGraph session、checkpoint、恢复和 SSE 事件流。
- Workspace 文件沙箱、Tool Registry 和默认拒绝权限。
- 持久化 HITL。
- 领域草稿、人工审核和知识库发布协议。
- 使用现有单题复习 Graph 完成端到端验收。

## 2. 范围

### 2.1 R1 包含

- 应用级 Provider 与 Workspace 注册配置。
- Provider CRUD、模型 CRUD、逐模型连接测试。
- 系统密钥链与环境变量 secret 来源。
- Workspace 模型用途绑定。
- 独立 Graph 注册机制。
- session、message、run、event、checkpoint 持久化。
- REST 命令和 SSE 事件协议。
- 进程重启后的 session、checkpoint 和 HITL 恢复。
- 工具白名单、目录授权、路径安全和审计。
- 持久化 pending action。
- 原始资料、领域草稿、Vault 知识三层数据模型。
- 幂等、可恢复的 PublicationService。
- 当前单题复习 Graph 迁移到共享 Runtime。

### 2.2 R1 不包含

- 完整 10/20 题复习轮次。
- 追问策略和会话派生体验。
- 全局掌握度合并策略。
- 个人信息、岗位、复盘或模拟面试业务 Graph。
- embedding 和向量数据库。
- 模型列表自动发现。
- 远程账号、多人权限或局域网开放访问。
- Celery、Redis 等外部任务队列。
- 完整 Obsidian 冲突合并 UI。
- 移动端 Channel。

这些能力分别属于 R2-R8，不应混入 R1。

## 3. 已确认决策

- Provider 全局保存，Workspace 只保存模型用途绑定。
- Provider 元数据位于应用级 SQLite，API Key 位于系统密钥链。
- 无系统密钥链时允许从环境变量读取 API Key，但不自动写入本地明文文件。
- session、checkpoint、HITL 和草稿元数据位于各 Workspace 的 runtime SQLite。
- 每类 Agent 使用独立 LangGraph，共享 Runtime、Provider、HITL 和知识发布服务。
- Agent 权限默认拒绝，每类 Agent 拥有独立 tool allowlist 和目录 scope。
- HITL action 必须持久化、可编辑、可拒绝、可幂等恢复。
- 原始资料和领域草稿位于 Workspace；只有用户确认后的知识文档进入 Vault。
- Agent 命令使用 REST，模型输出和运行进度使用 SSE。
- R1 使用当前单题复习 Graph 证明共享底座，不提前实现 R2 多题能力。
- 实施采用按能力纵向切片，每个切片都包含后端、前端、测试和人工验证。

## 4. 总体架构

```text
React Frontend
  |-- REST commands
  |-- SSE events
  v
FastAPI API
  |-- ProviderService
  |-- WorkspaceService
  |-- AgentRuntime
  |-- HitlService
  |-- PublicationService
  v
Graph Registry
  |-- review graph
  |-- future personal graph
  |-- future job graph
  |-- future retrospective graph
  |-- future mock interview graph
  v
Adapters and Policies
  |-- OpenAI-compatible adapter
  |-- Anthropic-compatible adapter
  |-- SecretStore
  |-- Tool Registry
  |-- Workspace Path Policy
  |-- Vault Writer and Indexer
```

### 4.1 API 层

API 层负责：

- 请求和响应 schema 校验。
- REST 命令与 SSE 连接。
- 将 workspace、session 和 action 上下文传给应用服务。
- 将领域错误映射为稳定的 HTTP 错误码。

API 层不直接：

- 访问文件系统。
- 读取 API Key。
- 调用模型。
- 编译或运行 Graph。
- 写入 Vault。

### 4.2 应用服务层

- `ProviderService`：Provider、模型、secret 引用和连接测试。
- `WorkspaceService`：Workspace 注册、可用性和模型用途绑定。
- `AgentRuntime`：Graph 注册、session、run、checkpoint 和事件。
- `HitlService`：pending action 创建、预览、批准、拒绝和恢复。
- `PublicationService`：草稿审核、Vault 发布、manifest 和索引更新。

### 4.3 Graph 层

每个 Graph 注册以下元数据：

- `graph_id`
- `graph_version`
- state schema
- graph factory
- required model roles
- allowed tools
- allowed directory scopes

Graph 不能直接访问底层数据库、文件系统或密钥链，只能调用 Runtime 注入的 Provider 和工具。

## 5. 数据归属与恢复

### 5.1 应用级数据

应用级数据放在操作系统应用数据目录，例如：

- macOS：`~/Library/Application Support/cyber-interview-agent/`
- Linux：`$XDG_DATA_HOME/cyber-interview-agent/`
- Windows：用户 Local App Data 下的 `cyber-interview-agent/`

其中 `app.sqlite` 保存：

- Provider 元数据。
- Provider Model。
- Workspace 注册表。
- Workspace Model Binding。
- Provider Test Run。
- schema migration 版本。

`app.sqlite` 删除后不能自动恢复，需要备份或重新配置。

### 5.2 Secret 数据

API Key 保存于：

1. 系统密钥链，首选。
2. 指定环境变量，兜底。

数据库只保存 `secret_ref` 或环境变量名称，不保存明文或可还原密文。

API Key 删除后不能自动恢复，只能重新录入。

### 5.3 Workspace 运行数据

```text
Workspace/
  .cyber-interview-agent/
    runtime.sqlite
  artifacts/
    review/
      sources/
      drafts/
  knowledge-vault/
```

`runtime.sqlite` 保存：

- session
- session message
- run
- event
- checkpoint
- pending action
- knowledge draft metadata
- publication run
- tool audit log
- schema migration 版本

运行数据中只有部分可以从业务文件恢复；关键 session、HITL 和 checkpoint 需要备份。

### 5.4 业务可信数据

- `artifacts/` 保存原始资料和领域草稿。
- `knowledge-vault/` 保存用户确认后的长期知识文档。

这两类数据本身是恢复来源，不能由索引自动还原，必须备份。

### 5.5 派生数据

以下数据可以从 Vault Markdown 和 frontmatter 重建：

- manifest 派生表。
- FTS 索引。
- 关系索引。
- 缓存和临时文件。

正式文档使用“删除后能否从其他数据自动恢复”，不使用容易误解的“是否可重建”。

## 6. Provider 与模型管理

### 6.1 Provider

Provider 字段：

- `id`
- `name`
- `api_format`
- `base_url`
- `secret_source`
- `secret_ref`
- `enabled`
- `created_at`
- `updated_at`

`api_format` 第一版支持：

- `openai-compatible`
- `anthropic-compatible`

`base_url` 只允许 HTTP/HTTPS，并拒绝在 URL 中嵌入用户名和密码。localhost 和私有网络地址允许使用，以支持本地模型服务。

### 6.2 Provider Model

模型字段：

- 内部稳定 `id`
- `provider_id`
- 真实 `model_id`
- `display_name`
- `enabled`
- `connectivity_status`
- `last_tested_at`
- `last_error_code`
- `last_latency_ms`

同一个 Provider 可以包含多个模型。连接状态记录在模型上，而不是只记录一个 Provider 总状态。

连接状态：

- `unknown`
- `ok`
- `secret_missing`
- `auth_failed`
- `model_not_found`
- `rate_limited`
- `timeout`
- `network_error`
- `protocol_error`

修改 Provider 协议、URL 或 API Key 后，旗下模型状态全部重置为 `unknown`。

### 6.3 Workspace Model Binding

R1 固定四种用途：

- `question_generation`
- `answer_evaluation`
- `report_summarization`
- `agent_chat`

每个 Workspace 为每种用途选择一个 Provider Model。run 启动时保存模型绑定快照，恢复旧 run 时不静默切换到新的模型绑定。

### 6.4 API Key

- 前端只允许创建、替换和删除 API Key。
- 读取 Provider 时只返回 `hasSecret` 和 `secretSource`。
- API Key 输入留空表示保留旧 secret。
- SecretStore 写入失败时，Provider 不得保存为可用状态。
- 删除 Provider 时删除对应密钥链项。
- 使用环境变量时只保存变量名，不保存变量值。

### 6.5 Provider 保存和删除

- Provider 可以在连接失败时保存。
- 删除被 Workspace Model Binding 使用的 Provider 或模型时返回 `409`，并列出占用关系。
- 用户必须先解除或替换绑定，才能删除。

### 6.6 真实连接测试

连接测试针对具体模型：

1. 选择对应协议 adapter。
2. 从 SecretStore 读取 API Key。
3. 发起一次最小、非流式模型请求。
4. 使用短超时和极小输出上限。
5. 记录状态、耗时和错误分类。
6. 不保存回复正文、请求头或 API Key。

前端明确提示连接测试会产生一次极小模型调用。

R1 不依赖 `/models` 自动发现接口，模型 ID 由用户手工维护。

### 6.7 Provider API

```text
GET    /api/settings/providers
POST   /api/settings/providers
PATCH  /api/settings/providers/{provider_id}
DELETE /api/settings/providers/{provider_id}

POST   /api/settings/providers/{provider_id}/models
PATCH  /api/settings/provider-models/{model_id}
DELETE /api/settings/provider-models/{model_id}
POST   /api/settings/provider-models/{model_id}/test

GET    /api/settings/workspaces
POST   /api/settings/workspaces
PATCH  /api/settings/workspaces/{workspace_id}
POST   /api/settings/workspaces/{workspace_id}/relink
GET    /api/settings/workspaces/{workspace_id}/model-bindings
PUT    /api/settings/workspaces/{workspace_id}/model-bindings
```

Workspace 注册接口接收本地路径并返回稳定 workspace id。后续 Agent、HITL 和知识 API 使用 workspace id，不再接收可任意改变的原始根路径。Workspace 移动后使用 `relink` 显式关联新路径。

## 7. Agent Runtime

### 7.1 标识

- `workspace_id`：已注册 Workspace 的稳定标识。
- `session_id`：产品会话标识，同时作为 LangGraph `thread_id`。
- `run_id`：一次输入、恢复或命令执行。
- `event_id`：session 内可排序、可重放的事件标识。

### 7.2 Session

Session 保存：

- id
- workspace id
- graph id
- graph version
- title
- status
- parent session id，可空
- summary
- created/updated time
- last run id

Session 状态：

- `active`
- `waiting_for_approval`
- `interrupted`
- `completed`
- `migration_required`
- `archived`

单次 run 失败不会永久关闭 session。失败信息保存在 run 上，session 回到可继续的 `active`，除非用户归档、完成会话或遇到版本迁移问题。

每个 session 固定 graph id 和 graph version。运行环境不存在兼容版本时，session 进入 `migration_required`，不能静默使用新版本恢复旧 checkpoint。

### 7.3 Run

每次新的用户输入创建 run。interrupt、HITL 或服务重启后的恢复沿用原 `run_id`，增加 resume attempt 计数并记录恢复事件。一个 session 同时只允许一个 active run。

Run 状态：

- `queued`
- `running`
- `waiting_for_approval`
- `interrupted`
- `completed`
- `failed`
- `cancelled`

Run 保存模型绑定快照，保证恢复时使用相同 Provider 和模型。

### 7.4 Checkpoint 与产品数据

LangGraph checkpoint 只用于恢复 Graph 执行状态。

以下数据使用独立产品表保存，不依赖 checkpoint：

- 会话标题和状态。
- 用户和 Agent 消息。
- run 状态和错误。
- pending action。
- 草稿和发布记录。
- 工具审计记录。

前端读取产品表，不能直接解析 checkpointer 内部格式。

### 7.5 执行模型

- R1 使用进程内异步执行，不引入外部任务队列。
- 每个 session 使用互斥锁，拒绝并发 run。
- 服务重启后，原 `running` run 标记为 `interrupted`。
- 用户可以从最后 checkpoint 恢复。
- `waiting_for_approval` 在重启后继续等待，不自动失败。
- 用户取消 run 时在下一个安全节点停止。

### 7.6 Middleware 设计规则

后续 Runtime 增加统一 middleware 层，用于承载跨 Graph、跨 Agent、与具体业务节点无关的横切能力。判断一项功能是否应实现为 middleware，至少满足以下多数条件：

- 对多个 Graph/Agent 使用相同触发时机和处理规则；
- 关注模型调用、消息、工具调用或 run 生命周期，而不是领域状态转换；
- 可以通过 before/after hook、包装调用或标准事件完成；
- 失败时能够采用统一降级策略，不应部分提交领域副作用；
- 输入输出可以定义稳定、可测试、可组合的窄契约；
- middleware 顺序、幂等性和可观测性能够明确说明。

优先通过 middleware 实现：

- 模型调用 token、context、耗时和费用统计；
- context budget 检查、消息裁剪和上下文压缩触发；
- 会话标题自动总结、待办事项候选提取、关键结论和长期记忆候选提取；
- 通用 tracing、审计、敏感信息脱敏、错误归一化和重试策略；
- 普通工具调用的统一 approve/edit/reject 拦截。

Middleware pipeline 固定分为三层，按以下顺序执行：

1. **Guard middleware**：权限和 scope、HITL 拦截、最大节点步数、工具调用数、运行时间、token/费用预算、无限循环和无进展检测；
2. **Invocation middleware**：模型/工具调用包装、token/费用/耗时统计、超时、限流、重试、fallback、schema 校验、tracing、错误归一化和脱敏；
3. **Post-processing middleware**：会话标题、阶段摘要、待办事项候选、主题标签、关键结论、长期记忆候选和下一步建议。

无限循环检测必须综合多个信号，不能只依赖固定步数：重复节点路径、重复工具名与规范化参数、连续相同错误、token 持续增长、连续多轮无产品状态变化、运行时间和费用预算。达到软阈值时先产生诊断事件并允许一次受控纠偏；达到硬阈值时终止 run，保存稳定错误码和可恢复说明。不得由 middleware 自动重复启动新 run。

待办事项采用“候选提取 + 领域服务确认”边界。Post-processing middleware 只输出带来源消息、置信度、建议标题、截止时间和关联对象的候选项；Todo Service 负责去重、持久化、状态转换、撤销和用户确认。Middleware 不得静默创建不可撤销的正式待办。

候选能力目录：

- **模型治理**：token/context/费用/耗时、context budget、压缩、限流、重试、fallback、响应格式校验；
- **运行保护**：无限循环、最大步骤、重复工具调用、无状态进展、连续错误、超时、费用熔断和取消传播；
- **会话增强**：标题、摘要、待办候选、主题分类、关键结论、偏好和记忆候选；
- **工具治理**：参数 schema、scope、审批、频率限制、只读缓存、敏感参数清理和重复副作用拦截；
- **可观测性**：tracing、审计、质量评分、低置信度标记、模型/Prompt 版本和统一指标；
- **体验事件**：长任务进度、失败恢复建议、预算预警和统一状态说明。

首批只实现六项：token/context 统计、context budget 与上下文压缩、会话标题总结、待办事项候选提取、无限循环检测、HITL middleware adapter。其他候选项保留为后续扩展，不得在首批中顺带实现。

不应仅通过 middleware 隐藏实现：

- 知识发布、草稿版本推进、Vault 写入和索引更新等领域状态机；
- 需要用户明确理解的业务分支、长事务和补偿流程；
- 依赖 action version、content hash、operation id 或领域幂等键的副作用；
- 必须在 Graph 拓扑中显式表达的编排步骤。

HITL 采用分层方案：保留现有 `HitlService`、pending action repository、resolution receipt、handler 和 `interrupt()/Command(resume=...)` 持久化语义；在其上补一层 middleware/adapter，统一普通工具审批和 action 创建模板。`knowledge.publish` 等复杂领域审批继续使用显式 Graph 节点与 handler，不把业务状态机迁入 middleware。

所有 middleware 必须声明：适用范围、执行顺序、持久化边界、失败/降级策略、幂等键、产生的事件与指标，以及不允许承载的领域副作用。Graph 或 Agent 新增横切能力前，先完成“middleware / 显式节点 / 应用服务”归属判断，禁止在各 Graph 中复制相同包装逻辑。

采用 middleware 的预期收益是：一次实现供全部 Agent/Graph 复用；业务节点只表达领域编排；安全、成本和质量策略保持一致；新 Agent 默认获得基础治理；每项能力可独立测试、替换、开关和观测；执行预算和错误语义可以集中配置。对应代价是 pipeline 顺序、共享状态、额外模型调用和失败传播更复杂，因此 middleware 必须保持单一职责，禁止形成一个拥有全部 Runtime 状态的“大中间件”。

## 8. SSE 事件协议

### 8.1 事件持久化

所有 SSE 事件先写入 runtime DB，再发送给前端。

前端重连时使用 `Last-Event-ID` 或 `after` 参数补发事件。SSE 断开不会自动取消后端 run。

### 8.2 事件 Envelope

事件至少包含：

- `id`
- `sessionId`
- `runId`
- `type`
- `timestamp`
- `payload`

Payload 必须经过事件类型 schema 校验和敏感信息过滤。

### 8.3 初始事件类型

- `session.created`
- `run.started`
- `graph.node.started`
- `graph.node.completed`
- `message.delta`
- `message.completed`
- `tool.started`
- `tool.completed`
- `tool.failed`
- `hitl.required`
- `hitl.resolved`
- `draft.created`
- `publication.started`
- `publication.completed`
- `publication.index_stale`
- `run.interrupted`
- `run.completed`
- `run.failed`
- `run.cancelled`

### 8.4 Agent API

```text
POST /api/agent/sessions
GET  /api/agent/sessions
GET  /api/agent/sessions/{session_id}
POST /api/agent/sessions/{session_id}/runs
POST /api/agent/runs/{run_id}/resume
POST /api/agent/runs/{run_id}/cancel
GET  /api/agent/sessions/{session_id}/events
```

Session 列表按 workspace id 过滤。Session 详情返回产品消息、最近 run 和当前 pending action 摘要，不暴露 checkpointer 内部数据。`events` 使用 SSE。

## 9. Workspace 沙箱与 Tool Registry

### 9.1 Execution Context

每次工具调用由 Runtime 注入：

- workspace id
- session id
- run id
- agent type
- allowed tools
- allowed directory scopes

模型不能修改 Execution Context。

### 9.2 路径规则

- Agent 工具只接受相对路径。
- 拒绝绝对路径、`..`、空字节和非法目录。
- 解析路径后确认仍在授权 Workspace 子目录内。
- 拒绝通过软链接跳出 Workspace 或授权子目录。
- 创建文件前验证已存在的父目录。
- 真正执行 I/O 前再次校验路径。
- 文件工具不接受前端或模型传入的新 Workspace 根路径。

### 9.3 Tool Registry

每个工具声明：

- tool name
- input schema
- output schema
- risk level
- required scope
- audit policy

权限默认拒绝。Graph 只能调用注册并授权的工具。

R1 Review Agent 权限：

- 允许读取 active knowledge 文档，只读。
- 允许读取 review source。
- 允许在 review draft 目录创建草稿。
- 禁止直接写 Vault。
- 禁止修改 Provider。
- 禁止任意 HTTP 请求。
- 只允许通过 PublicationService 发布知识。
- 只允许调用 Runtime 注入的模型。

### 9.4 审计

工具审计记录工具名、session、run、结果状态、耗时和脱敏资源标识。

审计记录不保存：

- API Key。
- Provider 请求头。
- 完整敏感文件正文。
- 未经脱敏的模型请求和回复。

## 10. 持久化 HITL

### 10.1 Pending Action

字段：

- id
- workspace id
- session id
- run id
- action type
- payload
- preview
- status
- version
- idempotency key
- created/resolved time

状态：

- `pending`
- `approved`
- `edited_and_approved`
- `rejected`
- `cancelled`

### 10.2 初始 Action 类型

- `knowledge.publish`
- `document.activate`
- `file.overwrite`
- `mastery.update`
- `conflict.resolve`

### 10.3 处理规则

- Graph 创建 action 后触发 LangGraph interrupt。
- run 进入 `waiting_for_approval`。
- 用户可以接受、编辑后接受、拒绝或稍后处理。
- action version 防止批准过期内容。
- idempotency key 防止重复点击执行两次。
- 并发处理已解决 action 时返回 `409 action_already_resolved`。
- 服务重启后 action 与 checkpoint 保持可恢复。

### 10.4 HITL API

```text
GET  /api/agent/actions?workspace_id=...&status=pending
GET  /api/agent/actions/{action_id}
POST /api/agent/actions/{action_id}/approve
POST /api/agent/actions/{action_id}/reject
```

批准请求必须提交 action version 和 idempotency key，并可携带经过 schema 校验的 edited payload。编辑后批准时，HitlService 先保存新的草稿版本，再由 PublicationService 发布该精确版本。

## 11. 知识草稿与发布

### 11.1 三层数据

原始资料：

```text
Workspace/artifacts/<domain>/sources/
```

Agent 草稿：

```text
Workspace/artifacts/<domain>/drafts/
```

已发布知识：

```text
Workspace/knowledge-vault/
```

草稿不会进入 Vault，也不会参与 active knowledge 检索。

### 11.2 Knowledge Draft

草稿正文使用 Markdown，runtime DB 保存：

- id
- workspace id
- session id
- run id
- agent type
- document type
- title
- content path
- source refs
- relation refs
- status
- version
- content hash
- created/updated time

状态：

- `draft`
- `review_pending`
- `rejected`
- `published`

### 11.3 发布流程

1. Agent 生成领域草稿。
2. 用户请求推送知识库。
3. 系统创建 `knowledge.publish` pending action。
4. 用户预览、编辑、批准或拒绝。
5. PublicationService 校验草稿版本和 hash。
6. 使用临时文件和原子替换写入 Vault。
7. 更新 manifest、FTS 和关系索引。
8. 草稿与 publication run 标记 published。

### 11.4 一致性与幂等

- Action 绑定 draft id、version 和 content hash。
- 草稿变化后，旧 action 返回 `409 draft_version_changed`。
- 文档使用稳定 id 和确定性路径。
- 重复批准同一 action 返回同一路径，不生成第二份文件。
- Publication Run 记录发布阶段，服务重启后可恢复或安全重试。
- Markdown 写入成功后即成为发布事实。
- 索引失败时标记 `index_stale`，rescan 负责修复，不删除已发布 Markdown。
- 已被 Obsidian 修改的文件不静默覆盖，返回冲突。

### 11.5 Vault Frontmatter

至少包含：

```yaml
schema_version: 1
id: question_xxx
type: question
status: ingested
title: 缓存穿透是什么
source_refs:
  - source_xxx
relation_refs: []
ingestion:
  confirmed_by_user: true
  published_at: 2026-07-10T12:00:00Z
provenance:
  agent_type: review
  session_id: session_xxx
  run_id: run_xxx
  model_id: model_xxx
```

不写入 API Key、Provider 请求头、完整 system prompt、checkpoint 或隐藏分析内容。

### 11.6 Active Knowledge Scope

只有同时满足以下条件的文档进入正式 Agent 检索：

```text
status == ingested
ingestion.confirmed_by_user == true
```

`draft`、`review_pending`、`stale` 和 `archived` 不进入 active scope。

R1 支持现有类型：

- source
- question
- concept
- session_report
- mastery_report

后续阶段通过文档类型注册扩展 PublicationService。

### 11.7 Knowledge Draft API

```text
GET   /api/knowledge/drafts?workspace_id=...
GET   /api/knowledge/drafts/{draft_id}
PATCH /api/knowledge/drafts/{draft_id}
POST  /api/knowledge/drafts/{draft_id}/publish-request
```

修改草稿必须提交当前 version，版本不一致返回 `409 draft_version_changed`。`publish-request` 只创建 pending action，不直接写入 Vault。

## 12. 异常与恢复

### 12.1 Provider

- 缺少 API Key：run 不启动，返回 `secret_missing`。
- 鉴权失败、模型不存在、协议错误：不自动重试。
- 限流、超时和服务端错误：最多自动重试两次，并记录 retry event。
- 连接失败不删除 Provider 或用户输入。

### 12.2 Runtime

- SSE 断线不取消 run。
- 服务重启后，running run 变为 interrupted。
- waiting_for_approval 保持等待。
- Graph 节点失败时保留最后稳定 checkpoint。
- 恢复必须使用原 graph version 和模型绑定快照。
- 用户取消后在下一个安全节点停止；已完成的外部模型调用可能产生费用，但结果不继续写入状态。

### 12.3 工具与发布

- 有副作用工具不盲目自动重试，必须使用 operation id 或 idempotency key。
- 重复确认不重复执行。
- Vault 写入成功但索引失败时进入 index stale。
- 外部修改产生冲突，不静默覆盖。

### 12.4 数据库与 Workspace

- schema migration 使用事务和版本记录。
- 关键数据库迁移前创建本地备份。
- SQLite 锁定时返回明确诊断，不创建新数据库覆盖旧库。
- SQLite 损坏时停止写入并提示恢复，不静默重建关键数据。
- Workspace 移动后标记 unavailable，重新关联路径后继续使用原 workspace id。

## 13. 本地服务安全边界

- 后端默认只监听 `127.0.0.1`。
- CORS 只允许配置的前端 origin。
- API 主要接受 JSON，拒绝不符合 schema 的跨站表单请求。
- Agent 不能调用设置管理 API。
- 导入文档内容不能修改 Tool Registry、Workspace 或 Provider 配置。
- Provider adapter 是 R1 唯一允许的外部网络访问入口。
- 远程访问和移动端需要后续身份认证设计，R1 不开放局域网监听。

## 14. 前端体验

### 14.1 设置页

- Provider 列表和连接摘要。
- Provider 编辑：名称、协议、Base URL、API Key 替换。
- 模型列表、添加、编辑、删除和逐模型测试。
- Workspace 模型用途绑定。
- 删除占用冲突、密钥缺失、鉴权失败和模型不存在的操作建议。

### 14.2 会话体验

- 后端 session 是状态真相来源。
- 页面刷新后恢复 session 和最终消息。
- SSE 展示节点、模型输出、工具和错误事件。
- 断线显示重连状态，不误报 run 失败。
- interrupted run 提供恢复入口。

### 14.3 HITL 与发布

- 待确认列表。
- Action 详情、来源、内容差异和影响范围。
- 接受、编辑后接受、拒绝。
- 发布成功路径、冲突和 index stale 提示。

## 15. 测试策略

### 15.1 单元测试

- Provider schema、密钥脱敏、模型绑定和错误分类。
- Graph registry、session/run 状态机。
- pending action 状态和幂等处理。
- 路径穿越、软链接越界和 tool allowlist。
- 草稿版本、Markdown/frontmatter 和稳定路径。
- SSE event schema 和敏感信息过滤。

### 15.2 集成测试

使用临时 app data、临时 Workspace、Fake SecretStore 和 Fake Provider：

- Provider CRUD、多模型和 Workspace 绑定。
- OpenAI-compatible 与 Anthropic-compatible adapter contract。
- session、checkpoint、服务重启和恢复。
- SSE 断线后按 event id 补发。
- HITL 创建、重启、编辑批准、拒绝和重复批准。
- PublicationService 原子写入和重复提交。
- 索引失败后 rescan 修复。
- Agent 尝试访问 Workspace 外文件时被拒绝。

自动测试不依赖真实 API Key 或外部网络。

### 15.3 前端测试

- Provider 列表、编辑、模型测试和错误提示。
- Workspace 模型用途绑定。
- session 刷新恢复。
- SSE 进度与断线重连。
- HITL 预览、编辑、接受和拒绝。
- 发布成功、冲突和 index stale 状态。

### 15.4 人工验收

1. 保存两个 Provider，并在同一 Provider 下添加多个模型。
2. 分别测试 OpenAI-compatible 和 Anthropic-compatible。
3. 为 Workspace 配置四种模型用途。
4. 启动一次单题复习并观察 SSE。
5. 刷新页面并恢复会话。
6. 在运行中重启后端，从 checkpoint 恢复。
7. Graph 生成草稿并停在 HITL。
8. 编辑后批准，确认 Vault 生成一份 Markdown。
9. 重复批准不生成第二份文件。
10. 拒绝另一份草稿，确认 Vault 无新增文件。
11. 在 Obsidian 修改已发布文档，再次发布时看到冲突。
12. 验证 Agent 无法读取 Workspace 外文件。

两种 adapter 都必须有自动 contract 测试。R1 标记为“场景可用”前，还需要至少一个真实 OpenAI-compatible 和一个真实 Anthropic-compatible 服务完成连接测试；缺少真实凭证时只能标记为“技术验证通过，真实协议待验收”。

## 16. 实施切片

### R1.1 应用配置与 Provider

- app data resolver 和 app.sqlite。
- Provider、Model、Workspace、Binding schema。
- SecretStore。
- Provider CRUD 和真实测试。
- 设置页 Provider 管理与模型用途绑定。

### R1.2 会话 Runtime 与 SSE

- runtime.sqlite。
- Graph Registry。
- session、run、message、event。
- SQLite checkpointer。
- SSE replay。
- Fake Graph 端到端测试。

### R1.3 工具权限与 Workspace 沙箱

- Execution Context。
- Tool Registry。
- 路径和 scope policy。
- 工具审计。
- 安全测试。

### R1.4 持久化 HITL

- pending action schema 和服务。
- LangGraph interrupt/resume。
- 幂等确认。
- 前端待确认体验。

### R1.5 知识草稿与发布

- artifacts 目录和 draft schema。
- PublicationService。
- Vault writer、manifest/index 更新。
- 冲突和 index stale。
- 发布预览与确认。

### R1.6 单题复习迁移验收

- 现有 review graph 注册到共享 Runtime。
- 真实 Provider 调用。
- SSE 输出和会话恢复。
- 生成知识草稿。
- HITL 批准后发布 Vault。
- 完整人工验证说明。

## 17. 现有代码迁移边界

可以沿用：

- 现有 Provider 和 Workspace Pydantic schema 的字段命名习惯。
- 现有 Settings、Knowledge、Review 页面作为渐进式 UI 入口。
- 现有 review graph 作为 R1.6 迁移对象。
- 现有 Vault、Markdown、manifest、FTS 和 workspace 模块。

需要替换或增强：

- 进程内 `_workspace` 替换为 Workspace Registry。
- 字符串形式 Provider 测试替换为真实 adapter。
- 当前一次性 Graph 调用替换为共享 Runtime 和 checkpoint。
- 前端 `AppShell` 内存会话状态替换为后端 session。
- 文件系统调用接入 Workspace Path Policy 和 Tool Registry。
- 报告确认接口逐步迁移到统一 pending action 和 PublicationService。

不做无关重构。每个切片只修改完成该能力所需的现有模块。

## 18. R1 完成定义

R1 达到“技术验证通过”必须满足：

- 六个实施切片全部通过自动测试。
- Provider、Runtime、SSE、沙箱、HITL 和 PublicationService 形成一条单题复习链路。
- 前后端构建和测试通过。
- 两种 Provider adapter contract 自动测试通过。
- 用户可以按验证文档独立完成端到端流程。
- 所有剩余粗糙边界在验证文档中明确列出。

R1 达到“场景可用”还必须满足：

- 使用真实 OpenAI-compatible 服务完成连接和单题调用。
- 使用真实 Anthropic-compatible 服务完成连接和最小调用。
- 服务重启、SSE 断线、HITL 恢复和重复发布经过人工验证。
- Workspace 外文件访问经过人工安全验证。

完整多题复习不属于 R1 完成定义。
