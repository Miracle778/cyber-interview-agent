# Agent Runtime 框架收敛进度

## 2026-07-13：开发期 Runtime 数据库启动修复

- 复现 `IncompatibleRuntimeDatabaseError`，确认两个已注册 demo workspace 命中重构前开发 schema。
- RED：已知 schema 备份重建与未知 schema 中性错误两项用例按预期失败。
- GREEN：实现已知开发 schema 备份/重建，异常改为 `RuntimeDatabaseSchemaError`；针对性用例 4 passed。
- 相关仓储、HITL、草稿、知识和审计测试 33 passed。
- 最终后端回归 196 passed，文档门禁 16 passed，diff check 与旧错误文案扫描通过。
- 修复提交 `396f607` 已 fast-forward 合入 main；真实 FastAPI 生命周期到达 `Application startup complete`，随后仅因测试沙箱禁止绑定 8011 端口而正常关闭。
- demo 与 demo1 的当前数据库均为 generation 2，原测试 schema 分别保存在 `runtime.development-backup.sqlite`；demo2 未创建过 Runtime 数据库。

## 2026-07-13：Agent Harness 后续路线对齐启动

- 用户确认执行总路线修正、历史文档标记、跨阶段 Harness 模板和 R2 正式设计四项工作。
- 明确本轮不拆 R2 implementation tasks，也不开始产品实现。
- 从 `main@3435128` 创建 `codex/agent-harness-roadmap-alignment` 隔离 worktree。
- 文档门禁基线：`scripts/test_check_stage_docs.py` 16 passed。
- 扫描发现 R2 的 Middleware 1.0 引用、路线图 R0 当前状态和多份历史旧 Harness 计划仍可能误导未来实现。
- 总路线已改为官方 Harness 当前状态，补充十项阶段设计清单、四项纵向任务骨架和八项禁止项；R2 旧 Middleware 1.0 表述及 R0 当前下一步已修正。
- 16 份旧 R1/Pre-R2 spec/plan 与 Middleware task-details 已加统一“历史实现、禁止作为后续模板”标记；Middleware 1.0 spec 的既有失效提示同步强化。
- 错误记录：首次给 Pre-R2 文档加标记时假设了错误标题，补丁校验失败 1 次；读取真实标题后精确修正，未发生部分写入。
- R2 正式设计已完成：定义长生命周期轮次 Graph、领域输入 interrupt、角色 Agent、状态所有权、middleware、API、恢复、安全与验收；未创建 implementation plan。
- 收尾复核将“暂停”消歧为离开页面后继续，并将 Provider adapter 限定为配置/连通性适配；Agent 调用继续消费标准 `BaseChatModel`。
- 新鲜验证：`scripts/test_check_stage_docs.py` 为 16 passed；静态扫描未发现占位符、缺失历史警示或误改 `docs/my_idea.md`。

## 2026-07-13：设计与前三个纵向任务

- 用户确认测试数据可丢弃并选择不兼容重写；归档 tag 指向 `main@8e1b500`。
- Task 1 提交 `adfea9f`：官方 Agent 核心、直接模型解析、review Agent/Graph。
- Task 2 提交 `7a6f8cc`、`76c979a`：标准工具、ToolPolicy、官方 HITL、显式 publication。
- Task 3 提交 `92857a7`：官方 middleware、usage/title/summary/no-progress/observability 与原生 stream 投影。

## 2026-07-13：Task 4 实现

- 新建 application services、fresh runtime schema、Workspace checkpointer 与 observability infrastructure。
- FastAPI 和前端切到 session/execution/action/event 新资源；删除旧 Runtime、gateway、registry/executor、pipeline 与对应实现型测试。
- 修复 draft pending 状态、SSE 旧错误清理、同连接事件写入、restart/cancel 和 ToolStrategy 兼容。
- 角色 Agent 改用独立派生 thread；官方 summary 在第 11 次真实 execution 触发。

## 2026-07-13：验收

- 最小和完整浏览器验收完成：approve/reject、刷新、重复决定、重启恢复、桌面/375px、Vault path。
- 真实 Provider 验收完成：OpenAI-compatible 结构化评价与 Anthropic-compatible 流式报告。
- 不可连接 OTLP endpoint 下执行仍到达等待审批，证明 observability fail-open。
- 最终回归：后端 `195 passed`；前端 `76 passed`；`npm run build`（含 `tsc`）通过。
- 旧 E2E 契约已更新；静态扫描不再发现旧产品 API 名称。
- verification 与 `foundation` learning 七件套已生成，文档门禁通过。
- 最终实现提交：`4f6aabb refactor(agent): complete runtime framework convergence`。

## 当前下一步

1. 用户审阅 R2 正式设计；确认后再编写 implementation plan。
2. 用户并行完成本阶段 ownership 练习。

## 2026-07-13：合入 main

- `codex/agent-runtime-framework-convergence` 已 fast-forward 合入 `main@9116dff`。
- verification 与 learning 七件套已显式同步；目录 diff 和 verification SHA-256 一致。
- main 合并后复验：后端 `195 passed`，前端 `76 passed`，`npm run build` 通过。
- 文档门禁通过，旧 Runtime 抽象扫描零匹配；产品切片关闭。
