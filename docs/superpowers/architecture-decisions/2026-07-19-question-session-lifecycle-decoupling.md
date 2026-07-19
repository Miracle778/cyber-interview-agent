# ADR：题目生命周期与 Agent Session 解耦

- 状态：Accepted
- 决定日期：2026-07-19
- 适用阶段：R2 题库生命周期补强，后续题目生成与修订 Agent 继续遵守
- 关联设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 关联决定：`docs/superpowers/architecture-decisions/2026-07-16-unified-cancellable-execution-runtime.md`

## 背景

当前题目候选通过 question batch 关联生成它的 Agent Session。`review_question_batches.session_id` 和部分来源证据使用级联删除，因此永久删除 Session 可能一并删除 batch、未发布候选和来源关系。题目详情的“重新整理”也默认要求原整理 Session 仍可恢复。

这把两种生命周期不同的资源绑在了一起：

- Session 是运行容器，拥有消息、execution、event、checkpoint、上下文投影和运行诊断；
- 题目是长期领域资产，拥有 Markdown 版本、来源证据、发布状态、复习引用和修订历史。

用户需要归档或永久删除会话，同时继续保留题目；需要单题和批量删除题目；需要在原会话不存在时，仍能利用题目自身的完整上下文创建一次新的修订会话。

## 选择标准

- 删除 Session 不得隐式删除题目、草稿、来源证据、发布记录或复习快照；
- 题目删除不得破坏已经创建的复习轮次和审计历史；
- 原 Session 可用时，修订应继续沿用原会话上下文和 thread；
- 原 Session 不存在时，修订仍必须支持 SSE、停止、重试、刷新和重启恢复；
- 批量操作必须由服务端在明确 candidate ID 集合上校验并执行，不能由前端循环调用单题接口；
- 发布文件、HITL receipt 和题目内容的删除边界必须显式，不能由数据库 cascade 决定产品语义。

## 候选方案

### 方案 A：保留 Session 级联删除，删除前禁止存在关联题目

优点：数据库关系简单，不会产生无 Session 的 batch。

拒绝原因：用户必须为了保留题目永久保留无价值的运行历史；题目所有权继续从属于 Session；会话数量和事件数据只能增长，无法形成真实的归档与清理能力。

### 方案 B：永久删除 Session 时复制题目到一套独立归档表

优点：可以保留当前外键，同时把题目快照搬离级联范围。

拒绝原因：正常题目和归档题目形成两套查询、编辑、发布与来源模型；复制时容易丢失 draft version、source evidence、duplicate link 和 publication receipt；后续修订必须处理两套 ID，复杂度高且没有业务收益。

### 方案 C：题目作为独立领域资产，Session 只保留可空运行关联

题目、batch、draft、来源证据和发布事实独立保存；Session 关联只表示“当前仍可进入的运行容器”，另存不可变的原 Session ID 作为生成血缘。永久删除 Session 只清理运行数据。

优点：资源所有权与用户预期一致；题目管理、复习和发布不依赖历史聊天；原会话存在时仍可恢复完整上下文，不存在时可创建轻量修订会话。

代价：需要重建部分 SQLite 表的外键，增加题目删除投影、修订会话解析和更多生命周期测试。

## 决定

采用方案 C，并规定以下边界。

### 1. Session 生命周期

Session 支持两个用户操作：

1. **归档**：从默认会话列表隐藏，保留消息、execution、event、checkpoint 和恢复能力；归档会话不得启动新 execution，恢复后才能继续交互。
2. **永久删除**：禁止存在活动 execution；删除 Session 的运行数据和 `review_curation_sessions` 等会话投影，但保留题目、batch、draft、来源证据、publication receipt、active catalog 历史和复习快照。

数据库不得再通过 Session 外键级联删除题目领域事实。batch 和来源证据保存：

- 可空的 live session reference，用于判断原会话是否仍可进入；
- 不受外键级联影响的 immutable origin session ID，用于来源追溯和缺失状态展示。

永久删除后的题目显示“原生成会话已删除”，而不是伪造新会话或隐藏关联状态。

### 2. 题目删除生命周期

题目默认只提供可恢复删除，不在题目详情和批量操作中直接提供永久删除：

- candidate 增加删除事实，普通查询、会话统计和新复习选题排除已删除题；
- 已发布题删除时将 active catalog 投影停用，但保留 candidate、draft、publication 和来源证据；
- 已存在的复习轮次继续使用创建时保存的题目快照，不因题目后来删除而改变；
- Vault Markdown 不随题目删除自动移除。外部文件删除是单独、明确且可审计的操作；
- 题目回收站提供恢复，恢复后根据原 publication 状态决定是否重新激活 catalog。

单题删除与批量删除调用同一个领域服务。批量请求携带显式 candidate IDs、expected versions 和 idempotency key；服务端在一个受控事务中逐题校验，返回 `deleted / already_deleted / blocked / failed` 的逐项结果。首版只支持用户明确勾选的题目，不把“当前筛选条件”隐式解释为全库删除。

### 3. 重新整理的 Session 解析

重新整理 candidate 时按以下顺序执行：

1. 原 Agent Session 和整理投影均存在且未归档：在原 Session 创建新的 revision execution；
2. 原 Session 已归档：界面提供“恢复并重新整理”，恢复后在原 Session 执行；
3. 原 Session 存在但整理投影缺失：允许按 candidate/batch/source facts 按需重建最小投影后复用，不要求批量回填既有开发数据；
4. 原 Session 已永久删除或底层记录缺失：创建新的持久 `question.revise` Session，并记录 candidate ID、origin session ID 和 revision lineage。

`question.revise` 是轻量但正式的可恢复会话，不是进程内临时对象。它继续使用统一 Execution Runtime、middleware、SSE、停止、重试、usage 和 observability；用户可以继续追问或归档该会话。

修订上下文由题目领域事实组装，不依赖原聊天全文：

- candidate ID、当前 QuestionSnapshot 和完整 Markdown draft/version；
- 用户本次反馈、退回原因和持久备注；
- 全部 source/evidence links 及预算内原文片段；
- duplicate/similarity 信息和当前 publication 状态；
- 历史修订摘要与最近有效决定。

修订输出采用单题严格契约，只生成同一 logical question 的新 draft version，不启动多题资料整理，也不创建无关 candidate。已发布题修订后必须重新走 publication/HITL，旧发布版本在新版本批准前保持可追溯。

### 4. 状态所有权

- Session Runtime 拥有归档、消息、execution、event、checkpoint、取消和恢复；
- Question domain 拥有题目删除、版本、来源、重复关系和修订 lineage；
- Publication domain 拥有发布 receipt、Vault target 和 active catalog 投影；
- Review round 拥有创建时的题目快照，不回查已删除题来改写历史轮次；
- 前端只提交显式用户选择，不能通过隐藏列表、缺失 Session 或本地筛选推断删除范围。

## 结果

正向结果：

- 会话运行历史可独立清理，不再绑架长期题目资产；
- 题目删除、恢复、发布和复习引用拥有稳定语义；
- 原会话缺失不再阻止单题修订；
- 重写上下文更小、更明确，不需要为了一个题目恢复整个资料整理历史；
- 未来 Web、微信和飞书 Channel 可以复用同一题目删除与修订 application service。

负向结果与风险：

- SQLite 需要重建含 Session cascade 的表并验证迁移前后来源与候选数量；
- Session 永久删除后无法恢复原聊天和 checkpoint，只能从题目事实创建新修订会话；
- 已发布题软删除同时涉及 candidate 和 active catalog，必须保持事务一致；
- 批量删除存在部分失败和并发版本冲突，需要逐项 receipt 和幂等测试；
- 归档、题目回收站和 Session 回收站是两个不同入口，界面必须使用清楚的资源名称。

## 实施约束

- 不修改或批量补齐当前缺失整理投影的开发测试数据；迁移只改变未来删除的结构安全性；
- 不把题目复制到第二套归档表；
- 不让前端对批量删除逐题发请求；
- 不在删除题目时自动删除 Vault 文件；
- 不让 `question.revise` 绕过统一 Execution Runtime 或 publication HITL；
- 不把完整原始资料、全部聊天和内部 Chain of Thought 无界注入修订上下文。

## 重新评估条件

满足任一条件时重新评估：

- 产品需要题目永久擦除或合规级数据销毁，并要求同步删除 Vault、备份和审计记录；
- 多 workspace 共享同一道 logical question，需要把 candidate 提升为跨 workspace 的独立 question aggregate；
- 修订会话大量出现且用户从不继续交互，需要评估完成后自动归档策略；
- 批量删除需要支持“当前筛选下全部 N 道”，必须引入服务端 selection snapshot，而不是扩展客户端勾选列表；
- 外部 Channel 需要管理员批量治理题库，权限模型需要区分题目编辑、删除、恢复和 Vault 文件删除。
