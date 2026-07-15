# Cyber Interview Agent 当前任务规划

## 当前任务：R2 题库与 Agent 可用性补强

目标是在现有 R2 闭环上补齐失败恢复、可观察过程、候选题管理、删除生命周期、分层题库、上下文续写和可审计相似题合并。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 题库与持久轮次领域事实 | 已完成 | additive migration、catalog/round/input/mastery repository、selector、publication projection |
| 2. Agent 与长生命周期 Graph | 已完成 | 题目整理、评价/追问、报告、discussion、input resume |
| 3. API 与完整 Web 体验 | 人工浏览器验收未通过，交互模型需修订 | 现有 API/页面可运行，但题库过程不可见、复习回答阻塞、历史与创建入口混杂 |
| 4. 会话化交互修订与重新验收 | Task 1–3 已完成；Task 4 修复与重新验收中 | durable facts、题库整理会话、历史优先复习与异步评价已落；最新审阅修复通过后端 15、前端 19 个针对性测试及 build；当前 HEAD 的最终全量回归、4 宽度 UI/UX 审计与 10 场景浏览器验收待执行 |
| 5. Agent 失败恢复与运行证据 | 已完成 | failed 原会话重试、公开阶段历史、耗时/错误、上下文压缩事实 |
| 6. 候选题与题库信息架构 | 已完成 | 总结直达候选查看/编辑、topic→难度→题目分层、Markdown 阅读 |
| 7. 生命周期与上下文续写 | 已完成 | 会话/原材料软删、引用保护硬删、题目重写恢复原整理 session/thread |
| 8. 相似题合并与最终验收 | 自动验证完成，浏览器待验收 | 规范化+高置信候选归并、active 关联降级、单 reducer；276/102/build 通过 |
| 9. 整理会话 UI 与回收站补强 | 自动验证完成，浏览器待验收 | 历史优先会话页、聚焦 Agent 工作区、折叠资料提示、会话/原材料回收站与恢复入口 |

## 工作位置

- 分支：`codex/r2-complete-review-agent`
- worktree：`/private/tmp/cyber-interview-agent-r2-ui-design`
- 基线：`codex/r2-ui-design-guidance@e3d64b3`
- R2 设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 补充实施计划：`docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md`
- 总路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`

## 范围与约束

- 不修改 `docs/my_idea.md`。
- 效果图是结构参考，不是硬编码数据或逐像素验收基线。
- 必须还原一级入口、区域职责、主要操作顺序、状态显隐和 Markdown 阅读/编辑边界。
- 会话化前端实施前、实施中和最终审查必须使用 `ui-ux-pro-max`，产出设计系统、页面约束和五类 UX 验收证据，不能只在收尾换颜色。
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

当前先完成新增阶段 5–8，不使用旧的最终证据关闭 R2。执行顺序：

1. 启动本分支服务执行回收站、历史会话、聚焦会话与折叠资料提示的浏览器复核。
2. 运行一次最终全量后端/前端回归。
3. 刷新 verification/learning 与文档门禁后再进入提交/合并。

## 所有权状态

- 产品：R1/Agent Harness 已完成；R2 后端核心能力可运行，但人工浏览器验收暴露关键交互缺陷，必须完成修订后才能关闭。
- 用户学习/实践：现有 learning 七件套需在新交互稳定后刷新，用户练习待完成且不阻塞产品修订。
