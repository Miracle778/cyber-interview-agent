# Cyber Interview Agent 当前任务规划

## 当前任务：R2 完整复习 Agent 实施

目标是按已确认设计交付题库整理、可恢复多题轮次、必要追问、报告、掌握度和派生讨论的完整 Web 闭环。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 题库与持久轮次领域事实 | 已完成 | additive migration、catalog/round/input/mastery repository、selector、publication projection |
| 2. Agent 与长生命周期 Graph | 已完成 | 题目整理、评价/追问、报告、discussion、input resume |
| 3. API 与完整 Web 体验 | 人工浏览器验收未通过，交互模型需修订 | 现有 API/页面可运行，但题库过程不可见、复习回答阻塞、历史与创建入口混杂 |
| 4. 会话化交互修订与重新验收 | 设计已确认，实施计划待写 | 整理会话/题目库双视图、历史优先复习、异步回答、阶段 SSE、来源关联 |

## 工作位置

- 分支：`codex/r2-complete-review-agent`
- worktree：`/private/tmp/cyber-interview-agent-r2-ui-design`
- 基线：`codex/r2-ui-design-guidance@e3d64b3`
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
- 三张图片链接有效，最新 Agent 会话概念图作为交互修订的权威结构参考。
- 计划没有 `TBD`、`TODO` 或未定义接口；文件路径与当前仓库一致。
- `git diff --check`、计划占位符扫描和文档测试通过。

## 下一步

用户复核已确认的 R2 spec 修订；通过后编写补充实施计划，在当前分支/worktree 完成会话化题库与异步复习改造，再重新执行浏览器验收。既有真实 Provider/重启证据保留，只有受交互与异步协议影响的场景重验。

## 所有权状态

- 产品：R1/Agent Harness 已完成；R2 后端核心能力可运行，但人工浏览器验收暴露关键交互缺陷，必须完成修订后才能关闭。
- 用户学习/实践：现有 learning 七件套需在新交互稳定后刷新，用户练习待完成且不阻塞产品修订。
