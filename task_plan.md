# Cyber Interview Agent 当前任务规划

## 产品目标

建设由复习、个人信息、岗位追踪、面试复盘和模拟面试等场景 Agent 组成的个人面试准备工作台。产品交付与用户学习保持双轨，学习不阻塞实现。

## 当前产品状态

| 阶段 | 状态 | 成熟度边界 |
|---|---|---|
| R0 | 可人工验证 | 单题单轮技术切片 |
| R1.1-R1.4 | 可人工验证并已合入 main | Provider、Runtime、工具安全、持久化 HITL |
| R1.5 | 可人工验证并已合入 main | 草稿分层、持久化审核发布、publication journal、active scope 与浏览器闭环 |
| R1.6 | 场景可用并已合入 main | 单题复习迁移到共享 Runtime、真实 Provider 与持久化发布闭环 |
| R2-R8 | 待开始 | 见正式产品路线 |

## 当前任务：Learning 掌握包深度治理

1. **风险档案与机器门禁 TDD（已完成）**
2. **模板和阶段关闭规范（已完成）**
3. **历史 learning 掌握包补强（已完成）**
4. **全量文档验收与 main 本地同步（已完成）**

本切片不修改产品运行行为。目标是补齐 R1.4、R1.6、Runtime Middleware、Pre-R2 和设置页掌握材料，并防止以后以标题存在性代替学习深度。

本切片的正式规范和门禁已合入 main；8 个忽略的 learning 目录与设置页 verification 已显式同步、逐文件 hash 核对并在 main 复验。

## 当前分支

- 分支：`main`
- worktree：`/Users/miracle778/Project/cyber-interview-agent-new`
- 完成合并：`main@6d26b77`，另有本次同步收尾提交
- 当前设计：`docs/superpowers/specs/2026-07-13-learning-documentation-depth-design.md`
- 当前实施：`docs/superpowers/plans/2026-07-13-learning-documentation-depth.md`
- 下一产品阶段：R2 完整复习 Agent

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
- 学习练习不阻塞当前 Pre-R2 产品切片。

## 权威资料

- 工作流：`docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- 产品路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- 当前设计：`docs/superpowers/specs/2026-07-12-pre-r2-experience-stabilization-design.md`
- 当前实施：`docs/superpowers/plans/2026-07-12-pre-r2-experience-stabilization.md`
- 历史归档：`docs/superpowers/history/2026-07-12-pre-context-optimization/`
