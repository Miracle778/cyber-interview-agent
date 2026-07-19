# Cyber Interview Agent 当前任务规划

## 当前任务：R2 题库与 Agent 可用性补强

目标是在现有 R2 闭环上补齐失败恢复、可观察过程、候选题管理、删除生命周期、分层题库、上下文续写和可审计相似题合并。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 题库与持久轮次领域事实 | 已完成 | additive migration、catalog/round/input/mastery repository、selector、publication projection |
| 2. Agent 与长生命周期 Graph | 已完成 | 题目整理、评价/追问、报告、discussion、input resume |
| 3. API 与完整 Web 体验 | 人工浏览器验收未通过，交互模型需修订 | 现有 API/页面可运行，但题库过程不可见、复习回答阻塞、历史与创建入口混杂 |
| 4. 会话化交互修订与重新验收 | Task 1–4 实现与自动门禁完成；真实模型浏览器验收待补 | 可取消 execution、SSE 临时消息、模型选择、停止/重试、批量预检与安全重试已落；最终 319/113/build 通过，桌面与 390px 无模型失败态已验收；真实模型流式/停止、重启恢复和批量部分成功浏览器证据仍待配置 Provider 后完成 |
| 5. Agent 失败恢复与运行证据 | 已完成 | failed 原会话重试、公开阶段历史、耗时/错误、上下文压缩事实 |
| 6. 候选题与题库信息架构 | 已完成 | 总结直达候选查看/编辑、topic→难度→题目分层、Markdown 阅读 |
| 7. 生命周期与上下文续写 | 已完成 | 会话/原材料软删、引用保护硬删、题目重写恢复原整理 session/thread |
| 8. 相似题合并与最终验收 | 自动验证完成，浏览器待验收 | 规范化+高置信候选归并、active 关联降级、单 reducer；276/102/build 通过 |
| 9. 整理会话 UI 与回收站补强 | 自动验证完成，浏览器待验收 | 历史优先会话页、聚焦 Agent 工作区、折叠资料提示、会话/原材料回收站与恢复入口 |
| 10. 生成文件交互与自由意图 | 实现完成，浏览器待验收 | 文件卡默认 3 条/有界展开、右栏 Markdown 详情、单题发布、持久备注、结构化意图 Agent |
| 11. Agent 上下文组装与命令解释收敛 | 已完成 | 通用 token-budget ContextAssembler、持久领域焦点、确定性命令优先、一次性结构化 classifier；301/109/build 与浏览器/重启验收通过 |
| 12. 可取消流式执行、模型切换与批量发布 | 实现与自动验证已完成，完整浏览器验收待 Provider | 整理命令接统一 Execution Runtime、服务端停止/恢复、execution 模型快照、真实 SSE、候选题安全一键发布；普通问答绕过 classifier，溢出摘要移到首个 delta 之后 |
| 13. 题目与 Session 生命周期解耦 | 业务实现与最小浏览器验收完成，待并入 R2 最终完整验收 | 会话归档/永久删除不级联题目、题目单删/批删/回收站、原会话缺失时创建 `question.revise` 修订会话 |
| 14. 逻辑题目归组与重复发布门禁 | 实现与桌面最小视觉验收完成 | 目录/筛选按逻辑题计数、版本可追溯、等价题不得重复 active |
| 15. 唯一入库版与更新入库版 | 实现与自动验证完成，真实数据浏览器验收待补 | 稳定 question ID、事务化 active 指针切换、乐观并发保护、历史版本与冻结轮次保留 |
| 16. 复习历史、失败恢复与结果回放 | 实现与本机浏览器验收完成 | 跳过追问状态机修复、失败 checkpoint 恢复、终态页面、历史统计、报告/回放双视图 |
| 17. 回放讨论、复习归档与统计下钻 | 实现与本机浏览器验收完成 | 同款聊天回放、异步深入讨论、复习归档恢复、数字与条目同源 |
| 18. 整理会话题目统计口径统一 | 实现与本机浏览器验收完成 | 主页按逻辑题目计数，题目总数/已发布与题目库下钻条目一致 |
| 19. 深入讨论会话闭环修正 | 实现与本机浏览器验收完成 | 点击只准备/恢复会话，补齐作答上下文、持久关联、SSE 发送、停止/重试与恢复入口 |
| 20. 深入讨论工作台体验补全 | 实现与自动验证完成，真实数据浏览器待复核 | 聊天主区与上下文侧栏重排、模型/思考强度、运行事实、消息操作及终态纠正 |
| 21. Agent 会话视觉与运行事实统一 | 实现与自动验证完成，待重启后实页复核 | 深入讨论复用题库整理 Dock、运行详情和真实上下文 Token 进度 |
| 22. 复习 Agent 工作台比例与组件统一 | 实现与自动验证完成，实页视觉待复核 | 深入讨论与普通复习互斥渲染、工作台填满可用视口、统一 Dock 与上下文进度侧栏 |
| 23. Agent 代码结构整理第一阶段 | 已完成 | 显式 Agent/Middleware 模块命名、版本化 Prompt、共享 runnable 协议与 thread 配置；不改变 API、数据库、Graph 或 SSE 行为 |

## 工作位置

- 分支：`feature/review-agent-workspace`
- worktree：`/Users/miracle778/Project/cyber-interview-agent-new/.worktrees/r2-complete-review-agent`
- 基线：`codex/r2-ui-design-guidance@e3d64b3`
- R2 设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 补充实施计划：`docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md`
- 当前补强设计：`docs/superpowers/specs/2026-07-16-r2-cancellable-streaming-execution-design.md`
- 当前补强计划：`docs/superpowers/plans/2026-07-16-r2-cancellable-streaming-execution.md`
- 架构选型：`docs/superpowers/architecture-decisions/2026-07-16-unified-cancellable-execution-runtime.md`
- 题目生命周期选型：`docs/superpowers/architecture-decisions/2026-07-19-question-session-lifecycle-decoupling.md`
- 题目生命周期计划：`docs/superpowers/plans/2026-07-19-r2-question-session-lifecycle-decoupling.md`
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

阶段 12 的实现与自动门禁已完成，但不使用自动测试替代真实模型浏览器证据。接下来的执行顺序：

1. 在已配置健康 Provider 的环境完成发送→流式→停止→刷新/重启→重试，以及批量发布停止/重试的浏览器验收。
2. 接回阶段 8–10 和阶段 13 的完整 R2 浏览器场景，补测真实题目删除/恢复、会话永久删除与修订 SSE，记录 execution/event 标识。
3. 刷新 verification/learning 七件套并运行文档门禁；关闭 R2 后进入下一产品阶段。

## 所有权状态

- 产品：R1/Agent Harness 已完成；R2 后端核心能力可运行，但人工浏览器验收暴露关键交互缺陷，必须完成修订后才能关闭。
- 用户学习/实践：现有 learning 七件套需在新交互稳定后刷新，用户练习待完成且不阻塞产品修订。
