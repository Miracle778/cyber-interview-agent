# Cyber Interview Agent 当前任务规划

## 当前任务：开发期 Runtime 数据库启动修复

目标是让重构前创建的本地测试数据库不再阻断当前开发版本启动，同时避免误删无法识别的数据。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 根因定位 | 已完成 | 确认两个 demo workspace 为已知开发期 schema，第三个无数据库 |
| 2. TDD 修复 | 已完成 | 已知 schema 备份重建，未知 schema 原样保留 |
| 3. 验证与合入 | 进行中 | 相关后端测试已通过，待实际启动数据切换与 main 复验 |

## 工作位置

- 分支：`codex/runtime-db-dev-reset`
- worktree：`/private/tmp/cyber-interview-agent-runtime-db-dev-reset`
- 基线：`main@d3817b1`
- 相关设计：`docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md`

## 范围与约束

- 只修改 Runtime 数据库初始化、对应测试和直接相关设计说明。
- 不实现数据兼容 adapter，不迁移测试记录。
- 已知开发期 schema 自动备份后重建；未知结构绝不自动删除。
- 不修改 `docs/my_idea.md`。
- 单 Agent 负责到底，不创建 subagent。

## 验证

- RED 用例必须证明现有代码会拒绝已知开发 schema。
- GREEN 用例验证备份内容、generation=2 和未知结构保留。
- 运行所有直接依赖 Runtime 数据库的仓储/API 测试。
- 在 main 上验证两个已注册 demo workspace 可初始化。

## 下一步

完成验证并合入 main，让用户直接重新启动项目。

## 所有权状态

- 产品代码：修复开发启动门禁，不改变产品成熟度。
- 用户学习/实践：待完成，不阻塞本修复。
