# Agent Runtime 框架收敛进度

## 2026-07-16：题匠输入 Dock 重构

- 用户审阅三张视觉方案后选择第 2 版紧凑聊天 Dock。
- 保留自由输入、Enter 发送、Shift+Enter 换行、模型/思考强度切换以及发送/停止行为；两个设置收进单一胶囊，输入框获得完整宽度。
- 新增紧凑设置交互测试；`CurationConversation` 与 `QuestionCatalog` 共 11 tests passed，production build 通过，仅保留既有主 chunk 体积 warning。
- 本机 5174 真实页面完成 1280×720 默认/输入/设置展开和 390×844 响应式检查；无横向溢出，浏览器控制台 warning/error 为 0。
- 视觉对比记录更新到根目录 `design-qa.md`，最新结果为 `passed`。

## 2026-07-16：R2 可取消流式执行设计

- 用户确认停止只取消当前 execution，保留用户消息，半成品 assistant 内容不进入正式上下文。
- 用户确认模型选择采用会话偏好 + 单次 execution 快照；运行中切换只影响下一次发送。
- 用户确认一键发布只处理待发布且建议确认项，逐题幂等，允许部分成功、停止和失败项重试。
- 选用统一 Execution Runtime，拒绝前端假取消与当前阶段整体 ReAct 重写。
- 正式设计提交 `69c1d29`，架构选型提交 `9f2be5c`。
- 四 Task 实施计划已完成自审；继续由一个 Agent 在现有 R2 worktree 端到端执行，不创建 subagent。
- Task 1 完成：migration 10 增加 execution 配置、持久化取消请求、命令关联/偏好和批量发布表。
- Runtime 新增通用 domain handler、cancelling 事件与关键区；用户停止和 graceful shutdown 均不会切断单题事务。
- RED 为 7 个预期失败；GREEN 覆盖运行时、审批和复习恢复共 `29 passed`，仅保留既有 Starlette 弃用警告。

## 2026-07-15：Agent 上下文组装设计

- 已提交上一批时区、耗时、Enter/Shift+Enter 与临时最近 8 条指代修复：`78e8eec`；针对性后端 10、前端 8 项测试和 build 通过。
- 用户确认后续采用“通用 ContextAssembler + 领域记忆投影”，先迁移题库整理命令链路，不一次重写全部 R2 Agent。
- 用户确认不建立长期 Intent Agent；命令解释收敛为确定性 parser 优先、一次性 structured classifier 兜底，副作用继续由领域服务执行。
- 用户确认不采用单次自由 ReAct 直接执行题库副作用；命令链路固定为 `Plan -> Validate -> Execute`，ReAct 只保留给探索型只读或受限任务。
- 正式设计、独立架构选型记录与后续 ADR 询问规则已起草，等待用户文档审阅后再编写 implementation plan。
- 用户已通过书面设计；四 Task 实施计划已完成自检，采用当前会话 inline 执行，不创建新 worktree 或 subagent。
- Task 1：新增通用 token-budget ContextAssembler，并分离 Agent execution name/model role；RED 后 GREEN，`test_context_assembly.py + test_agent_factory.py` 共 13 passed。
- Task 2：新增 migration 9、`review_curation_context` CAS 投影和解析前 receipt lookup；RED 4 failed 后 GREEN，migration/repository 共 18 passed。

## 2026-07-15：R2 题库与 Agent 可用性补强启动

- 用户提出 7 项新增要求：失败重试与运行证据、整理上下文压缩、候选查看编辑、会话/原材料删除、题库分层、重写恢复原会话、相似题合并与 subagent 边界。
- 继续使用 `codex/r2-complete-review-agent` worktree，不切分支、不创建开发 subagent。
- 采用四个纵向阶段：运行恢复、候选与题库、生命周期与续写、合并与验收。
- 初步安全边界：只展示可公开阶段而非 Chain of Thought；默认软删；硬删受活动 execution 和引用完整性约束；并行合并 worker 只产出结构化建议，由单一 reducer 提交。
- 第一轮代码扫描确认候选详情/编辑能力已存在，但页面信息架构和 session-bound rewrite 未接通；删除生命周期尚无持久字段。
- 第二轮确认整理 Agent 已接官方上下文压缩（24→10），但未投影到 UI；execution 已有计时/错误事实，可直接扩展资源并实现 retry。
- 确认现有“合并”仅为同批题干完全相等去重，不满足跨来源语义合并，需新增 merge contract/reducer。
- RED：curation 运行证据与 retry API 测试按预期 2 failed，缺少 `executionStartedAt`/`executionErrorCode` 字段和 retry 路由。
- 环境诊断：当前 worktree 没有 `backend/.venv`，改用主仓库锁定依赖的 `.venv/bin/python` 并保持 cwd 在当前 worktree；不重复尝试缺失路径。
- 阶段 5 完成：curation resource 投影 execution 起止时间、错误码/消息和 context compacted；failed 会话可在原 session/thread 重试，前端显示公开阶段历史、耗时与重试入口，不暴露 Chain of Thought。
- 阶段 6 完成：会话总结可直达候选详情；候选继续支持渲染、原文、编辑与保存；题目列表改为 topic→难度→题目层级。
- 阶段 7 完成：migration 006 增加 session/source `deleted_at`；默认软删保留历史、文件和证据，硬删拒绝活动 execution 或题目/整理引用；候选重写追加到原 curation session 并复用稳定 role thread。
- 阶段 8 核心完成：相似题先做 Unicode/标点/问句套话规范化，再在 topic 相交约束下计算序列/二元组相似度；会话内高置信候选由单 reducer 合并来源、关键点、追问，active catalog 只建立疑似关联。可选 subagent 仅作为只读结构化判断 worker，不获数据库写权限。
- 新鲜针对性证据：后端 37 passed；前端 14 passed；`tsc --noEmit` 与 `git diff --check` 通过。尚未运行本次最终全量回归、build 或浏览器验收。
- 最终全量第一次：后端 `276 passed`；前端 `101 passed, 1 failed`，失败是旧测试仍查找已改名的“发送回答”按钮。只修改失败测试并单文件 `1 passed`。
- 第二次/最终前端全量 `102 passed`；production build 成功，保留约 `566 kB` 主 chunk 警告。浏览器 skill 已读取，但本次会话缺少其必需的控制接口，未执行也未宣称新增浏览器验收通过。


## 2026-07-15：R2 Claude 修复审阅问题修正

- 阻止 R2 内部 Graph input 自动写成用户 text；curation resource 同时过滤旧数据库中无 typed payload 的内部 JSON，真实用户命令仍按 `resourceId` 保留。
- `SessionMessage` 改为按 `messageKind/payload` 渲染显式 question card，删除文件头和长度启发式。
- 整理工作台改为对话 DOM 优先；900–1199px 两栏、1200px 以上三栏、窄屏单栏，避免 1024px 主侧栏叠加导致横向溢出。
- 修正活动复习轮次“已完成”误导文案，并增加组件测试。
- 新鲜验证：后端针对性 15 passed；前端针对性 19 passed；`npm run build` 通过（保留既有 500 kB chunk warning）；`cafca31` 的 270/94 仅作为历史基线，不再冒充当前 HEAD 最终结果。

## 2026-07-14：R2 Task 4（Claude 接手自动验证与文档）

- Codex 额度用完，Claude 接手 Task 4 的自动验证与文档部分；浏览器审计交用户执行。
- 修复过时测试 `App.test.tsx`：redesign 改 history-first 后，旧测试仍期望 ReviewSetup 默认可见，改为先验证 ReviewLanding（“复习历史”heading + “创建复习”按钮 + 空状态），点“创建复习”再验证 ReviewSetup（“创建复习轮次”heading + “题量不足”文案）。提交 `8028416`。
- 全量回归：后端 270 passed，前端 94 passed（较 Task 3 的 84 增加 10，含修复的 App 测试），tsc OK，build OK。
- 定向集成/重启测试（curation session API / async answer / restart / review routes）：11 passed。
- verification 文档刷新：自动验证数字更新为 270/94，补 Task 4 测试修复说明，人工验证节补 4 宽度 UI/UX 审计清单 + 10 场景浏览器验收清单（交用户执行）。
- 文档门禁通过（verification + learning 七件套 + redesign plan）。
- 待用户执行：Step 1（375/768/1024/1440 四宽度 UI/UX 审计）+ Step 4（10 个浏览器/重启验收场景）。已知待修：左侧轮次列表 `waiting_for_input` 文案误写为“已完成”。

## 2026-07-14：R2 会话化交互 Task 3

- 复习入口改为 history-first；创建面板显式打开，进入轮次后保持历史/对话/运行状态三栏，页面不再自动进入最新轮次。
- 回答接口改为原子接受后返回 `202` receipt；后台从同一 LangGraph checkpoint 评价，SSE 投影 answer accepted/evaluation started/completed/failed，事件不含回答、参考答案或评价正文。
- 增加 durable 评价重试 receipt、失败保答、幂等重试与启动恢复；同一重试 key 在评价完成后仍返回原回执，异常原文不进入事件或日志。
- 后端针对性 `21 passed`；前端针对性 `17 passed`；`tsc --noEmit` 与 `git diff --check` 通过。未运行本阶段最终全量回归或 build。
- 无 Langfuse 的最小真实浏览器路径通过：round `cf712f97-0dcf-4ede-9513-065fa1bf6513`、session `135df4f0-2123-408d-b6ea-c2314078ee11`；回答气泡约 282ms 出现，评价卡约 56.4s 完成，刷新后重新进入同一轮次可恢复回答、评价与追问。
- 浏览器发现左侧历史的进行中轮次误显示“已完成”；留到 Task 4 最终 UI/UX 审计修复，不将本次最小路径表述为完整浏览器验收。

## 2026-07-14：R2 人工浏览器反馈与会话化交互修订

- 用户在 R2 worktree 启动真实页面后确认现有交互不合格：题库只显示批次数字、看不到 Agent 过程；复习默认混入创建态，回答请求同步等待 LLM，缺少即时用户消息和评价阶段。
- 已确认题库以每次选择的 source 集合创建独立 session；重复来源提示但不禁止；会话内相似题合并并维护 question-source-evidence 关联。
- 已确认题库采用“整理会话/题目库”双视图，复习采用历史首页、显式创建按钮、多个未完成轮次与聊天式异步回答。
- 已确认受约束自然语言命令，明确确认消息本身作为 HITL receipt；复习评价使用阶段 SSE + 校验后完整卡片，只有 discussion 使用文本 delta，不输出 Chain of Thought。
- 新 Agent 会话概念图已保存到 `docs/superpowers/assets/r2/agent-session-redesign-reference.png`，正式 R2 spec 已按架构、API、状态、失败和验收边界修订；尚未开始业务代码修改。
- 用户追加前端质量要求：实施前、实施中和最终审查均使用 `ui-ux-pro-max`。检索后确定 `AI-native + data-dense dashboard + modern dark`，基线为 variance 4 / motion 3 / density 8，并明确拒绝不适合应用工作台的 Landing Page、紫粉营销和重玻璃拟态建议。
- 用户已确认正式修订规格；新增 `docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md`，按 durable session facts、题库整理会话、异步复习会话、最终 UI/UX/验收四个纵向任务执行。计划已对齐 spec 状态名、202 answer receipt、原子接收、重启恢复、安全 SSE 和一次最终全量回归预算，尚未修改业务代码。
- 会话化修订 Task 1 已实现：migration 003、结构化 timeline message、curation session/summary/source-link facts、attempt evaluation 状态及原子 answer acceptance；针对性测试 `24 passed`，compile 与 diff check 通过。计划中 verification/learning 路径已修正为仓库现有的 `r2-complete-review-agent` 命名。
- 会话化修订 Task 2 已实现：新增持久 command receipt migration 004、source-scoped curation session API、受约束命令/澄清/幂等、显式确认直接发布、跨来源相似题证据合并，以及“整理会话/题目库”双视图。
- Task 2 前端默认展示会话列表、对话/总结/命令输入和运行状态三栏；AI 整理改为选源弹窗，重复/进行中资料只提示不阻断；题目库保留候选编辑和真实 pending publication ActionCenter。
- `ui-ux-pro-max` 实施门禁采用 data-dense Agent workbench、语义 token、44px 交互目标和 150–300ms 动效，拒绝 Landing Page、紫粉营销和重玻璃建议；本任务完成后退出 skill。
- Task 2 针对性验证：后端 `45 passed`（含整理会话/summary/timeline 重启恢复）；前端相关 `9 passed`（含命令乐观消息与服务端 timeline 对账）；`tsc --noEmit` 与 `git diff --check` 通过。未运行全量回归、build、浏览器或 Langfuse；下一步为 Task 3 异步复习会话。

## 2026-07-14：R2 Task 4 非浏览器验收完成

- 清理阶段编号命名：删除 `r2_contracts.py`，题库与轮次结构化输出分别迁移到语义化 contract 模块，`ReviewRoundState` 回归 Graph，未使用的 `FollowUpDecision` 删除。
- 识别本机真实 Provider：OpenAI-compatible `GLM-5.2` 与 Anthropic-compatible `claude-haiku-4-5` 均为 connectivity `ok`；demo workspace 的 question/evaluation 与 report 角色绑定符合验收组合。
- 新增分阶段真实验收脚本，支持题库生成/发布、十题轮次、两次重启、报告审批、派生讨论和下一轮 weak-point 检查；脚本只记录 Provider 类型、模型/资源 ID、usage 和路径，不记录密钥或正文。
- 第一次真实 12 题整理只生成 3 个候选，收紧提示后为 6 个；改为按编号语义边界每 6 题分片、聚合去重后，同一批生成并发布 11 个候选，达到十题验收门槛。
- 真实 round `4c9098f2-df8e-4553-b3ed-8d0bdea03ea7` 完成 10 attempts、1 skip、9 follow-ups；等待首答和等待报告审批前各重启一次，均从持久状态恢复。两份报告成功发布，派生 discussion 未改变父轮次 attempts，weak-point 下一轮成功选题，context compacted 为 true。
- 真实组合使用 OpenAI-compatible `GLM-5.2` 评价与 Anthropic-compatible `claude-haiku-4-5` 报告，共 19 calls、102094 tokens；功能通过但成本偏高，列为后续上下文隔离与追问阈值优化项。
- 真实中断诊断发现 batch 可能永久停在 `generating`；新增启动对账，将无可继续 execution 的 generating batch/running round 标记 `failed`，重启用例 2 passed。
- 重启日志发现 role checkpoint 的 strict Pydantic structured response 不在允许列表；显式加入 R2 三类输出并补 round-trip 测试，避免恢复时静默丢失结构化状态。
- 最终回归：后端第二次/最终 `246 passed`；前端首次 `82 passed, 2 failed`（旧 App UI 断言），只修复失败文件后最终 `84 passed`；production build 通过并保留主 chunk 约 538 kB 警告。
- verification 用户指南与 foundation learning 七件套已生成。浏览器交互仍因 browser client `Cannot redefine property: process` 未执行，文档门禁因此必须保持失败，R2 未关闭。

## 2026-07-15：整理会话 UI 与回收站补强

- 题库页工具栏新增显式“回收站”入口；后端会话/原材料列表支持 `deletedOnly`，前端可查看、恢复和尝试永久删除软删除资源。
- 整理会话改为复习页一致的历史优先结构：默认展示概览与历史卡片，选择后进入对话/运行状态聚焦工作区，并可返回历史。
- 重复或正在整理资料的提示移到运行状态底部并默认折叠，不再占据执行过程的首屏空间。
- 针对性验证：后端知识与整理会话接口 `19 passed`；前端 `8 passed`；`tsc --noEmit`、production build 与 `git diff --check` 通过。
- 未执行浏览器交互验收；当前改动保持未提交，等待用户实际页面复核或提交指令。
- 后续真实浏览器复现聚焦会话重叠：对话区和运行面板均位于 `x=748`、宽约 `507px`。修复旧 `grid-area` 继承后，1280px 下对话区为 `x=265..935`、运行面板为 `x=935..1255`；1024px 下边界为 `265..679` 与 `679..999`，均无交叠。
- 会话首屏继续优化：开始复习的反馈栏改为工作区内滚动，整行高度从约 799px 收敛到 520px；开始复习与题库整理在进入会话后自动定位聚焦工作区。真实浏览器中题库会话自动滚动约 255px 后，对话输入框底部为 675px、工作区底部为 696px，均在 720px 视口内完整可见。
- 新鲜验证：`ReviewPage`/`QuestionCatalog` 共 10 项测试通过，`tsc --noEmit`、production build 和 `git diff --check` 通过；仅保留既有主 chunk 体积警告。
- 聊天记录补齐自动定位：复习会话在切换/消息与评价状态更新后滚到最新记录；整理会话在切换/消息/总结版本/乐观消息更新后滚到最新记录，并在下一渲染帧再次校准动态卡片高度。真实浏览器测得两类消息列表距底部均约 0px。
- 使用 `ui-ux-pro-max` 的高密度仪表盘与渐进披露原则重构整理状态栏，拒绝其不适用的夸张字体、漏斗页和全新配色。核心状态改为摘要卡、紧凑进度、三列指标和双列关键事实；运行详情、执行过程、资料提示独立折叠，失败重试保持常显。
- 真实浏览器 720px 高度复核：右栏 `clientHeight=558`、`scrollHeight=558`，默认状态无滚动；三个折叠区域均关闭且核心状态完整可见。
- 复现并修复多详情展开重叠：修复前“运行详情”处于 open 但被 flex 压缩到约 49px；修复后运行详情完整高度约 115px，切换执行过程时前者自动关闭，执行过程完整高度约 304px，两个区域不会同时展开或覆盖。

## 2026-07-14：R2 Task 3 API 与 Web 闭环

- 完成 question batch/candidate/active catalog 与 review round/answer/skip/cancel/discussion API；资源从 Runtime SQLite 恢复，不依赖 SSE 重建。
- 完成题库整理与复习双一级入口、候选搜索/Topic/难度/来源/状态筛选、来源证据、重复题内容对比、Markdown 阅读/原文/编辑边界。
- 完成可恢复多题答题工作台、模型与思考强度服务端快照、usage/掌握度/报告/发布路径展示；普通 input 不展示 HITL，真实 pending approval 才显示确认区。
- Knowledge 上传收敛为只登记 source；题目候选只在题库整理工作台生成和确认。
- 受影响后端 `43 passed`；前端 7 文件 `20 passed`；`tsc --noEmit` 与一次生产 build 通过。
- 本机临时后端 `/api/health` 与前端 `/review` 均返回 200；浏览器插件在加载自身 runtime 时因 `Cannot redefine property: process` 失败，因此没有执行交互式浏览器 happy path，也没有声明浏览器通过。
- 未配置或启动 Langfuse；下一步提交 Task 3 并执行 Task 4。

## 2026-07-14：R2 Task 2 Agent 与长生命周期 Graph

- 完成严格结构化题目/评价/报告契约、四个隔离 role thread 和回答模型/思考强度 override。
- 完成 question curation、review round、derived discussion 三类显式 Graph；多题轮次在同一 execution/checkpoint 经回答、必要追问、报告和两次发布审批恢复。
- 普通输入 interrupt 与 HITL approval 已分流；输入 receipt 幂等、同 key 异值冲突，未知 interrupt 稳定失败。
- 默认 middleware pipeline 新增不可变 review-round 预算，保留默认值并将 round/index/input request 纳入 no-progress 指纹。
- 针对性 Task 2 与受影响 Runtime/Agent 测试 `44 passed`；完整切片复核 `44 passed`，compileall 与 diff check 通过。
- 未运行全量回归、浏览器或 Langfuse；下一步为 Task 3 API/Web 闭环。

## 2026-07-14：R2 Task 1 题库与持久轮次领域事实

- 从 `e3d64b3` 在现有隔离 worktree 创建 `codex/r2-complete-review-agent`，未创建 subagent。
- RED/GREEN 完成 generation-2 additive migration、`waiting_for_input`、领域 records、四种 selector、repository 幂等/CAS、report proposal 和 publication callback。
- 题库发布后从结构化 candidate 投影 active catalog；mastery 发布从结构化 proposal 做 expected-version 更新。
- 针对性验证：Task 1 与受影响 Runtime/Knowledge/HITL 测试 `48 passed`；compileall 与 `git diff --check` 通过。
- 未运行全量回归、浏览器或 Langfuse；按阶段预算留到跨层接通和最终验收。

## 2026-07-14：R2 UI 设计契约补充

- 按用户确认调整验收边界：R2 默认无 Langfuse，不测试正常导出、可视化或服务不可达；后续 observability 专项再覆盖。
- 将复习轮次与题库整理两张桌面效果图保存到正式 R2 文档资产目录。
- R2 spec 新增 UI 设计原则、还原优先级、一级导航、题库整理工作台、复习轮次工作台、响应式/可访问性和浏览器验收规则。
- R2 plan 新增 `ReviewShell`、`QuestionDetailPanel`、candidate/batch 查询接口、模型/思考强度服务端快照，以及对应测试和浏览器路径。
- 明确效果图用于信息架构与行为参照，不作为固定数字或逐像素验收依据。
- 新鲜验证：两张 PNG 均为 1536x1024；文档测试 `16 passed`；图片引用扫描和 `git diff --check` 通过。

## 2026-07-14：R8 Channel 校准与 R2 拆解启动

- 用户纠正需求语义：微信、飞书 Channel 是原生聊天窗口接入，不是移动浏览器适配。
- 确认 R2 是完整 Web 复习 Agent；R8 才负责外部 Channel。
- 从 `main@262c540` 创建普通分支 `codex/r2-plan-r8-channel-alignment`，不创建额外 worktree 或 subagent。
- 选择 `planning-with-files-zh` 维护 current-state，使用 `writing-plans` 生成可执行 R2 实施计划。
- 已更新总路线 R8：明确微信/飞书原生会话、账号/workspace/session 可信绑定、消息幂等与乱序、异步回复、HITL 卡片、文件安全、断线恢复和真实 Channel 验收。
- 已创建 `docs/superpowers/plans/2026-07-14-r2-complete-review-agent.md`，按四个纵向任务拆解 R2，并明确 additive migration、`waiting_for_input`、长生命周期 Graph、完整 Web 闭环和最终验收。
- 已同步修正 R2 spec：375px 是响应式 Web 质量，不能作为微信/飞书 Channel 证据。
- 最终文档测试 `16 passed`，计划占位符扫描零匹配，`git diff --check` 通过；下一产品任务为 R2 Task 1。

## 2026-07-13：开发期 Runtime 数据库启动修复

- 复现 `IncompatibleRuntimeDatabaseError`，确认两个已注册 demo workspace 命中重构前开发 schema。
- RED：已知 schema 备份重建与未知 schema 中性错误两项用例按预期失败。
- GREEN：实现已知开发 schema 备份/重建，异常改为 `RuntimeDatabaseSchemaError`；针对性用例 4 passed。
- 相关仓储、HITL、草稿、知识和审计测试 33 passed。
- 最终后端回归 196 passed，文档门禁 16 passed，diff check 与旧错误文案扫描通过。
- 修复提交 `396f607` 已 fast-forward 合入 main；真实 FastAPI 生命周期到达 `Application startup complete`，随后仅因测试沙箱禁止绑定 8011 端口而正常关闭。
- demo 与 demo1 的当前数据库均为 generation 2，原测试 schema 分别保存在 `runtime.development-backup.sqlite`；demo2 未创建过 Runtime 数据库。

## 2026-07-13：Agent Harness 后续路线对齐启动

- 用户确认执行总路线修正、历史文档标记、跨阶段 Harness 模板和 R2 正式设计四项工作。
- 明确本轮不拆 R2 implementation tasks，也不开始产品实现。
- 从 `main@3435128` 创建 `codex/agent-harness-roadmap-alignment` 隔离 worktree。
- 文档门禁基线：`scripts/test_check_stage_docs.py` 16 passed。
- 扫描发现 R2 的 Middleware 1.0 引用、路线图 R0 当前状态和多份历史旧 Harness 计划仍可能误导未来实现。
- 总路线已改为官方 Harness 当前状态，补充十项阶段设计清单、四项纵向任务骨架和八项禁止项；R2 旧 Middleware 1.0 表述及 R0 当前下一步已修正。
- 16 份旧 R1/Pre-R2 spec/plan 与 Middleware task-details 已加统一“历史实现、禁止作为后续模板”标记；Middleware 1.0 spec 的既有失效提示同步强化。
- 错误记录：首次给 Pre-R2 文档加标记时假设了错误标题，补丁校验失败 1 次；读取真实标题后精确修正，未发生部分写入。
- R2 正式设计已完成：定义长生命周期轮次 Graph、领域输入 interrupt、角色 Agent、状态所有权、middleware、API、恢复、安全与验收；未创建 implementation plan。
- 收尾复核将“暂停”消歧为离开页面后继续，并将 Provider adapter 限定为配置/连通性适配；Agent 调用继续消费标准 `BaseChatModel`。
- 新鲜验证：`scripts/test_check_stage_docs.py` 为 16 passed；静态扫描未发现占位符、缺失历史警示或误改 `docs/my_idea.md`。

## 2026-07-13：设计与前三个纵向任务

- 用户确认测试数据可丢弃并选择不兼容重写；归档 tag 指向 `main@8e1b500`。
- Task 1 提交 `adfea9f`：官方 Agent 核心、直接模型解析、review Agent/Graph。
- Task 2 提交 `7a6f8cc`、`76c979a`：标准工具、ToolPolicy、官方 HITL、显式 publication。
- Task 3 提交 `92857a7`：官方 middleware、usage/title/summary/no-progress/observability 与原生 stream 投影。

## 2026-07-13：Task 4 实现

- 新建 application services、fresh runtime schema、Workspace checkpointer 与 observability infrastructure。
- FastAPI 和前端切到 session/execution/action/event 新资源；删除旧 Runtime、gateway、registry/executor、pipeline 与对应实现型测试。
- 修复 draft pending 状态、SSE 旧错误清理、同连接事件写入、restart/cancel 和 ToolStrategy 兼容。
- 角色 Agent 改用独立派生 thread；官方 summary 在第 11 次真实 execution 触发。

## 2026-07-13：验收

- 最小和完整浏览器验收完成：approve/reject、刷新、重复决定、重启恢复、桌面/375px、Vault path。
- 真实 Provider 验收完成：OpenAI-compatible 结构化评价与 Anthropic-compatible 流式报告。
- 不可连接 OTLP endpoint 下执行仍到达等待审批，证明 observability fail-open。
- 最终回归：后端 `195 passed`；前端 `76 passed`；`npm run build`（含 `tsc`）通过。
- 旧 E2E 契约已更新；静态扫描不再发现旧产品 API 名称。
- verification 与 `foundation` learning 七件套已生成，文档门禁通过。
- 最终实现提交：`4f6aabb refactor(agent): complete runtime framework convergence`。

## 当前下一步

1. 用户审阅 R2 正式设计；确认后再编写 implementation plan。
2. 用户并行完成本阶段 ownership 练习。

## 2026-07-15：生成文件交互与自由意图

- 候选题总结改为生成文件卡：默认 3 条，展开区限制高度并内部滚动；每个 draft 提供查看、发布、备注。
- 查看在同一会话右栏渲染 Markdown、AI 建议和按需相似题卡；发布复用确定性 publication/HITL；备注通过 migration 008 持久化且不触发 execution。
- 新增结构化 `CurationIntentAgent`，自由文本只生成 publish/reject/regenerate/resummarize 计划，稳定 candidate ID 解析和最终副作用仍由领域服务拥有。
- 自动证据：后端定向 21 passed，前端定向 7 passed，TypeScript/Vite build 通过；真实浏览器验收待执行。
- 修复候选题查看问答遗漏关键点：意图 Agent 只解析 inspect 目标，领域服务从候选结构化事实确定性生成题目、参考答案、关键点和必要追问；相关后端定向 18 passed。
- 修复意图 Agent 复用原 execution 导致的 `NoProgressError`：每次命令调用使用独立 progress scope，同一调用内部仍保留无限循环检测；覆盖重复输出、独立命令和同幂等键重试，相关定向 20 passed。
- 修复意图解析内部资源主键错配：真实 `candidate_resource` 使用 `id`，解析器不再假设外部 DTO 的 `candidateId`；改用稳定主键归一化并以真实内部资源形状回归，相关定向 19 passed。
- 修复整理会话时间与连续指代：SQLite UTC 时间显式按 `Asia/Shanghai` 渲染；命令耗时从请求开始时间计算；Enter 发送、Shift+Enter 换行；最近 8 条用户/Agent 命令消息及关联候选序号进入意图上下文。后端定向 20 passed，前端定向 8 passed，build 通过；历史页面已从 14:39/108 分钟修正为 22:39/单条耗时。

## 2026-07-13：合入 main

- `codex/agent-runtime-framework-convergence` 已 fast-forward 合入 `main@9116dff`。
- verification 与 learning 七件套已显式同步；目录 diff 和 verification SHA-256 一致。
- main 合并后复验：后端 `195 passed`，前端 `76 passed`，`npm run build` 通过。
- 文档门禁通过，旧 Runtime 抽象扫描零匹配；产品切片关闭。

## 2026-07-15：整理会话处理过程迁入聊天流

- 移除状态栏“执行过程”，将连续 stage 事件聚合为默认折叠的状态卡片，标题随 execution 在“Agent 处理中/处理完成/处理失败”之间切换。
- 每条聊天消息增加时间；整理总结、命令结果和处理状态的 execution 耗时紧邻时间戳展示。
- 真实页面验证：5 条处理步骤展开区高度限制为 220px，内容高度 259px，自动滚至底部且剩余距离为 0。
- 状态栏仅保留运行详情和资料提示，不再与聊天过程重复。
- 候选题总结已锚定在最新 `curation_summary` 消息之后，后续用户/Agent 对话按时间顺序显示在卡片下方；列表压缩为紧凑行并限制为 192px 内部滚动区。
- 运行状态栏移除耗时；Token 以 `k` 为单位进入默认展开的运行详情；“资料提示”改名“提示”并在存在时默认展开。真实页面两区同时展开时右栏 `clientHeight=scrollHeight=535px`，无额外滚动。
- 修正上下文压缩事实：Provider model 新增可配置最大输入 Token；middleware 使用 70% Token 主阈值、20% Token 保留量和 100 消息兜底，并将真实当前/阈值 Token 投影到 session API；前端已删除 timeline 条数推算。定向后端 68 项、前端 14 项通过，待重启服务后完成真实页面数据验收。

## 2026-07-15：持久上下文架构 Task 3

- 用确定性 parser 优先处理明确序号、唯一焦点和危险多焦点指代；复杂自由表达才进入结构化模型分类。
- `CurationIntentAgent` 收敛为无工具、无 checkpoint 的 classifier/summarizer 组件，执行名称与模型 role 分离。
- 新增领域上下文 adapter：完整 turn、焦点题全文、其他题轻量索引，并保证显式命令不加载上下文或调用模型。
- TDD 证据：RED 为缺少新模块/接口；GREEN 定向回归 27 passed。

## 2026-07-15：持久上下文架构 Task 4

- 删除 `execute_curation_command` 的固定 8 条消息分支，接入持久焦点、完整 turn、token budget、结构化压缩和 classifier lazy provider。
- inspect 后跨 10 条无关消息及进程重启仍能用“这题”发布；双焦点指代只澄清且不修改候选状态。
- 显式发布与重复幂等请求均零 classifier/summarizer 调用；重复请求不推进 context version。
- 压缩成功推进 summary cursor 并投影 `contextCompacted`；压缩失败记录 warning、保留 cursor，classifier 继续收到最近完整 turn。
- TDD 证据：集成 RED 6 failed；GREEN API/restart/migration 21 passed，跨模块定向回归 70 passed。
- 最终自动门禁：后端 `301 passed`（1 条第三方 Starlette 弃用 warning）；前端 `109 passed`；TypeScript/Vite production build 通过。首次全量发现 11 个同根因的无模型绑定启动失败，修复后失败文件 11 passed，再运行第二次也是最后一次后端全量确认 301 passed。
- 真实浏览器会话 `611cb0d3-c287-46f0-bbe5-0753fd6c5370`：5 轮 inspect 形成超过 8 条消息后，“这题发布吧”准确发布第 1 题；后端真实重启后发布回执与 3/2/1 统计恢复。
- 真实 structured classifier 将“请同时查看第 2、3 题”投影为两个 candidate ID；随后“这题发布吧”返回多焦点澄清，发布数不变，模型调用数保持 4。页面与 API 均显示实际 context `3160 / 89600` tokens；另一个真实会话为 `contextCompacted=true`。
- 375px 检查 `clientWidth=scrollWidth=375`，无横向溢出；浏览器 console error 为 0；本次后端未启动或依赖 Langfuse。产品实现基线为 `97529b7`。

## 2026-07-16：可取消流式执行 Task 4

- 前端按 execution ID 聚合 replay-safe SSE 临时消息；发送态切换为停止，支持模型/思考强度快照、interrupted 重试与放弃。
- 候选文件卡新增服务端预检的一键发布、共享停止、部分成功保留和仅重试失败/未处理项。
- `ui-ux-pro-max` 仅调用一次，落实紧凑 composer、危险操作层级、可访问确认框、有界流式内容与移动端折叠约束。
- TDD RED 后，前端定向 `22 passed`，后端跨层定向 `41 passed`；`git diff --check` 通过。
- 最终全量：后端 `319 passed`（1 条第三方弃用 warning）、前端 `113 passed`、production build 通过（保留 >500 kB chunk 提示）。
- 浏览器隔离工作区：桌面与 390px 可进入失败会话，模型/思考强度、失败恢复和运行详情可用且未见重叠。
- 环境未配置 Provider，执行真实进入 `MODEL_NOT_FOUND`；未伪造流式停止、重启恢复或批量部分成功的浏览器结论。
- 文档门禁已执行但因本地 `docs/learning/r2/` 尚未生成而失败；完整浏览器验收和 learning 七件套未完成前不关闭 R2。

## 2026-07-16：题库会话首 token 路径优化

- 普通问答不再先等待 structured classifier，默认直接调用无工具 responder 并发布真实 `assistant.delta`。
- 潜在副作用词仍走 classifier → validate → execute；明确题号命令继续走确定性 parser，模型不能直接写库。
- `CurationCommandPlan.response` 已删除，消除分类器完整生成回答后 responder 再生成一次的双调用。
- 长上下文普通问答先流式回答，再持久化 overflow 摘要；模糊副作用分类仍保留同步压缩以保证决策上下文安全。
- TDD RED 为 3 个路由/契约/delta 失败及 1 个摘要阻塞失败；GREEN 受影响命令、上下文、重启和 Runtime 回归 `58 passed`。
- 未消耗新的全量回归或浏览器验收预算；下一步仍是在健康 Provider 环境测真实 TTFT、停止、重启和批量部分成功。

## 2026-07-16：题匠输入 Dock 大视口返修

- 用户实际截图推翻首轮视觉验收；定位为旧 flex 对齐属性泄漏到新 Grid，导致 textarea/toolbar 收缩且发送按钮无法靠右，不是单纯间距偏好。
- 显式重置输入容器 stretch，工具栏改为三列 Grid，textarea 从一行起步并随内容增长至 120px；缩短空态提示，390px 隐藏无必要的桌面快捷键提示。
- 最终浏览器证据：903×689 输入区 456.9×110px、按钮右间距 9px；1440×900 右间距仍为 9px；390×844 无横向溢出；设置面板 310×161.7px 完整位于视口内；console warning/error 为 0。
- 针对性前端测试 `11 passed`，production build 通过（保留既有 >500 kB chunk 提示）。

## 2026-07-16：整理右栏候选状态实时化

- 删除右栏“当前任务”和来源处理单元百分比，替换为真实候选状态卡：草稿、待确认、已发布、已拒绝及最近更新题目。
- 候选查询按选中 session 过滤；summary、命令结果、发布和 execution 完成事件都会刷新，生成运行中保留 1200ms fallback；同批 SSE 中间事件不再丢失。
- 会话消息流中的候选文件卡及其查看/发布/备注/展开逻辑未修改。
- 真实 1280×720 页面展示 14 道、11 待确认、3 已发布；运行详情和提示默认展开时右栏 `558/558px`，无滚动或重叠，console warning/error 为 0。
- 新增候选状态 rerender 测试；相关 12 tests 和 production build 通过。
