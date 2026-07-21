# Agent Runtime 框架收敛进度

## 2026-07-21：GLM-5.2 题目整理正式修复

- RED：新增 GLM 默认 Thinking、显式推理、未知 OpenAI-compatible 兼容、角色输出预算、稳定分块 thread、无换行长文本六类测试；首次运行 `6 failed, 16 passed`，均命中预期缺口。
- GREEN：resolver 对 GLM 4.5+ / 5.x 显式映射 Thinking；8,192 输出预算仅绑定 `question_generation`；分块 thread 改为 `<session>:question_generation:<run>:<index>`；补齐单行硬切并移除 UUID/临时诊断日志。
- 自动验证：核心 `22 passed`；curation API、review round、profile Agent 相关回归 `57 passed`；`git diff --check` 通过。
- 真实 Provider：火山 `/coding/v3` GLM-5.2 在原 curation system prompt 下成功返回 1 个结构化候选，确认关闭 Thinking 参数有效。
- 合成约 20,000 字符多分块验证因 Provider 长延迟被人工取消；原始 Mybatis 文档因未取得明确数据外发授权未发送。完整真实文档验收仍待用户授权或由用户在 App 内执行。

## 2026-07-20：R3 第一里程碑实施计划完成

- 用户确认 R3 完整规格后，创建 `docs/superpowers/plans/2026-07-20-r3-personal-profile-agent.md`，本轮未修改业务代码、数据库或前端实现。
- 计划把 R3.1-R3.4 拆成 18 个顺序 TDD Task，覆盖 migration、私有存储/解析、Evidence/Claim/Proposal、四个 Agent、三个 Graph、八个只读 Tool、Action Plan、六个页面、发布/撤回及最终文档门禁。
- 自审纠正了 Evidence 定位与敏感 tombstone、PublicationSelection 版本快照、Claim 决定/证据支持双状态、编辑后接受、派生简历版本、删除三选语义和独立 `profile.assess` Graph，确保没有用简化实现偏离已确认规格。
- 明确执行继续由同一 Agent 端到端承担；Task 之间共享 migration/domain/runtime 状态，不适合并行 subagent。下一步从 Task 1 的 schema、六模型用途和共享 registry 开始。

## 2026-07-20：R3 Task 1-5 实现审查修正

- 审阅 Claude 的五个本地提交并复现 8 类阻断问题：跨 Workspace Proposal/PublicationSelection、Profile 目录未初始化、Proposal/Decision 非幂等、restore 破坏 active 唯一性、Action Plan SQL 列不存在、共享 blob 可被误删、system Session 可被通用 API 修改、空 DOCX/text 被当作成功。
- TDD 增加 regression coverage，并新增 migration 017：active Material partial unique index与 `profile_idempotency_receipts`。Proposal 创建/决定和 PublicationSelection 现在支持同 key/同请求返回原结果、异请求稳定冲突。
- Repository/Service 同步补强 Workspace 所有权、材料 aggregate version、derived version 来源、parse input hash、结构化 batch decision、Action Plan expected Claim version和公开 connection 边界。
- Runtime 初始化 Profile 私有目录；generic session/execution 定位器隔离 system Session；MaterialStorage 删除必须显式提供剩余引用数；所有空可解析文档统一失败为 `profile_no_extractable_text`。
- 移除 Claude 越界加入且未经本轮确认的两个 ADR；修正设置页“六用途未齐就不能复习”的误导文案。未修改或纳入 Claude 尚未提交的 Task 6 两个 RED 测试。
- 修复后完整 Task 1-5 后端定向门禁 `181 passed`（仅 1 条既有 Starlette 弃用 warning）；相关前端 `13 passed`；TypeScript、Python compileall、`git diff --check` 通过。下一步从 Task 6 继续。

## 2026-07-20：R3 Task 6 - 有界只读 Profile Tool

- 完成规格允许的八个只读 Tool；所有业务输入使用 strict/extra-forbid Pydantic Schema，Workspace、Session、Run、Tool/Scope allowlist 仅由 `AgentContext` 注入，handler 内再次校验 Workspace 与 Scope。
- Tool 只返回材料/版本/Claim/Evidence/发布的稳定 ID、结构化字段、定位信息和短摘录；统一 envelope 最多 50 项、单条摘录最多 2,000 字符，不返回整份私有材料、storage/text ref 或数据库异常。
- 新增每个 Execution 最多 6 次、相同规范化 `(tool_name,args)` 最多 2 次的预算中间件；耗尽后返回终止 Tool loop 的安全指引。统一 middleware stack 支持显式插入 Tool guard，Profile budget profile 同步收紧为 6 次。
- Claude 的 RED 夹具最初用不同 content hash 提交 parse，触发既有仓储不变量；修正夹具后补齐 Scope、Workspace、截断、顺序、归档、strict schema 与参数键顺序规范化覆盖。
- 新鲜定向证据：Profile Tool/预算与受影响 middleware stack `29 passed`；Python compileall 与 `git diff --check` 通过。Ruff 不在项目依赖中，未声称 Ruff 门禁。

## 2026-07-20：R3 Task 7 - 结构化 Profile Agent 与 ingest/assess Graph

- 新增 extraction、assessment、chat、action planner 四个逻辑 Agent；首版分别绑定 `profile_extraction`、`profile_assessment`、`agent_chat`、`profile_assessment`，全部使用默认 AgentState。Extraction/Assessment/Planner 无 Tool，Chat 只接 Task 6 的只读 allowlist。
- `ProfileExtractionOutput` 强制 category、typed value、1-50 个 Evidence ID、confidence 和 rationale；`profile.ingest` 按 parse→redact→evidence candidates→Agent→validate/persist 显式节点运行，未知 Evidence 在写 Proposal 前整体拒绝。
- 私有原文和 source bytes 只在节点局部变量/MaterialStorage 中存在；外层 Graph state 仅保存材料/版本/Evidence/Proposal ID、计数和未提交结构化输出。Agent checkpoint 仅获得最多 50 条、每条 2,000 字符的脱敏 Evidence。
- 上传/重试现在通过 `AgentExecutionService.run_prepared` 真正调度后台 Graph；Runtime 注入同一连接上的 ProfileRepository/Storage，不在节点另开连接。事件仅包含版本/Proposal ID 和计数。
- 独立 `profile.assess` 锁定 confirmed snapshot，先校验全部 Evidence、版本和目标 Claim，再幂等保存 Assessment/Proposal，最后投影 `assessment_card`；失败不留下 Assessment 半成品。
- 新鲜定向回归：Profile repository/material service/Agent/Graph/checkpoint/middleware/Agent routes 共 `73 passed`；compileall 与 `git diff --check` 通过。

## 2026-07-20：补充 Agent State 与 Context Offload ADR

- 将 `state_schema` 的五项准入条件、状态归属表、R2 现状和 R3-R6 采用边界补入全路线 Agent 能力 ADR。
- 区分摘要 compaction、ToolMessage 清理、领域 evidence 外置和可重读 Runtime Artifact Offload，避免把 `[cleared]` 或数据库持久化泛称为完整 Offload。
- 决定 R3 首先建设个人材料 Evidence Offload，通用 Runtime Artifact Offload 等真实复用证据；Context Editing 阈值在工具型 Agent 启用前按模型窗口和 role 预算配置。
- 本次只更新正式 ADR 与本地 current-state 记录，不修改业务代码、数据库或 `docs/my_idea.md`。

## 2026-07-20：全路线 Agent 能力矩阵 ADR

- 盘点 R2 生产 Agent、跨领域基础辅助模型和 R3-R8 路线角色，区分 ToolStrategy、业务 Tool、领域 Graph、checkpoint 恢复、事件回放、领域版本和真正 Time Travel。
- 新增 `docs/superpowers/architecture-decisions/2026-07-20-agent-capability-allocation-across-roadmap.md`，逐组件记录 Tool、Plan-and-Execute、恢复和 Time Travel 默认能力。
- 决定全路线不启用模型自由写工具或通用 Time Travel；R3-R6 探索角色只用有界只读工具；R2/R3/R4 的复杂变更采用受控计划，R6 采用固定主从委派。
- 本次只修改正式架构文档与本地 current-state 记录，不修改业务代码或 `docs/my_idea.md`。

## 2026-07-20：领域 Agent 工具与写入边界 ADR

- 核对 R2 当前生产代码，确认全部领域 Agent 的业务 tool/scope allowlist 为空；候选只读工具和写草稿工具只存在于 Harness 基础设施、测试或预留注入点，未接入 R2 生产执行。
- 接受跨阶段决策：已知上下文 Agent 默认无工具；探索型 Agent 仅获角色级最小只读工具；正式修改、删除和发布由结构化 proposal、领域服务、显式用户确认和 receipt 驱动。
- R3 个人信息 Agent 将使用 ID/evidence-ref 驱动的材料与画像只读工具，不复用允许模型传任意路径的通用 source reader；画像确认不自动推导为知识发布。
- 新增 ADR `2026-07-20-domain-agent-tool-and-write-boundaries.md`；本次只记录正式架构决定，未修改业务代码、数据库或测试。

## 2026-07-20：主分支合并与远程发布准备

- 产品分支重命名为 `feature/review-agent-workspace`，不再使用工具或阶段编号前缀。
- 推送前扫描当前树和 `main..HEAD` 历史，未发现私钥、GitHub/OpenAI Token、运行数据库、日志或 `node_modules` 被跟踪；Langfuse `.env.example` 仅包含本地示例配置。
- 11 张约 9.5 MB 的 `.design-qa/`、`.design-audit/` 本地截图已从当前 Git 索引移除但保留磁盘文件，并补充环境文件、数据库、日志和本地工具目录忽略规则。
- 远程发布仍待恢复 GitHub 认证或提供可访问的私有仓库 URL；本机 `gh` 的 `Miracle778` token 已失效，SSH 访问同名仓库失败。

## 2026-07-19：Agent 代码结构整理第一阶段

- 完成 Agent、Factory、模型解析器和 Middleware 文件的显式语义命名，所有生产代码与测试导入已迁移，旧含糊模块不再存在。
- 新增 `app/agents/prompts/`，提取题目整理、整理命令、单题复习、轮次复习和深入讨论 Prompt；PromptSpec 提供稳定 ID/版本，输入 renderer 与 Agent 调用解耦。
- 新增共享 `AgentRunnable`/`StreamingAgentRunnable` 和 thread invocation helper，删除各 Agent 模块的重复 Protocol 与 `_role_config`。
- 新增模块布局、Prompt identity/render 和 thread 隔离测试；核心 Agent/Middleware 53 tests、API/重启/异步执行 50 tests 通过，最终后端全量 339 tests 通过，compileall 通过。
- 本阶段保持数据库 schema、API DTO、Graph state、thread ID、事件类型和 SSE 顺序不变；已运行后端全量回归，未重复运行前端或浏览器验收。

## 2026-07-16：候选状态文件下钻完成

- 抽取共享 `CurationArtifactCard`，会话总结与右栏列表共用查看、发布、备注行为及 query-backed candidate 状态。
- 点击草稿/待确认/已发布/已拒绝数字可进入有界文件列表；支持历史版本标记、Markdown 详情和返回筛选状态。
- 针对性前端 13 tests 通过，TypeScript/production build 通过；1440×900 浏览器交互、布局与 console 检查通过。
- Product Design 的强制并排比较受 in-app browser 本地文件安全策略阻断，`design-qa.md` 如实保持 `blocked`，不将其表述为完整视觉门禁通过。

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

## 2026-07-19：整理会话题目统计口径修复

- 将主页“累计候选”改为“题目总数”，使用与题目库一致的逻辑题目归组结果。
- “已发布”同步改为逻辑题目聚合状态计数，避免历史入库版重复累计。
- 定向前端 17 passed，production build 通过。
- 本机 5174 验证：题目总数 25，点击后显示 25 道/25 条；已发布 18，点击后显示 18 道/18 条。

## 2026-07-19：深入讨论会话闭环修正启动

- 已完成代码与本机页面诊断，确认固定代发问题、作答上下文缺失、Session 无恢复入口和重复创建风险。
- 采用单 attempt 对应一个可恢复 discussion Session；首次打开只初始化持久上下文，不调用模型，用户发送后才进入 SSE 执行。
- 本阶段不调用 superpowers、不创建新 worktree或 subagent；在现有 R2 分支端到端完成。
- 首次 production build 被旧测试 fixture 缺少新增 `discussionSessionId` 阻断；该字段改为兼容旧响应/历史 fixture 的可选读取字段，服务端新响应仍始终返回明确值。
- 浏览器客户端不支持 Playwright 风格的 `setViewportSize`，因此未重复调用；本轮使用当前真实窗口完成桌面交互核对，响应式约束由 production build 和既有 CSS 门禁保留，后续完整 R2 浏览器验收再统一覆盖窄屏。
- 同一浏览器绑定也不暴露 `playwright.screenshot`；停止继续猜测截图 API，保留已取得的真实 DOM/交互证据，避免无变化工具循环。

## 2026-07-19：深入讨论会话闭环修正完成

- 点击入口不再自动发送固定问题；首次只初始化 checkpoint，页面明确提示发送后才调用 Agent。
- 上下文卡展示题目、原回答、补充回答和评价；增加建议问题、真实 SSE 发送、停止与失败重试。
- 旧 discussion Session 无需迁移即可恢复，返回报告后按钮显示“继续讨论”；重复点击复用同一 Session。
- 自动证据：后端 Graph/API/Session/Repository 30 passed；前端 review 55 passed；production build 通过。
- 本机 5174 验证：旧 MySQL B+ 树 discussion 成功恢复，完整作答上下文和历史回复可见，报告入口显示“继续讨论”。未额外发送模型问题。

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

## 2026-07-16：候选状态文件下钻与正式视觉门禁

- 右栏状态数字可点击下钻到具体 Markdown 文件卡片；卡片与会话记录复用同一组件、候选数据和查看/发布/备注回调，不维护第二套状态。
- 正式 1440×900 并排门禁完成：首轮修复状态顺序和摘要缺失，次轮修复重复标题、英文难度及操作层级。
- 最终设计图与实现右栏逐面复核无 P0/P1/P2；页面无横向溢出，右栏不溢出，文件区使用有界内部滚动，浏览器 console warning/error 为 0。

## 2026-07-16：题目库浏览器重构

- 题目库改为搜索/筛选 + 主题目录 + 扁平结果 + Markdown 阅读器的三栏结构，原有渲染、原文、编辑、AI 重写和生成会话入口保留。
- 候选 API 客户端支持页码，页面遍历真实分页，修复原先只显示前 50 道导致的统计和筛选误差；真实页面现显示 51 道、33 待确认、18 已入库。
- 桌面 1440×1024 与移动端 390×844 均无横向溢出；搜索 Redis 得到 20 条、状态筛选与 Markdown 模式切换可用，console warning/error 为 0。
- 选定设计与最终实现已在同一画布完成全页和主体并排复核；首轮三个 P2 视觉问题修正后门禁通过。
- 题目详情模式从“渲染 / Markdown 原文 / 编辑”收敛为面向用户的“阅读 / 原文”；原文页直接编辑 Markdown 并保存，同时同步标题、题干、参考答案和关键点。相关前端 10 项测试与 production build 通过。
- 题目“确认入库”后的 HITL 不再追加到题库页面末尾，改为当前视口内的发布审批弹层；审批列表同时按 action type 与本次 execution ID 过滤，避免展示其他题目的待处理动作。
- 发布审批弹层完成二次设计：补齐右上角关闭、Escape/遮罩关闭、44px 点击区；默认展示有界 Markdown 预览，编辑和暂不发布理由改为渐进展开，底部操作始终可见。
- 关闭审批后显示固定待处理入口，刷新页面会从服务端 pending action 恢复，避免关闭弹层或 HMR 后丢失审批上下文；真实本地 pending action 已完成打开、关闭与恢复检查。
- 针对性前端 21 tests 通过，production build 通过（仅保留既有 >500 kB chunk 提示）；真实页面截图：`.design-qa/question-library/publication-approval-redesign-2026-07-16.png`。

## 2026-07-18：整理会话概览下钻

- 将含糊的“进行中”改为“待处理会话”，口径明确为排队、整理中、待确认和发布中的非终态会话；失败与已完成会话不计入。
- 三张概览卡均可操作：待处理会话在当前页切换筛选，累计候选进入全部题目，已发布进入题目库并自动应用已入库筛选。
- 修复概览数字原先按会话 `candidateCount/publishedCount` 求和、题目库按全局候选查询造成的口径不一致；两处现共用完整分页候选事实，累计候选和已发布数量与点击结果一致。
- 题目库目录计数改为分面统计：主题数字会随搜索、状态、难度和来源联动，并按题目全部主题计数，点击后的结果数量与目录一致；“全部题目”同样展示当前非主题筛选范围。
- 删除在所有主题下重复显示的全局“最近整理 N 道”，结果头改为“全部候选 / 当前筛选结果 / 某主题”范围说明；待发布审批入口收进筛选工具栏，使用“待审批 + 数量”的紧凑按钮复用原审批弹窗，不再遮挡正文或占据整行。
- 新增筛选、跳转和统计一致性测试；`CurationSessionList` 与 `QuestionCatalog` 共 10 tests passed，production build 通过（保留既有 >500 kB chunk 提示）。

## 2026-07-18：发布审批等待与空结果修复

- 定位真实数据根因：同一草稿已有 pending action，重复点击却创建新 execution，action 幂等冲突使新 execution 失败；前端随后盲轮询 20 次并显示“暂无待确认动作”。
- 发布接口改为幂等的 get-or-create：已有动作直接返回原 action/execution；首次请求等待 Graph 到达 `waiting_for_approval` 后返回 action，不再暴露中间竞态。
- 题目库把接口返回的 action 直接交给审批弹窗，并以 action ID + execution ID 双重聚焦；后台列表刷新只用于恢复，不会让弹窗退回等待态。
- 拆分发布入口语义：题目详情“确认入库”只打开当前题；工具栏“待审批 N”先展示全部待审批题目标题，未选择前不显示内容或发布按钮，选择后只操作该 action。
- 完成“退回修改”闭环：HITL rejection 同步候选题与 draft，候选资源暴露退回理由/时间/action；详情页展示理由并预填 AI 重写反馈，手动修改会生成新版本、恢复待确认并允许创建新的审批 action。migration 013 会回填现有 rejected draft 对应的候选状态与理由。
- 退回闭环新鲜验证：后端 migration + draft/publication routes 15 passed；前端 ActionCenter、题目详情、题库与整理卡片 30 passed；`tsc --noEmit` 通过。
- 定向验证：后端 `test_draft_routes.py` 7 passed；前端 ActionCenter、QuestionCatalog、DraftReview 26 passed；`tsc --noEmit` 与 `git diff --check` 通过。

## 2026-07-18：候选题生成会话可靠跳转

- 新增候选题原会话解析资源，区分可用、回收站、整理投影缺失和底层会话缺失；没有批量回填既有开发测试数据。
- 题目详情按 candidate ID 解析原会话，可用会话直接按 ID 打开，不再受整理会话列表 50 条上限影响；回收站会话提供“恢复并打开”，缺失状态显示明确提示而非空白工作区。
- 针对性验证：后端 curation session API 22 passed；前端 QuestionCatalog/QuestionDetailPanel 16 passed；production build 与 compileall 通过（仅保留既有 >500 kB chunk 提示）。

## 2026-07-19：题目与 Session 生命周期解耦 ADR

- 用户确认会话可归档或永久删除且不级联删除题目；题目增加单删、显式勾选批删和回收站；原会话不存在时创建轻量修订会话。
- 新增 Accepted ADR `2026-07-19-question-session-lifecycle-decoupling.md`，比较三种方案并固定 Session、Question、Publication、Review Round 的状态所有权。
- R2 权威 spec 已补生命周期与 `question.revise` 规则；task plan 新增阶段 13，并把实施排在最终浏览器验收之前。本次只记录设计，未修改业务代码或开发测试数据。

## 2026-07-19：题目与 Session 生命周期解耦实施启动

- 已确认权威 worktree 为 `.worktrees/r2-complete-review-agent`，保留现有未提交改动，不另开 worktree、不创建 subagent。
- 新增四任务实施计划：持久化边界、领域/API、单题修订解析、Web 闭环与验收；当前进入 Task 1。
- `ui-ux-pro-max` 只采用与既有产品一致的显式勾选、危险确认、加载反馈、44px 点击区和有界滚动约束，不替换现有品牌视觉。

## 2026-07-19：题目与 Session 生命周期解耦业务实现

- migration 014、领域 repository/application、API 和 `question.revise` Graph 接线完成；会话归档/永久删除与题目资产不再级联。
- 题目库增加单题删除、checkbox 显式批删、逐项结果反馈和题目回收站；会话列表统一称为归档，永久删除只在回收站提供并明确保留题目。
- 新增跨层测试验证 Session 永久删除后题目/血缘保留、缺失会话创建修订 Session、logical question 不变、draft 版本推进，以及删除幂等/列表排除/恢复/部分失败。
- 定向证据：后端 runtime migration + agent routes + curation/API/catalog `41 passed`；前端 QuestionCatalog/QuestionDetailPanel/CurationSessionList `18 passed`；production build 通过，`git diff --check` 与 compileall 通过。
- 最小浏览器验收：本机真实 51 道题显示独立 checkbox；勾选后出现“已选 1 道/批量删除”；1280px 和 390px 均 `clientWidth == scrollWidth`，console warning/error 为 0。未执行真实删除，避免修改用户当前测试数据；删除副作用由自动化跨层测试覆盖。

## 2026-07-19：逻辑题唯一入库版与版本晋升

- 题目库按稳定逻辑题身份归组；普通发布在应用层和 catalog 事务内双重阻止等价题成为第二个 active 题目。
- 新增“更新入库版”专用 API：待确认候选复用目标 `question_id`，以 active content hash 做乐观并发校验，原子切换 catalog；旧 publication、Vault 文件与已开始复习轮次继续保留。
- 前端版本区区分当前入库版、历史入库版与候选版；候选可显式晋升，普通确认入库会提示改走更新流程。
- 自动证据：后端定向 `47 passed`；前端定向 `15 passed`；production build 与 `git diff --check` 通过。5174 当前未连接后端且 Workspace 未初始化，真实数据浏览器晋升仍待服务恢复后补验收。

## 2026-07-19：整理工作区返回导航增强

- 整理会话详情和题目库统一在页面标题区展示“返回整理会话”，使用箭头、文字和 40px 可点击区域；移除题目库目录栏中不易发现的图标返回入口。
- 返回时退出详情态并清理临时会话、候选详情和状态筛选；题目库内部搜索、筛选状态仍由组件保留。
- 针对性验证：`QuestionCatalog.test.tsx` 12 passed，production build 通过；浏览器真实 workspace 视觉复核待本地已配置页面完成。

## 2026-07-19：复习历史、失败恢复与结果回放

- 修复追问“跳过”后仍再次调用 evaluator 的状态机错误；首次评价被保留，attempt 直接完成并进入下一题。
- 新增 failed review execution 的 checkpoint 恢复 API 和前端“恢复本轮”入口；回答、评价和当前题序不重建、不丢失。
- 历史页改为中文模式/难度、北京时间、进行中/完成/结束/真实作答统计，进度按 completed attempt 计算。
- cancelled/failed 页面不再空白；完成与有记录的终态提供复习报告/会话回放双视图，旧数据从持久 attempt 还原回放。
- 自动证据：后端 Review Graph/API/异步恢复 `13 passed`；前端 review feature `52 passed`；production build 与 `git diff --check` 通过。
- 本机 5174 浏览器检查 5 条历史：2 条可恢复、2 条已结束、1 条已完成；恢复入口、终态、报告和旧数据回放均可见。未点击恢复，避免触发真实模型调用。
# 2026-07-19：深入讨论工作台体验补全

- 已对照用户截图完成静态审查：确认上下文过高、消息列失衡、重复返回入口、模型控制/运行事实缺失，以及完成态错误显示停止按钮。
- `ui-ux-pro-max` 门禁确定为“内容优先聊天主区 + 320px 有界上下文侧栏 + 紧凑 composer”；正在进行实现与本机 5174 验收。
- 页面已改为聊天主区 + 320px 侧栏：本题上下文和评价摘要有界折叠，消息列扩到 860px，移动端回落为上下两区；重复的全局返回入口在讨论态隐藏。
- composer 已补模型、思考强度、停止/发送；配置随 execution 持久化并真实覆盖 `agent_chat` 模型。侧栏展示状态、耗时、Token、调用次数和上下文压缩事实，assistant 回复增加复制操作。
- 修复历史 execution 状态滞后导致完成后仍显示“停止”：同 execution 的持久 assistant 回复现在作为终态纠偏证据。
- 验证：后端定向 `15 passed`；前端定向 `10 passed`；`tsc --noEmit`、production build、`git diff --check` 通过。
- 浏览器可加载 5174 前端，但当前浏览器会话无法取得本机 8000 的 workspace 数据，只看到“正在连接本地服务”，因此未虚报真实数据视觉验收；需在用户已有本机会话刷新后复核最终密度。
- 用户在真实页面复核后否决第一版 composer 与笼统上下文状态；阶段 21 改为直接对齐题库整理 Agent 的既有视觉/交互规范，并暴露通用 middleware 已记录的真实上下文 Token 进度。
- 深入讨论 composer 已切换为题库整理页同款 DOM/CSS 结构：textarea 独占首行、设置胶囊渐进披露模型/思考强度、Shift+Enter 提示、44px 圆形发送以及运行时停止态。
- 通用 `SessionDetailResource` 新增 `contextUsage`，直接读取 `agent_context_usage`；讨论运行详情默认展开并显示执行状态、耗时、模型、Token、调用次数、百分比圆环和 `当前上下文 / 压缩阈值`，压缩发生后显示事实提示。
- 复用题库整理页的运行详情、上下文圆环、提示与 loading 视觉类；保留 discussion 真实 SSE/停止/失败重试，不伪造题库整理特有的读取、合并等阶段。
- 新鲜验证：后端定向 `15 passed`；前端相关 `19 passed`；`tsc --noEmit`、production build、`git diff --check` 通过。后端响应契约已变化，真实页面复核前必须重启 8000 服务。

## 2026-07-19：复习 Agent 工作台比例与组件统一

- 修复深入讨论与普通复习工作台同时渲染；进入讨论时只保留讨论工作台，退出后恢复原复习会话。
- review shell 的内容区、workbench 与 main 改为传递父级可用高度；普通会话和讨论会话不再各自硬编码 viewport 减法，桌面填满剩余高度，移动端保持自然滚动。
- 两类工作台右栏统一扩为 `340–400px` 自适应宽度并压缩卡片间距；普通复习侧栏新增真实上下文百分比圆环、current/threshold、模型、思考强度、Token 与调用次数，关键点改为有界折叠区。
- 普通复习 composer 已切换为题库整理/深入讨论同款 Dock：textarea 独占首行、紧凑模型摘要、Shift+Enter 提示、跳过次动作和 44px 圆形发送。
- 新鲜验证：后端 round projection/restart `7 passed`；前端会话、讨论、页面 `11 passed`；`tsc --noEmit` 与 production build 通过（仅保留既有 >500 kB chunk 提示）。浏览器连接连续两次返回失效 tab，已按门禁停止无变化重试，未将其写成浏览器验收通过。
- 二次比例校正：普通复习与深入讨论的聊天区/状态栏均显式占满同一 Grid 行；两个右栏移除整体 `overflow-y` 和滚动槽。普通复习的长关键点限制在剩余高度内滚动，移动端恢复自然文档流。最新 production build 与 `git diff --check` 通过。
- 单屏滚动边界修正：桌面普通复习和深入讨论的 shell 固定为 `100dvh` 并禁止整页溢出，移除聊天工作台/会话的 520px 最低高度；对话记录内部继续滚动，composer 和右栏固定可见。移动端在 899px 以下恢复页面自然滚动。最新 production build 与 `git diff --check` 通过。

## 2026-07-20：R3 Task 1 — Runtime Schema 与共享 Registry

- 新增 Runtime migration 016：`agent_sessions.visibility`（user/system）、重建 `agent_messages` 接受 profile 卡片/Receipt kind、重建 `tool_audits` 增加 `tool_call_id/agent_role/input_digest/result_digest` 与 `denied` 状态、重建 `knowledge_drafts` 接受 `profile`、重建 `publication_runs` 接受 `revoked`，并新建 13 张 R3 领域表（材料/版本/Evidence/Claim/ClaimVersion/Proposal/Conflict/Assessment/ActionPlan/Item/PublicationSelection/SelectionItem/Publication）。
- 新增 App migration 003：重建 `workspace_model_bindings` 接受六个角色，保留既有四角色绑定。
- 共享边界：`ModelRole`/`MODEL_ROLES` 增加 `profile_extraction`、`profile_assessment`，校验文案 four->six，读绑定容忍部分历史绑定、仅显式保存要求六角色；`profile -> 50_profile` 文档类型与 Vault 目录；`domain="profile"` 创建 `artifacts/profile/materials/{blobs,text}`；`profile.materials` scope 与 `knowledge.active` 隔离；`python-docx>=1.1.0` 入依赖。
- TDD：先写失败测试（14 red），再实现；后端定向 `54 passed`，关联绑定 `43 passed`，前端 `ModelBindings.test.tsx` `2 passed`，`tsc --noEmit` 0 错误，`git diff --check` 通过。
- Reviewer gate：重建表逐列拷贝既有行（旧 tool_audits/agent_messages 行保留验证通过）；Runtime 迁移 runner `PRAGMA foreign_key_check` 无违规；`profile.materials` 穿越到 `knowledge-vault` 被拒。

## 2026-07-20：R3 Task 2 - Profile 领域契约与 Repository 不变量

- 新增 `app/profile/` 领域包：`models.py`（frozen dataclass 记录、Literal 状态、命令/结果类型）、`errors.py`（稳定错误码：profile_material_not_found/evidence_mismatch/proposal_already_decided/claim_version_conflict/snapshot_changed 等）、`repository.py`（ProfileRepository）。
- 仓库方法：create_material/add_material_version/mark_version_parsed/replace_version_evidence/create_claim_proposals/decide_proposal/batch_decide_proposals/save_assessment/create_action_plan/apply_action_plan_item/create_publication_selection/profile_snapshot 及配套读方法。
- 不变量：材料版本号单调递增；同一 workspace+primary_role 仅一个 active 材料；Evidence 不可变（replace 时旧记录 tombstone 并清空敏感正文）；Proposal 接受原子化（校验 Evidence 属不可变版本、追加 ClaimVersion、更新 current_confirmed_version_id、标记 proposal accepted 同事务）；决策态与证据支持态独立（confirmed 可转 unsupported）；冲突 proposal 记录冲突边不覆盖已确认版本；profile_version 由有序 (claim_id, version) 确定；stale Action Plan 被 reject。
- TDD：先写 20 个失败测试（ImportError），再实现；`test_profile_repository.py` `20 passed`，`compileall` 通过，`PRAGMA foreign_key_check` 无违规。
- Reviewer gate：所有写操作在 BEGIN IMMEDIATE 事务内并带 state/version 谓词；get_material 强制 workspace 归属；profile_snapshot/list_materials 均按 workspace 过滤。

## 2026-07-20：R3 Task 3 - 私有内容寻址存储与解析器

- 新增 `app/profile/storage.py`：`MaterialStorage` 在 `artifacts/profile/materials` 下内容寻址存储；blob 路径 `blobs/<sha[:2]>/<sha>.<ext>`，提取文本 `text/<version_id>.txt`；10 MiB 上限、扩展名白名单（pdf/docx/md/markdown/txt）、文件名穿越校验、fsync+atomic replace、写后哈希校验检测短写、重复内容复用 blob、删除幂等、符号链拒绝。
- 新增 `app/profile/parsers.py`：`parse_document` 按扩展名分发（不信任浏览器 mime）；PDF 按 `{page}`、DOCX 按 `{paragraph}`、Markdown/text 按 `{lineStart,lineEnd}` 定位；行尾归一化不改源字节；加密 PDF -> `profile_encrypted_document`，损坏 -> `profile_parse_failed`，扫描无文本 -> `profile_no_extractable_text`，错误信息仅含 code/ID 不含正文/路径。
- 扩展 `WorkspacePathPolicy.scope_root(scope)` 供 storage 安全创建 blob 前缀目录；`workspace_layout` profile 子目录改为有序创建 materials/blobs/text。
- TDD：先写 21 个失败测试，再实现；`test_profile_storage.py` + `test_profile_parsers.py` `21 passed`，关联回归 `73 passed`，`compileall` 通过。
- Reviewer gate：失败路径用 temp+os.replace+finally 清理不留部分文件；异常串与日志只含 code/ID，`"broken"` 等正文不入错误消息，绝对路径不泄漏。

## 2026-07-20：R3 Task 4 - 材料生命周期服务与隐藏摄入 Session

- 新增 `app/profile/service.py`：`ProfileService` 复用共享 Runtime 的 ProductRepository/AgentSessionService；`upload_material`/`add_material_version` 持久化字节、创建不可变版本、创建隐藏 `profile.ingest` system Session（id==version_id）、启动仅含 ID/定位符的 Execution，不创建用户消息；`retry_version_ingest` 拒绝活跃 Execution 并在同一隐藏 Session 上新建 Execution；`record_ingest_failure/success` 推进 Execution 终态与版本状态；archive/restore/primary 委托 repository。
- 扩展 `SessionRecord.visibility`（默认 user）、`ProductRepository.create_session(visibility=)`、`list_sessions(include_system=)` 默认仅 user、`AgentSessionService.create(visibility=)`；`_locate_session` 对 system 会话 continue（通用 API 不可见），内部 Runtime 仍经 repository 直接访问；`get_session` 路由补 404 映射。
- `WorkspaceRuntime` 注入 `profile: ProfileService`（共享 connection/repository，不新建数据库句柄）。
- TDD：先写 9 个失败测试，再实现；`test_profile_material_service.py` `8 passed` + `test_agent_routes_v2.py` 隐藏会话过滤 `1 passed`；回归 `58 passed`（agent routes/restart/profile/migrations）。
- Reviewer gate：直查 Runtime SQLite 确认每版本一个 system Session、无用户消息、通用 Agent 端点不返回 system Session。

## 2026-07-20：R3 Task 5 - Tool 审计与安全 Tool 可见性事件

- 扩展 `ToolAuditRepository`：`deny()` 记录 `denied` 状态；`start()` 接收 `tool_call_id/agent_role/input_digest`；`complete()/fail()` 接收 `result_digest`；`ToolAuditRecord` 增加四列；`canonical_digest` 提供稳定 SHA-256（不持久化原始参数/结果）。
- 扩展 `ToolPolicyMiddleware`：注入 `publish_event` 回调；拒绝路径 audit.deny + 发布 `agent.tool.failed`(tool_not_allowed)；start/complete/fail 分别发布 `agent.tool.started/completed/failed`，payload 仅含 executionId/toolCallId/toolName/purpose/status/resultCount/errorCode，不含原始参数/结果/模型推理；计算 input/result digest。
- `AgentContext`/`ToolExecutionContext` 增加 `agent_role`（默认 None，向后兼容）；`ProductEventStream._allowed` 增加三个 agent.tool.* 事件；`graph_factory` 三处构造点与 `WorkspaceRuntime.build` 串接 `publish_event=events.publish`（用 `.get` 保持既有 fixture 兼容）；前端 `useAgentEvents` 事件联合增加三个事件。
- TDD：先写 5 个失败测试，再实现；`test_tool_policy_middleware.py` `5 passed`；前端 `useAgentEvents.test.tsx` `8 passed`，`tsc --noEmit` 0 错误；回归 `46 passed`。
- Reviewer gate：用含 `api_key`/路径/正文的样本参数验证事件 payload 与 audit 仅含哈希与安全字段，无源文本/Tool 结果体泄漏。

## 2026-07-21：Progressive 题目整理与 Agent JSONL

- 单阶段完整候选生成已替换为稳定 section、bounded discovery/enrichment、migration 018 recoverable work item、同 batch retry 和显式 200-candidate warning。
- 全局 Runtime Agent JSONL 已落：per-Execution 文件，按 role/name/invocation 区分 Agent，覆盖模型、Tool、context summary 和 Execution 边界，写失败 fail-open。
- 自动回归：backend 477 passed；frontend 143 passed；production build 通过。原始本地 Mybatis artifact 的纯 sectioner 验证通过；按用户要求未再调用真实 Provider。
- 当前 R3 下一产品任务仍为 Task 8；本增量不声明 R2 Provider/browser acceptance 已完成。
- 用户随后从页面触发真实 retry：Execution `75f5ac8e-0d20-48d8-b7f5-8aa89e4bd69b` 完成 discovery units 0–3，在 unit 4 因模型对同一允许 `source_ref` 返回多个 seed 而失败；这证明原“无结构化输出”故障已越过，但暴露了新的输出容错缺口。
- 已把 discovery/enrichment 的重复允许引用改为稳定保留首项，未知引用继续拒绝；JSONL serializer 显式支持 LangChain `ModelResponse`。新增/关联定向 `58 passed`，`git diff --check` 通过。
- 卡死的旧 8000 开发进程已精确终止，修复后后端与 5173 前端重新启动；`/api/health` 返回 ok、前端 HTTP 200。未由 Codex 自动重放原始正文，完整 batch 仍待用户显式重试。
- 修正整理运行态的语义色：`正在识别题目/正在补全候选` 使用独立 `curation-progress` 主色样式和 `role=status`，`Agent 执行失败` 继续使用 danger 样式；前端定向 `7 passed`、TypeScript 与 `git diff --check` 通过。

## 2026-07-22：题目整理长任务 Task 7 自动验收

- 后端跨层场景使用 18 个明确题目形成 6 个 enrichment Work Item：第一波 barrier 实测 peak=3，两项完成、一项失败；第一次恢复跳过两项 completed，在三项调用活动时暂停；关闭并重建 AgentApplication、执行 recover 后再次恢复，最终最后一项 completed、所有 Work Item 均非 running。
- 有效 RED：fixture 校正后，新增场景只在 `final_batch.status` 失败，实际为遗留 `completed`、期望为设计规定的 `review_pending`。最小修正 finalization 状态和既有仓储/API 断言后，同一场景 `1 passed`。
- 前端新增 interrupted→resume→乱序资源契约，首次运行即 `1 passed`，证明 Task 6 的阶段防回退、单调计数与 provisional 合并已经满足验收，不额外修改生产 UI。
- 受影响回归：后端计划列出的 9 个套件 `152 passed`；前端 QuestionCatalog、CurationRuntimePanel、reviewApi、useAgentEvents `49 passed`。
- 完整回归第一次为后端 `629 passed, 1 failed`，唯一失败是旧 question-batch API 仍断言生成终态 `completed`；更新为 `review_pending` 并定向通过后，第二次/最终后端 `630 passed`（1 条既有 Starlette/httpx 弃用 warning）。前端完整 `166 passed`。
- `./node_modules/.bin/tsc --noEmit` 通过；`npm run build` 成功（保留既有 652.55 kB chunk 提示）。记录时间：2026-07-22 07:28 CST（UTC+08:00）。
- 产品成熟度：单进程 bounded scheduler，不是分布式 jobs；真实 Provider 性能、浏览器暂停/刷新/恢复/终止和真实材料完整运行未执行，也未声称通过。下一产品任务回到 R3 Task 8；非阻塞练习见本地 verification 指南。
