# Cyber Interview Agent 当前任务规划

## 当前任务：R2 UI 设计契约补充

目标是把已确认的复习轮次与题库整理效果图转化为可实施、可测试的 R2 UI 契约，避免实现阶段只参考图片猜测交互和状态。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 视觉参考固化 | 已完成 | 两张桌面效果图进入 `docs/superpowers/assets/r2/` |
| 2. Spec UI 契约 | 已完成 | 一级导航、两类三栏布局、状态显隐、Markdown 和响应式规则 |
| 3. Implementation plan 对齐 | 已完成 | 组件、API、模型参数、测试和浏览器验收同步更新 |
| 4. 一致性复核 | 已完成 | 文档门禁 16 passed，图片、引用和 diff 检查通过 |

## 工作位置

- 分支：`codex/r2-ui-design-guidance`
- worktree：`/private/tmp/cyber-interview-agent-r2-ui-design`
- 基线：`codex/r2-plan-r8-channel-alignment@1eb08fc`
- R2 设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 总路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`

## 范围与约束

- 不修改 `docs/my_idea.md`。
- 效果图是结构参考，不是硬编码数据或逐像素验收基线。
- 必须还原一级入口、区域职责、主要操作顺序、状态显隐和 Markdown 阅读/编辑边界。
- R8 明确为微信、飞书等原生对话入口；响应式 Web 只属于 Web UI 质量，不代表 Channel。
- R8 复用同一 application service、session/checkpoint、HITL、工具权限和知识发布规则，不复制 Agent Runtime。
- R2 计划最多四个纵向任务，一个 Agent 负责到底，不创建 subagent。
- R2 必须交付可用的 Web 复习闭环，而不是只交付 Graph/API 骨架。
- 当前 R2 验收默认不配置或启动 Langfuse；Langfuse 正常/不可达场景留到后续 observability 专项。

## 验证

- R8 路线中的目标、范围、身份、消息映射、HITL、安全和验收无“移动浏览器即 Channel”的歧义。
- R2 plan 覆盖 R2 spec 各章节及 `docs/my_idea.md` 的辅助复习要求。
- 两张图片链接有效，题库候选 API 与 UI 筛选/详情能力对齐。
- 计划没有 `TBD`、`TODO` 或未定义接口；文件路径与当前仓库一致。
- `git diff --check`、计划占位符扫描和文档测试通过。

## 下一步

按 `docs/superpowers/plans/2026-07-14-r2-complete-review-agent.md` 执行 Task 1。

## 所有权状态

- 产品：R1/Agent Harness 已完成；R2 待实施。
- 用户学习/实践：待完成，不阻塞 R2。
