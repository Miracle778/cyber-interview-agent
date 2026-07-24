# Cyber Interview Agent 当前任务规划

## 当前任务：画像助手会话工作台统一与实页验收

2026-07-24 经产品追问确认，画像助手需与已反复打磨的 R2 Agent 对话体验共享布局和开发规则：会话记录与工作台分离，消息为主体，运行与依据进入右侧栏，Session/Execution/Message/Event/Artifact 状态边界清晰。

权威新增输入：

- 补充规格：`docs/superpowers/specs/2026-07-24-r3-unified-personal-profile-correction.md`
- 架构决策：`docs/superpowers/architecture-decisions/2026-07-24-unified-profile-and-source-model.md`
- 实施计划：`docs/superpowers/plans/2026-07-24-r3-unified-personal-profile.md`

纠偏目标：

```text
简历/本人补充/对话补充/系统归纳
→ 待确认或用户直接确认
→ Workspace 级统一个人画像
→ 我的画像 / 待确认 / 简历与来源 / 画像助手
→ confirmed-only 下游消费
```

当前阶段：Agent 规范、会话标题/归档 API、共享前端组件和画像助手迁移已实现。经用户逐项确认，“我的画像”已改为单主轴全宽布局、一级页签固定、子页签吸顶、紧凑职业名片和概览摘要卡；项目编辑器已改为桌面宽版固定头尾、窄屏全屏单列。1200×702 与 390×844 实页、定向测试 8 项和 TypeScript 通过。剩余任务是补齐其他响应式档位验收。R2 仍是稳定视觉基准，本切片未迁移其业务组件。

---

## 前一任务：R3 可信个人资料底座第一里程碑

目标是在现有 R2 Runtime 上交付 R3.1-R3.4：私有简历版本与 Evidence、经确认的 Claim 资料、受约束评估/对话/Action Plan，以及供后续求职目标按用途受控读取的 `ConfirmedProfileContext`。个人资料不再以发布到 Active Knowledge 作为下游使用前提。

| 阶段 | 状态 | 产出 |
|---|---|---|
| 求职目标中心产品路线 | 已确认 | `2026-07-24-job-target-centered-interview-preparation.md`；B（可信资料）→ D（岗位差距）→ C（项目深挖训练）形成因果链 |
| R3 产品与架构规格 | 路线调整完成 | `2026-07-20-r3-personal-profile-agent-design.md`；R3 收窄为可信资料底座，知识发布页面延期 |
| R3 实施计划 | 执行中 | `2026-07-20-r3-personal-profile-agent.md`，18 个 TDD Task、R3.1-R3.4 四个检查点 |
| R3.1 材料与 Evidence | Task 1-9 已完成 | schema/registry、私有存储/解析、隐藏 ingest、只读 Tool、结构化 Graph、材料/版本/Evidence API，以及 `/profile` 上传、处理阶段、版本、Evidence 与恢复 UI 已落 |
| R3.2 Claim 审核 | Task 10-11 已完成 | Claim/Proposal/冲突/删除影响后端与审核工作台已完成 |
| R3.3 评估与连续对话 | Task 12-15 核心闭环已验收 | 真实模型问答、只读 Tool、停止/刷新、结构化 Action Plan 与人工确认已通过；完整 13 场景组合复跑仍属收口门禁 |
| R3.4 受控下游查询与收口 | Task 16 完成；Task 17 核心路径完成；Task 18 进行中 | confirmed-only 查询与敏感隔离已落；最终用户指南和学习包已生成，剩余完整回归、文档门禁与扩展浏览器场景 |
| R4 求职目标与项目深挖 | 待设计 | 创建角色/JD 目标、确认岗位要求、资料证据映射、项目深挖、四类缺口、项目讲解卡和岗位准备状态 |

当前权威输入：

- 规格：`docs/superpowers/specs/2026-07-20-r3-personal-profile-agent-design.md`
- 计划：`docs/superpowers/plans/2026-07-20-r3-personal-profile-agent.md`
- 工作分支：`feature/review-agent-workspace`
- 工作树：`/Users/miracle778/Project/cyber-interview-agent-new/.worktrees/r2-complete-review-agent`

下一步：运行 R3 唯一一次最终前后端回归和文档门禁；随后集中补齐验证指南中尚未完成的扩展浏览器场景，再关闭 R3 并进入 R4 求职目标工作区。

### 2026-07-21 R2 题目整理故障增量

- 正式修复已落：GLM Thinking 显式映射、question_generation 独立输出预算、稳定分块 thread、无换行长文本硬上限。
- 自动回归与最小真实 GLM 结构化调用已通过；完整原始文档验收等待用户明确授权向外部 Provider 发送正文。
- 该增量不改变当前 R3 Task 8 的下一产品任务，也不声明 R2 整体关闭。

### 2026-07-22 R2 题目整理长任务控制验收

- 产品状态与证据：结构感知规划、单进程最多 3 并发、completed Work Item 跳过、失败/暂停/重启后原 Batch 恢复、渐进预览、实时耗时和 Trace v2 已完成自动验收；最终后端 `641 passed`、前端 `167 passed`，TypeScript 与 production build 通过。
- 成熟度边界：当前是单进程内的 bounded scheduler 和 SQLite 持久恢复，不是分布式队列；Provider 调用是至少一次语义，已提交 Work Item 具有精确一次效果。
- 产品修正：最终 reducer 现在把 Batch 推进到 `review_pending`，等待候选人工决定，不再沿用含糊的 `completed` 生成终态。
- 所有权状态：产品自动门禁与隔离浏览器暂停/刷新/恢复/终止验收已完成；真实 Provider 性能与真实材料完整运行仍待具体授权，作为 pending practice，不阻塞回到 R3。
- 下一产品任务：继续 R3 Task 8，接通材料、版本和 Evidence API。
- 非阻塞练习：按本地 verification 指南完成一次暂停→刷新→恢复→终止，并核对新 Execution ID、单调预览和 UTC/北京时间 Trace。

### 2026-07-22 R2 随手记容错整理验收

- 产品状态：Tasks 1–8 已完成；单 Seed 恢复、两次自动调用上限、内容缺陷降级/跳过、质量来源、严格发布确认、前端恢复动作与安全事件均已接通。
- 证据：综合跨层场景 1 passed；后端首次完整回归 683/684，旧短 PDF 夹具修正后受影响 7/7；前端 172/172 与 build 通过；隔离真实数据快照保留 80 discovery、22 enrichment，并恢复 66 个唯一 Seed 输出。
- 浏览器：真实失败会话完成桌面/390px 的警告与失败语义、布局和 console 验收；没有在用户材料上触发 Provider 或重放。
- 成熟度：单进程 bounded scheduler + SQLite recovery + 人工确认，不是分布式作业或自动事实核验。
- 下一产品任务：回到 R3 Task 8，接通材料、版本与 Evidence API。
- 非阻塞练习：按 verification 用一份允许发送的随手记完成暂停、恢复、单题重试与 mixed 候选确认发布。

## 前置阶段：R2 题库与 Agent 可用性补强

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
| 24. Progressive 题目整理、长任务控制与 Agent JSONL | 自动与隔离浏览器验收完成；真实 Provider 验收待具体授权 | 结构感知 planning、discovery/enrichment 最多 3 并发、可暂停/恢复/终止、渐进预览、实时耗时、同 Batch/Work Item 恢复、Trace v2；普通/修订批次按 committed candidate revision 原子完成；最终 638/167/build 通过 |

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
- R2 默认由一个 Agent 负责到底；2026-07-21 增量经用户明确确认，例外地一次性并行 writer、sectioner、work-item 三个互不重叠基础任务，根 Agent 保留共享集成、审查、验证和提交所有权，且未发生二次转派。
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
