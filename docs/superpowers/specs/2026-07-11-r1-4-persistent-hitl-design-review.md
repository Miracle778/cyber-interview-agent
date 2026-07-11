# R1.4 持久化 HITL 设计复核

## 1. 复核结论

R1 总规格中的核心决策保持不变：pending action 存在 Workspace Runtime SQLite，Graph 使用 LangGraph `interrupt` 暂停，action 通过 version 和 idempotency key 解决，并以原 session、原 run 和原 checkpoint 恢复。

既有实施计划可以继续执行，但必须适配 R1.2/R1.3 已落地的 Workspace Runtime、`GraphBuildContext` 和设置页诊断入口。以下修订不改变产品需求，只补齐当前代码中的依赖方向、浏览器闭环和并发边界。

## 2. 当前基线

- `AgentRuntime` 按 Workspace 延迟创建独立 connection、repository、event stream、checkpointer 和 `RunManager`。
- run/session 已包含 `waiting_for_approval` 状态，活动 run 唯一索引也覆盖该状态。
- Graph factory 只接收 `GraphBuildContext`，不能从节点直接获取全局 service。
- LangGraph `ainvoke()` 遇到 `interrupt()` 时正常返回带 `__interrupt__` 的结果，不抛业务异常。
- 设置页已有 Runtime 和工具安全确定性诊断，R1.4 需要沿用同一人工验证方式。

## 3. 修订后的依赖方向

### 3.1 Workspace 级 HITL 上下文

每个 `_WorkspaceRuntime` 增加自己的 `PendingActionRepository` 和 `HitlService`，与该 Workspace 的 `runtime.sqlite`、`EventStream` 和 `RunManager` 共用生命周期。跨 Workspace 的 action 定位仍由 `AgentRuntime` 负责，API 不接触数据库连接。

`PendingActionRepository` 只保存 Workspace root/database path，每次操作使用独立 `aiosqlite` 连接、`busy_timeout` 和显式事务。它不能复用 Runtime 的同步 connection，因为 Graph 节点创建 action 时 checkpointer 可能正在同库事务中；同步写会阻塞 event loop 并重现 R1.3 已修复的 SQLite 自锁。

### 3.2 Graph 注入

`GraphBuildContext` 增加窄接口 `request_action`。Runtime 用闭包绑定 workspace、session、run、graph 和权限上下文；Graph 只传 action type、payload、preview、editable fields 和确定性 key，不能从 state 伪造执行身份，也不能持有 `HitlService`、Runtime repository 或路径对象。

创建操作只先持久化 action。`RunManager` 识别 `__interrupt__` 后，按以下顺序完成暂停：

1. 验证 interrupt payload 只包含已持久化的 action id；
2. 将 run/session 从 `running` 转为 `waiting_for_approval`；
3. 发布脱敏 `hitl.required` 事件；
4. 不写 assistant message，不把 run 标为 completed。

### 3.3 解决与恢复

action 终态和 resolution receipt 在单个 `BEGIN IMMEDIATE` 事务内提交。receipt 同时保存 decision payload、`delivery_status`、attempt count、delivered time 和稳定错误码。提交后才发布 `hitl.resolved`，再由 `RunManager` 使用 `Command(resume=typed_decision)` 恢复原 run。

相同 resolution idempotency key 返回原 receipt。若上一次请求已提交 action、但在启动 Graph 前中断，重试会再次尝试恢复；run 的 `waiting_for_approval -> running` 条件更新保证只会创建一个执行任务。不同 key 处理已解决 action 返回 `action_already_resolved`，旧 version 返回 `action_version_conflict`。

服务启动时执行 reconciliation：

- receipt 未 delivered 且 run 仍 waiting/interrupted：重新投递同一 typed decision；
- run 已 completed/cancelled：只补齐 receipt delivery 终态，不重放 Graph；
- 上次在 delivering 窗口崩溃：增加 attempt，并通过 run 条件转换与原 checkpoint 恢复；
- delivery 失败只记录稳定错误码，不保存内部异常正文。

R1.4 保证 action 决定和恢复投递可重试；真正有副作用的 R1.5 handler 仍必须使用 operation id/idempotency key，不能依赖进程内 exactly-once。

取消 waiting run 时同时把仍 pending 的 action 转为 `cancelled`。服务启动恢复只中断 `running` run，`waiting_for_approval` 和 pending action 保持原状。

## 4. 确定性人工验证 Graph

新增 `test.approval` version 1：

1. 输入一段摘要；
2. 使用 `${run_id}:test.approval` 创建确定性 action；
3. 调用 `interrupt({actionId})`；
4. 批准、编辑批准或拒绝后，根据 decision 生成确定性结果并完成原 run。

该 Graph 不调用 Provider、不写 Vault、不提前实现 R1.5。设置页 ActionCenter 提供“运行确认测试”，并展示 pending action 的列表、详情、可编辑字段、批准和拒绝入口。这样用户无需 curl 即可验证暂停、刷新、重启和恢复。

## 5. 数据与脱敏

- `payload_json` 保存执行需要的数据，`preview_json` 保存前端可展示的结构化摘要。
- action 明确保存 `editable_fields_json`，前端只允许编辑这些字段。
- API、SSE 和日志不返回 checkpoint、绝对 Workspace 路径、secret、请求头或内部异常。
- R1.4 的 handler 只验证 action type 和编辑字段；知识草稿版本保存与发布副作用留给 R1.5。

## 6. 验收补充

除原计划验收外，还必须证明：

- 设置页可以创建真实 pending action，而不是只展示测试夹具；
- session detail 返回当前 pending action 摘要；
- waiting action 在后端重启和浏览器刷新后仍可处理；
- 相同幂等键重试不会二次恢复，两个不同决定并发时只有一个成功；
- 取消 waiting run 会关闭 pending action；
- R1.4 不写入 Vault，也不声称知识发布已经完成。
