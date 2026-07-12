# R1.6 单题复习 Runtime 集成计划

**目标：** 将现有单题复习迁移到真实 Provider、持久化 Agent Runtime/SSE、受限工具和批准后 Vault 发布；不实现 R2 多题轮次。

**架构：** 注册 `review.single`/`1`。Run 创建时保存 Workspace 模型用途绑定快照；执行时由 resolver 将稳定模型 ID 解析为临时调用凭据，再通过窄 `ChatModelGateway` 注入 Graph。报告先保存为 knowledge draft，再通过 `knowledge.publish` HITL action 发布。

## 全局约束

- 单一 Run binding snapshot 是模型选择真相；恢复时不得静默切换模型。
- 密钥、Provider 原始错误正文和隐藏推理不得进入 run、checkpoint、event 或日志。
- 必需角色固定为 `answer_evaluation`、`report_summarization`。
- Graph 只能使用复习 source/draft 与只读 active knowledge scope。
- 发布必须停在 HITL；旧 `/api/review/run`、`/api/review/reports/confirm` 必须移除。
- 自动测试使用 fake gateway；真实 Provider 只进入最终人工验收。
- 每个任务仅跑受影响测试；全量后端/前端回归最多各两次，完整浏览器验收一次。

## Task 1：模型绑定 Gateway 与单题 Graph

**产出：** `ResolvedModelBinding`、稳定 Provider 错误、`ChatModelGateway`，以及 `review.single`/`1` contracts/nodes/definition。

- [x] RED：gateway 固定使用快照模型；结构化校验、流式文本和 secret/auth/model/rate-limit/timeout 错误均有稳定行为。
- [x] RED：单题输入依次完成回答评估、报告生成、draft 创建和 publication action interrupt。
- [x] Runtime 建图上下文注入按角色调用接口；建图前校验必需绑定，但不持久化 resolved secret。
- [x] 针对性测试通过：`test_chat_gateway.py`、`test_review_definition.py`、相关 graph/run-manager 测试。

## Task 2：Runtime 注册、恢复与移除绕过 API

**产出：** 应用组合 `review.single`，Provider 错误映射到稳定 run failure，通用 Agent/HITL/Draft API 成为唯一入口。

- [x] 注册 required roles、allowed tools/scopes，并用真实 runtime repository/event stream/checkpointer 验证运行。
- [x] 验证等待批准、拒绝、批准、进程重启恢复和 binding snapshot 不变。
- [x] 移除旧 review run/confirm 路由及其后端调用方。
- [x] 针对性测试通过：runtime integration、provider errors、review routes、restart。

## Task 3：持久化 Review UI 与 SSE/HITL 闭环

**产出：** session list、conversation、SSE 恢复、draft/publication 状态，以及批准/拒绝交互。

- [x] UI 使用通用 session/run/event/action/draft API，不保留 AppShell 本地报告真相。
- [x] 刷新后恢复 session、消息、latest run、pending action；断线按 Last-Event-ID 补流。
- [x] 显示模型/Provider 可操作错误、draft、target path、publication state、index-stale。
- [x] 前端针对性测试通过后立即跑一条最小浏览器 happy path，再进入最终文档（本地 mock API；不替代最终真实后端验收）。

## Task 4：最终验收、文档与合并

**产出：** 自动回归、真实 Provider 与浏览器证据、最终 verification 用户指南、七件 learning pack。

- [ ] 增加真实前后端发布闭环 E2E；完整验收覆盖桌面、移动、刷新、重启、拒绝与重复发布。
- [ ] OpenAI-compatible 与 Anthropic-compatible 至少各完成一次人工连接/调用证据；缺少外部凭据时明确标为外部阻塞，不伪造通过。
- [ ] 最终只跑一次全量 backend、frontend test/build 和文档门禁；数字来自最新命令。
- [ ] 更新 `docs/verification/r1-6.md` 和 `docs/learning/r1-6/`，与 R1.5 对比并运行：

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r1-6.md \
  --learning docs/learning/r1-6/ \
  --plan docs/superpowers/plans/2026-07-10-r1-6-review-integration.md
```

## 执行预算

- 启动入口合计不超过 400 行；单次工具返回默认不超过约 4,000 tokens。
- 全量后端、前端 test/build 各不超过 2 次；完整浏览器验收 1 次。
- 中途 Agent 交接 0；无变化失败最多重试 2 次。
- 每完成一个任务，只写不超过 10 行 handoff 到 `progress.md`。

## 完成定义

- Product：单题复习从真实 Provider 到 Runtime/SSE、draft、HITL、Vault 构成唯一闭环，旧绕过 API 不存在。
- Maturity：仍是单题、单 run；多题编排、队列与长期自治属于 R2+。
- Ownership：verification 与 learning pack 通过机器门禁；用户练习作为非阻塞 understanding debt 记录。
