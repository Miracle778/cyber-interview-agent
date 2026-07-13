# R1.3 Workspace 工具安全设计复核

> **历史实现记录，禁止作为后续模板：** 本文保留 R1/Pre-R2 当时的设计、实施和验收事实。
> 其中涉及的自研 `AgentRuntime`、`RunManager`、Gateway、Registry/Executor、middleware
> pipeline 或旧 session/run API 已由
> `docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md` 取代。
> R2-R8 必须以产品总路线、框架收敛设计和各阶段新 spec 为准；本文中的领域安全、
> HITL、发布和恢复不变量仍可作为历史证据，但代码路径和协议名称可能已不存在。

## 1. 文档目的

本文复核 R1 总规格和既有 R1.3 实施计划，并补充可人工操作的工具安全自检。R1.3 的目标不是增加更多文件能力，而是建立所有后续 Agent 必须经过的默认拒绝工具边界。

## 2. 当前基线

R1.2 已提供：

- Workspace 级 Runtime SQLite；
- versioned Graph Registry；
- session、run、message、event 和 checkpoint；
- REST 命令、SSE 重放和进程恢复；
- `GraphDefinition.allowed_tools` 与 `allowed_scopes` 元数据位置。

当前 Graph factory 只接收 checkpointer，尚无安全工具注入接口；现有知识上传和 rescan 仍存在直接路径拼接边界；R1.3 必须在不提前实现 HITL、知识发布和真实复习 Graph 的前提下解决这些问题。

## 3. 范围

### 3.1 包含

- Workspace 相对路径策略和固定 scope 映射；
- 绝对路径、父目录、NUL、空路径和软链接越界拒绝；
- 不可变 `ToolExecutionContext`；
- 默认拒绝的 Tool Registry；
- 工具输入输出 schema、风险、required scope 和审计策略；
- 有大小上限的文本读取和带 hash 冲突保护的草稿写入；
- 脱敏工具审计以及 `tool.started/completed/failed` 事件；
- 现有知识上传/rescan 路径边界迁移；
- 设置页独立“工具安全”自检卡片；
- 自动测试、浏览器验收、verification 文档和 ownership 掌握包。

### 3.2 不包含

- 任意 shell、任意 HTTP 或动态安装工具；
- 模型自行申请新权限；
- R1.4 pending action 和人工批准；
- R1.5 草稿发布到 Vault；
- R1.6 真实单题复习 Graph；
- R2 多题轮次和追问策略。

## 4. 方案选择

### 4.1 采用：独立策略、Registry、Invoker 和 Graph 构建上下文

```text
LangGraph
  -> BoundToolInvoker
  -> ToolRegistry
  -> tool/scope/schema checks
  -> WorkspacePathPolicy
  -> tool handler
  -> sanitized audit + SSE event
```

`RunManager` 只负责根据 session、run、Workspace 和 GraphDefinition 构造执行边界，不直接实现路径、工具 handler 或审计细节。

### 4.2 不采用：把 Workspace root 放进 Graph state

Graph state 会进入 checkpoint，也可能被模型或导入内容影响。Workspace root、allowed tools 和 allowed scopes 不能成为可变 state 字段。

### 4.3 不采用：由每个 Graph 自行做路径检查

分散检查容易产生规则漂移，也无法保证现有 API 和未来 Graph 使用同一套软链接、创建父目录和二次校验规则。

## 5. 组件设计

### 5.1 WorkspacePathPolicy

R1 固定 scope：

```text
review.sources     -> artifacts/review/sources
review.drafts      -> artifacts/review/drafts
knowledge.active   -> knowledge-vault
diagnostics.security -> .cyber-interview-agent/diagnostics
```

`diagnostics.security` 只允许内部确定性诊断 Graph 使用，不提供给业务 Agent。

策略要求：

- 输入必须是非空相对路径；
- 拒绝绝对路径、`.`、`..`、NUL 和非法空组件；
- 授权根目录必须位于已注册 Workspace；
- read 要求目标存在且为普通文件；
- create 要求父目录已存在并位于授权 scope；
- 拒绝路径链中的软链接组件；
- handler 在真正 I/O 前再次调用策略，降低检查后替换风险；
- 返回错误只包含逻辑 scope、相对路径和稳定 code，不返回越界绝对路径。

### 5.2 ToolExecutionContext

不可变上下文包含：

```text
workspace_id
workspace_root
session_id
run_id
graph_id
graph_version
allowed_tools
allowed_scopes
```

上下文只由 Runtime 根据持久化记录和 GraphDefinition 构造。模型输入、Graph state、导入文档和 API payload 都不能填充或覆盖这些字段。

### 5.3 ToolDefinition 与 ToolRegistry

每个工具声明：

```text
name
input_model
output_model
risk_level
required_scope
audit_policy
handler
```

Registry 启动时注册，重复名称直接失败。调用顺序固定为：

1. 工具存在；
2. 工具位于 Graph allowed tools；
3. required scope 位于 Graph allowed scopes；
4. 输入 schema 校验且拒绝未知字段；
5. 执行 handler；
6. 输出 schema 校验。

任何一步失败都不能调用后续 handler。

### 5.4 BoundToolInvoker

Invoker 绑定当前 `ToolExecutionContext`、Registry、PathPolicy、AuditRepository 和 EventStream，向 Graph 只暴露：

```python
async def invoke_tool(name: str, raw_input: dict[str, object]) -> dict[str, object]: ...
```

调用生命周期：

```text
authorize
  -> persist sanitized audit(started)
  -> publish tool.started
  -> invoke handler
  -> persist sanitized audit(completed/failed)
  -> publish tool.completed/tool.failed
```

审计与事件不保存文件完整正文、API key、请求头、Workspace 绝对路径或异常堆栈。允许保存工具名、逻辑 scope、相对资源、状态、耗时、byte count 和内容 hash。

### 5.5 GraphBuildContext

Graph factory 从单独 checkpointer 参数演进为构建上下文：

```python
@dataclass(frozen=True)
class GraphBuildContext:
    checkpointer: object
    invoke_tool: ToolInvokerProtocol
```

现有 `test.echo` Graph 使用新的 checkpointer 字段但不申请任何工具。工具入口通过运行时闭包绑定，不进入 Graph state 或 checkpoint。

## 6. 文件工具

R1.3 注册：

- `read_source`：读取 `review.sources`；
- `read_active_knowledge`：只读 `knowledge.active`；
- `write_review_draft`：写入 `review.drafts`；
- `diagnostic_read`：只供 `test.tool-security` 使用。

读取有固定最大 byte 数，返回 UTF-8 文本、相对路径和 SHA-256。草稿覆盖必须提交 `expected_sha256`；不匹配时返回稳定冲突错误。文件工具不能发布 Vault、修改正式知识或自行创建未授权目录。

## 7. 工具安全自检

设置页在 Agent Runtime 卡片后增加独立“工具安全”卡片，不嵌套卡片，不修改复习页面。

固定 Graph：

```text
graph_id: test.tool-security
graph_version: 1
allowed_tools: diagnostic_read, read_active_knowledge
allowed_scopes: diagnostics.security
```

每次自检准备一个不含用户内容的 probe 文件，并验证：

1. `diagnostic_read` 授权读取成功；
2. 未注册 `shell` 在执行前被拒绝；
3. Graph 允许但缺少 `knowledge.active` scope 的 `read_active_knowledge` 被拒绝；
4. `diagnostic_read` 的 `../` 路径被拒绝；
5. 审计和 SSE payload 不包含 probe 正文、绝对路径或注入 secret。

诊断 Graph 捕获预期拒绝并形成检查结果；只有安全边界未按预期工作时 run 才失败。页面通过现有 Agent session/run/detail/SSE 接口恢复状态，不增加第二套临时运行协议。

卡片展示：

- 安全策略可用状态；
- 最近 run 状态；
- SSE 连接状态；
- 四项检查结果；
- 整理后的工具事件时间线；
- 失败后的可操作建议。

页面不展示原始 payload、完整正文、checkpoint、绝对路径或异常堆栈。375px 下按钮、检查项和事件行必须换行且无水平溢出。

## 8. 错误与恢复

稳定错误至少包括：

```text
tool_not_allowed
tool_scope_denied
tool_input_invalid
tool_output_invalid
workspace_path_denied
file_too_large
draft_version_changed
tool_execution_failed
```

未知工具和权限失败在 handler 前返回。工具失败默认使当前 Graph 节点按业务逻辑处理；未捕获错误由 RunManager 转为安全的 `run.failed`。工具审计先持久化再发送 SSE，刷新后可通过 session event 重放。

## 9. 现有文件边界迁移

知识上传和 rescan 保持现有浏览器/API 契约，但内部目标路径必须使用 WorkspaceService 定位已注册 Workspace，并委派给 WorkspacePathPolicy。旧 `ensure_inside_workspace` 只在仍有兼容调用时保留，内部不得维护另一套路径算法。

## 10. 前端演进

前端新增 typed 安全检查事件解释和 `SecurityDiagnostics` 组件。它复用 `agentApi`、`useAgentEvents` 和 React Query，不自行读取审计数据库。

历史 run 事件不能污染最新诊断；终态后重新读取 session detail；SSE 仅维护增量状态，REST detail 仍是最终产品状态来源。

## 11. 测试与验收

测试层级：

1. 路径策略单元测试：绝对路径、父目录、NUL、软链接、创建父目录和二次校验；
2. Registry 单元测试：未知工具、tool allowlist、scope、schema 和上下文不可伪造；
3. 文件工具测试：byte 上限、UTF-8、hash、只读正式知识和草稿冲突；
4. 审计与 Runtime 集成测试：事件顺序、脱敏、失败状态和重放；
5. 现有 knowledge route 回归；
6. 前端组件和 SSE 多 run 测试；
7. 后端、前端和 production build 全量回归；
8. 设置页真实浏览器自检和四档响应式验收。

R1.3 验收成立必须证明：

- 未注册工具与未授权 scope 在执行前失败；
- 路径穿越和软链接越界被拒绝；
- 授权读写只能发生在 scope 内；
- 审计和事件不包含 secret、完整正文或绝对路径；
- 设置页可运行、刷新恢复并理解安全自检结果。

## 12. Verification 与所有权材料

按仓库规范增量维护：

```text
docs/verification/r1_3_workspace_tool_security.md
docs/learning/r1-3-tool-security/
```

每个 Task 后更新 verification 的代码入口、真实测试、人工验证待办、问题与残余风险。阶段结束前刷新最终测试、浏览器步骤和成熟度边界。两类目录均不提交；合并后必须显式同步到主仓库并验证目标存在，完成前在最终汇报中提供主仓库路径。

## 13. 任务分工

- Task 1～5 涉及路径、权限、状态机和审计边界，由 Codex 实现、审阅和验收；
- 前端安全诊断在后端契约稳定后可委派 Claude Opus，Claude 只读取最小上下文；
- Codex 对外部实现执行独立 diff 审阅、自动测试和浏览器验收；
- 用户所有权练习不阻塞 R1.3 产品开发。

## 14. 成熟度边界

R1.3 完成后成熟度为“工具安全切片可人工验证”。它证明 Agent 可以安全调用受限文件工具，但不代表持久化 HITL、知识发布或真实复习 Agent 已完成。
