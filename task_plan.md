# Cyber Interview Agent 当前任务规划

## 当前任务：Agent Harness 后续路线对齐

目标是在 R2 开始前，让所有仍然指导未来开发的文档与已落地的官方 Agent Harness 保持一致。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 总路线权威修正 | 已完成 | 清理旧 pipeline/R0 当前状态，更新 R2–R8 架构表达 |
| 2. 历史文档失效标记 | 已完成 | 旧 R1/Middleware spec/plan 统一声明禁止作为未来模板 |
| 3. Harness 跨阶段模板 | 已完成 | 总设计中的必答清单、任务骨架和禁止项 |
| 4. R2 正式设计 | 已完成 | 完整复习 Agent spec，不生成 implementation plan |

## 工作位置

- 分支：`codex/agent-harness-roadmap-alignment`
- worktree：`/private/tmp/cyber-interview-agent-harness-roadmap`
- 基线：`main@3435128`
- 权威总路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- Harness 基线：`docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md`
- 计划新增：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`

## 范围与约束

- 只修改正式设计、历史标记和三份短状态入口，不修改产品代码。
- 不重写已完成阶段的历史事实；只明确其不再是后续实现模板。
- R2 spec 定义目标、状态、Agent/Graph、工具、middleware、HITL、数据和验收。
- 本轮不拆 R2 Task，不创建 R2 implementation plan，不开始实现。
- 不修改 `docs/my_idea.md`。
- 单 Agent 负责到底，不创建 subagent。

## 验证

- 正式文档无 `TODO`/`TBD`/占位内容。
- 权威未来文档不再要求自研 Runtime、Gateway、Registry、Executor 或 middleware pipeline。
- 历史旧架构文档均有统一醒目标记。
- R2 spec 与总路线、现有代码能力和不兼容边界一致。
- `scripts/test_check_stage_docs.py` 及静态引用扫描通过。

## 下一步

等待用户审阅 R2 spec；用户确认后才进入 R2 implementation plan。

## 所有权状态

- 产品代码：Agent Runtime 收敛已完成，场景可用。
- 本切片：架构文档治理，不改变产品成熟度。
- 用户学习/实践：待完成，不阻塞文档对齐。
