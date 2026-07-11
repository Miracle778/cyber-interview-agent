# R1.2 Agent Runtime 与 SSE 设计复核

## 1. 复核目的

R1.2 的架构已经在 `2026-07-10-r1-shared-agent-foundation-design.md` 中通过用户确认，本次不重新设计共享 Runtime，而是基于 R1.1 Provider 落地和产品布局重构后的代码现状，确认实施边界、前端演进方式和任务分工。

## 2. 保持不变的已确认设计

- `session_id` 同时作为 LangGraph `thread_id`。
- 新用户输入创建新 `run_id`；中断恢复沿用原 run 并增加恢复计数。
- 产品 session、message、run、event 与 LangGraph checkpoint 分开保存。
- Workspace 内 `.cyber-interview-agent/runtime.sqlite` 是 Runtime 产品数据和 SQLite checkpointer 的存储位置，但 API 不暴露 checkpoint blob。
- Graph Registry 必须按 `(graph_id, graph_version)` 精确解析，不能静默升级旧会话。
- 每个 session 同时只允许一个 active run。
- SSE 事件先持久化再发送，支持 `Last-Event-ID` 和 `after` 重放。
- R1.2 只使用确定性 Fake Graph，不调用真实 Provider；真实复习迁移属于 R1.6。
- 服务启动时把遗留 `running` run 标记为 `interrupted`，不自动重放可能产生外部副作用的模型调用。

## 3. 本次发现的设计缺口

旧 R1.2 计划只交付前端 API client 和 EventSource hook，并明确“不迁移业务页面”。这保证了后端边界，但会造成浏览器中没有可操作入口，用户只能通过测试或 curl 判断 Runtime 是否工作，不符合项目“每个切片都有人工可验证闭环”的执行原则。

产品布局重构后，设置页已经承担 Workspace、Provider、模型和运行环境配置，因此 Runtime 技术验证入口应放在设置页，而不是把确定性测试 Graph 混入复习工作区。

## 4. 方案比较

### 方案 A：只交付前端 client

优点是范围最小；缺点是用户看不到 session、run、SSE 和恢复是否真实工作，仍像后端骨架。

### 方案 B：设置页 Runtime 自检（采用）

在设置页新增“Agent Runtime”区域，通过确定性 `test.echo` Graph 提供一次真实自检：创建或恢复自检 session、启动 run、显示事件连接和最终结果。它是运行环境诊断能力，不冒充完整复习 Agent，也不会污染复习页面状态。

### 方案 C：提前迁移复习页

能形成更强产品体感，但会绕过 R1.3 工具安全、R1.4 HITL 和 R1.5 发布协议，使临时实现未来还要拆除，因此不采用。

## 5. 后端落地结构

### 5.1 Runtime Database

每个已注册 Workspace 使用自己的 `.cyber-interview-agent/runtime.sqlite`。迁移 `001_runtime.sql` 创建：

- `agent_sessions`
- `agent_messages`
- `agent_runs`
- `agent_events`
- Runtime migration ledger

数据库启用 foreign keys、WAL 和 busy timeout。状态值由 SQL CHECK 与 Python Literal 双重约束。

### 5.2 Repository 与事务

Repository 负责记录映射和显式状态转换。创建 run 和 active 状态转换使用 `BEGIN IMMEDIATE`，数据库唯一约束作为进程锁之外的最终并发防线。任何转换都必须提交 expected source status；陈旧状态不能被覆盖。

### 5.3 Graph Registry 与 Checkpointer

`GraphDefinition` 声明 graph ID、版本、factory、模型用途、工具和 scope。R1.2 注册 `test.echo` version 1，输入文本后确定性地产生一条 Agent 消息。

`RuntimeCheckpointer` 封装 LangGraph SQLite saver 生命周期。Graph 只能通过 Registry factory 获得 checkpointer，业务 API 和前端不能读取其内部表。

### 5.4 Event Stream

`EventStream.publish` 的顺序固定为：校验事件类型与 payload、递归脱敏、写入数据库并提交、通知内存 subscriber。订阅先重放 `after_id` 之后的数据库事件，再等待新事件，并定期发送 SSE comment 保活。

### 5.5 RunManager 与 AgentRuntime

RunManager 管理进程内 task、session lock、取消和恢复；Repository 仍是状态真相源。AgentRuntime 负责 Workspace 解析、Graph 版本校验、模型绑定快照、资源组装和 RunManager 调用，不把 FastAPI request 对象传入 Runtime。

## 6. REST 与 SSE

继续使用已确认接口：

```text
POST /api/agent/sessions
GET  /api/agent/sessions?workspaceId=...
GET  /api/agent/sessions/{session_id}
POST /api/agent/sessions/{session_id}/runs
POST /api/agent/runs/{run_id}/resume
POST /api/agent/runs/{run_id}/cancel
GET  /api/agent/sessions/{session_id}/events?after=...
```

创建 session 返回 201，启动/恢复 run 返回 202。并发 run 返回结构化 `409 session_busy`。SSE envelope 使用 camelCase，错误 payload 只包含可展示 code/message，不包含异常堆栈、密钥或 Provider 请求内容。

## 7. 前端演进

### 7.1 Agent Client

`features/agent` 提供 session/run API、事件联合类型和 `useAgentEvents`。Hook 只维护连接状态、事件去重和增量显示；刷新或重连后的最终 session/message/run 仍从 session detail REST 读取。

### 7.2 Runtime 自检面板

设置页在 Workspace 就绪后显示 Agent Runtime 区域：

- Runtime 可用状态。
- 最近一次自检 session 和 run 状态。
- SSE 状态：连接中、已连接、重连中、已断开。
- “运行自检”主操作。
- 事件时间线，显示 run started、message completed、run completed/failed。
- 刷新后从 session 列表和详情恢复最近结果。

没有 Workspace 时不显示面板，避免制造不可操作入口。自检 session 固定 `graphId=test.echo`、`graphVersion=1`，标题为“Agent Runtime 自检”。面板不出现开发术语解释，不展示 checkpoint 或原始 JSON。

### 7.3 响应式与可访问性

面板沿用当前设置页卡片、按钮、状态色和 4/8 间距。事件时间线在桌面和平板保持普通文档流，375px 下换行且无水平滚动。状态不能只靠颜色，异步按钮禁用并显示 loading，SSE 状态使用 `aria-live=polite`。

## 8. 错误与恢复

- Workspace 不可用：REST 返回 404/409，前端保留设置内容并显示恢复建议。
- Graph 版本缺失：session 进入 `migration_required`，不能启动 run。
- SSE 断开：run 继续，hook 使用最后 event ID 重连；重复事件被忽略。
- Run 失败：run 保存 code/message，session 回到 active，可再次运行。
- 服务重启：running 变 interrupted；自检面板显示“可恢复”，由用户显式恢复。
- 取消：重复取消幂等，完成后的取消不改写最终状态。

## 9. 任务复杂度与分工

| 任务 | 复杂度 | 执行者 | 原因 |
|---|---|---|---|
| Runtime DB 与模型 | 中 | Codex | 定义全部后续状态契约 |
| Graph Registry | 低-中 | Codex | 代码少但版本边界关键 |
| Repository | 高 | Codex | SQLite 事务、并发与状态机 |
| Event Stream | 高 | Codex | 持久化顺序、重放、脱敏、异步订阅 |
| Checkpointer/RunManager | 很高 | Codex | LangGraph 生命周期、并发、取消、恢复 |
| REST/SSE | 高 | Codex | 跨 Workspace、Runtime、FastAPI 错误语义 |
| 前端 client/hook | 高 | Codex | EventSource 重连、去重、后端真相源 |
| 设置页 Runtime 自检 | 中-高 | Codex | 需要与新产品骨架和真实 API 联调 |

本切片不委派 Claude。虽然前两项局部代码量较小，但所有任务共享数据库、状态和事件契约，拆给外部实现的上下文交接和返工风险高于节省的 token。

## 10. 验收

- 确定性 session、message、run、event 和 checkpoint 持久化在 Workspace Runtime DB。
- 同一 session 的并发 run 被拒绝。
- 事件断线后可按 ID 重放且不重复。
- 进程重启后 running 变 interrupted，已完成 session 可恢复详情。
- 设置页可以完成一次 Runtime 自检并实时看到状态，刷新后仍显示最终结果。
- 前端现有布局在 1440、1024、768、375px 继续成立。
- 后端、前端、production build 和 Playwright 全部通过。
- R1.2 不调用真实模型、不访问 Workspace 文件工具、不实现 HITL 或知识发布。
