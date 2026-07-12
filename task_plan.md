# Cyber Interview Agent 当前任务规划

## 产品目标

建设由复习、个人信息、岗位追踪、面试复盘和模拟面试等场景 Agent 组成的个人面试准备工作台。产品交付与用户学习保持双轨，学习不阻塞实现。

## 当前产品状态

| 阶段 | 状态 | 成熟度边界 |
|---|---|---|
| R0 | 可人工验证 | 单题单轮技术切片 |
| R1.1-R1.4 | 可人工验证并已合入 main | Provider、Runtime、工具安全、持久化 HITL |
| R1.5 | 可人工验证并已合入 main | 草稿分层、持久化审核发布、publication journal、active scope 与浏览器闭环 |
| R1.6 | 实施中 | 单题复习迁移到共享 Runtime、真实 Provider 与持久化发布闭环 |
| R2-R8 | 待开始 | 见正式产品路线 |

## 当前任务：R1.6 单题复习 Runtime 集成

1. **模型网关与单题 Graph（已完成）**
   - 解析 run binding snapshot，复用现有 Provider/SecretStore。
   - 结构化评估、流式报告、session-report 草稿和发布 interrupt。
2. **Runtime 与 API 收口（进行中）**
   - 注册 `review.single/v1`、必需模型角色和工具 scope。
   - 覆盖错误恢复并移除旧 `/api/review/*` 绕过接口。
3. **持久化 Review UI（已完成）**
   - 代码、组件测试与本地 mock API 最小浏览器 happy path 已完成。
4. **验收与合并（待开始）**
   - 最终全量回归、浏览器/重启、真实 Provider、文档门禁和 main 合并。

## 当前分支

- 分支：`codex/r1-6-review-runtime-integration`
- worktree：`/private/tmp/cyber-interview-agent-r1-6`
- 基线：`main@66c26c3`

## 执行预算

- 启动必读入口合计不超过 400 行。
- 单次工具输出默认不超过 4,000 tokens。
- 针对性 TDD；跨层接通后可做一次集成回归，最终验收再做一次全量回归。
- 完整浏览器验收一次；失败只重跑受影响场景。
- 中途 Agent 交接为 0；不创建 subagent。
- 相同失败最多重复一次，第二次相同失败转根因诊断。
- 每个纵向任务 handoff 摘要不超过 10 行。

## 所有权状态

- 已掌握：尚未由用户验收。
- 待掌握：R1.1-R1.5 架构和代码链路。
- 待实践：发布请求到 Vault 写入追踪、SQLite 并发诊断。
- 学习练习不阻塞 R1.5 修正、合并或 R1.6。

## 权威资料

- 工作流：`docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- 产品路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- 当前设计：`docs/superpowers/specs/2026-07-10-r1-shared-agent-foundation-design.md`（R1.6 章节）
- 当前实施：`docs/superpowers/plans/2026-07-10-r1-6-review-integration.md`
- 历史归档：`docs/superpowers/history/2026-07-12-pre-context-optimization/`
