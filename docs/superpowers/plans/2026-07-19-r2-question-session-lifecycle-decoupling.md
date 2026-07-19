# R2 题目与 Session 生命周期解耦实施计划

## 目标

在不迁移或伪造既有开发测试数据的前提下，将题目领域资产从 Agent Session 运行容器中解耦，交付会话归档/永久删除、题目单删/显式批删/恢复，以及原会话缺失时的可恢复单题修订会话。

权威设计：

- `docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- `docs/superpowers/architecture-decisions/2026-07-19-question-session-lifecycle-decoupling.md`

## Task 1：持久化边界与迁移

- 新增 migration，令 question batch 与 source evidence 使用可空 live session reference，并保存不可变 origin session ID。
- 为 candidate 增加软删除事实；普通候选查询默认排除已删除题。
- Session 永久删除只删除 Runtime 和会话投影，不再因题目来源证据阻塞或级联题目。
- 迁移测试验证前后 candidate、draft、source link、publication 数量不变，永久删除后 live reference 为空且 origin ID 保留。

退出条件：数据库能够安全永久删除有题目关联的 Session，题目及审计事实仍可读取。

## Task 2：领域服务与 API

- 单题和批量删除复用同一个事务化领域操作；批量只接受显式 candidate IDs，并返回逐项状态。
- 已发布题删除时停用 active catalog；恢复时按发布状态重新激活。
- 增加题目回收站、恢复和 API 幂等 receipt；版本冲突按题返回 blocked，不扩大删除范围。
- Session 接口将软删除命名为归档，永久删除要求无活动 execution。

退出条件：单删、批删、重复请求、版本冲突、恢复和已发布投影均有 API 测试。

## Task 3：单题修订会话解析

- 原 Session 可用时继续原会话；归档时返回显式恢复要求；投影缺失时按需创建最小投影。
- 原 Session 不存在时创建持久 `question.revise` Session，记录 candidate、origin session 与 revision lineage。
- 修订输入由当前题目 Markdown/version、反馈/备注/退回原因、来源证据、重复关系和发布状态组装；一次只产生同一 logical question 的新版本。
- 继续复用统一 Execution Runtime、SSE、停止、重试和 publication HITL。

退出条件：原会话存在、归档、投影缺失、永久删除四条路径均有跨层测试。

## Task 4：Web 闭环与验收

- 会话列表提供归档；会话回收站提供恢复和永久删除，并明确题目不会删除。
- 题目库提供单题删除、checkbox 显式批删、危险操作确认、操作中状态及题目回收站。
- 重新整理根据服务端解析结果恢复原会话或打开新修订会话，不伪造原聊天。
- 保持当前三栏题库和会话文件卡，不另造题目状态副本；桌面与 390px 无横向溢出。

退出条件：针对性前后端测试、production build、最小浏览器 happy path、`git diff --check` 通过；完整 R2 浏览器验收仍按阶段门禁统一执行。

## 预算与边界

- 一个 Agent 负责到底，不创建 subagent。
- 开发阶段只跑受影响测试；本切片最终最多一次全量回归。
- 不删除 Vault Markdown，不修改历史复习轮次，不补齐既有缺失的整理投影测试数据。
- 不修改 `docs/my_idea.md`。
