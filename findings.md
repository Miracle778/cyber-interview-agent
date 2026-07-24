# Agent Runtime 框架收敛关键发现

## 2026-07-21 GLM-5.2 题目整理失败

- `reasoning_effort=none` 不能在所有 OpenAI-compatible Provider 上统一解释为“省略参数”：GLM-5.2 省略 Thinking 参数会默认开启推理。模型能力适配必须在 resolver 层显式映射，不能依赖通用协议默认值。
- 当前可靠映射是 GLM 4.5+ / 5.x：`none -> thinking.disabled`，非 none -> `thinking.enabled + reasoning_effort`；未知 OpenAI-compatible 模型保持原请求形状，避免发送不支持的 GLM 扩展字段。
- 模型输出预算应按角色收紧。题目生成需要 8,192 token 容纳 ToolStrategy JSON，但评价、聊天等角色不应被同一全局上限扩大。
- role thread 既要隔离也要可恢复：随机 UUID 会制造不可重放 checkpoint；题目分块使用 session + execution run + unit index，避免跨重试和跨块累积，同时保持同一 execution 的确定性命名。
- “每块最多 4,000 字符”必须覆盖无换行长文本；仅按行 flush 不能建立硬上限。
- 最小真实 Ark 调用证明 `thinking.type=disabled` 可在 `/coding/v3` 上恢复结构化 tool call；多块长生成仍有明显 Provider 延迟，功能正确性与性能验收必须分开记录。

## 2026-07-20 R3 实施扩展点

- R3 应建立独立 `app/profile` 领域包，但复用现有 Workspace Runtime、Session/Execution/Event、Middleware、HITL 和 Knowledge Publication；另建 Graph registry 或执行引擎会制造第二套恢复与审计语义。
- 现有 `agent_runs`、`agent_events` 和 `tool_audits` 都强制依赖 Session。为满足无上传对话又保留恢复能力，每个材料版本使用 `session_id == material_version_id` 的隐藏 system Session，并从通用列表/详情中隔离。
- 当前模型绑定只有四个用途；R3 新增 `profile_extraction` 和 `profile_assessment`，Planner 首版复用 assessment，Chat 复用 `agent_chat`，因此设置页和完整绑定校验必须同步变为六项。
- 当前 Knowledge Publication 只支持发布，不支持撤回；R3 需要基于已发布哈希的可恢复 revoke 状态机，同时删除 active 文件和搜索索引，保留无敏感正文的历史与 Receipt。
- 已确认规格的 Tool allowlist 是八个只读业务查询；Tool 产品 Event 只有 started/completed/failed，denied 作为 Audit 状态并投影为 failed + `tool_not_allowed`，原始参数和结果不进入 SSE。
- 实施计划按 18 个顺序 TDD Task 拆成 R3.1-R3.4 四个检查点，状态真相保留在领域表，默认 AgentState/checkpoint 只持有可恢复编排状态。

> 2026-07-24 路线调整：本节关于“R3 必须补齐画像知识发布/撤销”的判断被后文“求职目标中心产品路线”取代；相关 schema 可作为未来扩展保留，但不再属于 R3.4 的产品门禁。

## 2026-07-20 R3 Task 1-5 实现审查修正

- Profile Repository 的所有外部稳定 ID 都必须重新校验 Workspace 归属；仅验证 Evidence 属于当前材料版本不足以阻止 Proposal 指向另一 Workspace 的 Claim/ClaimVersion，PublicationSelection 也必须只接受当前 Workspace 的当前 confirmed ClaimVersion。
- “同一 Workspace + primary_role 只有一个 active Material”需要数据库 partial unique index和 restore 前显式冲突检查双保险；archive、restore、切换当前版本同时推进 aggregate version。
- Claim Proposal 创建、决定和 PublicationSelection 使用统一 `profile_idempotency_receipts`：同 key/同请求返回原结果，同 key/异请求返回稳定冲突，不能把“已经决定”误写成幂等。
- 内容寻址存储不能自行判断数据库引用；`delete_ref` 必须要求调用方提供剩余引用数，有引用时拒绝 unlink。实际永久删除仍由后续 deletion service 先查询引用、再调用存储。
- `profile.ingest` system Session 不仅要从 list/detail 隐藏，也必须从通用 delete/restore/cancel 定位器隔离；内部摄入服务继续通过 Workspace Runtime repository 访问。
- Workspace Runtime 创建 ProfileService 前必须初始化 `artifacts/profile/materials/{blobs,text}`；测试 fixture 手工建目录不能替代生产初始化。
- 空 PDF、DOCX、Markdown 和 text 使用同一 `profile_no_extractable_text` 语义；Action Plan status SQL 只能更新 schema 中真实存在的列，Item 执行必须校验 Claim expected version。
- Claude 在 Task 3 提交中加入的两个非 R3 ADR 含未确认结论和过期路径，已从本分支移除；架构决定只保留用户确认且路径有效的正式 ADR。

## 2026-07-20 R3 Task 6 Tool 边界

- Profile Tool 不能复用通用任意路径 reader：即使有 `ToolPolicyMiddleware`，稳定资源 ID 的 handler 仍需通过关联查询验证当前 Workspace、active material 和非 tombstone Evidence，形成纵深防御。
- 预算必须同时约束总调用次数与规范化重复调用；仅使用官方 `ToolCallLimitMiddleware(run_limit=6)` 无法识别参数键顺序等价的重复调用，因此增加 Profile 专用 guard，并在统一 stack 中保留显式插槽。
- Tool 输出上限属于服务端上下文契约，不应交给模型自报；R3 固定为最多 50 项、单条摘录 2,000 字符，并通过 `AgentContext` 只允许服务端进一步收紧。
- 发布状态读取来自 `profile_publications` 领域事实；未发布返回显式 `unpublished`，不把 PublicationSelection draft 伪装成已发布事实。

## 2026-07-20 R3 Task 7 Graph 与恢复边界

- 隐藏 system Session 只是满足 Runtime 外键和恢复语义的容器；创建 `agent_runs` 后仍必须交给统一 Execution scheduler，否则数据库会永久保留没有实际 task 的 running 假象。
- 原文解析结果不能放入外层 Graph state。节点从不可变 blob 重建确定性片段，原文只写私有 text artifact；checkpoint 只保存 ID、计数和严格结构化输出，重试从持久 Evidence/Proposal receipt 恢复。
- Ingest Proposal 幂等键必须稳定绑定 MaterialVersion，而不是每次重试的新 Execution ID；否则“写入成功、Event 失败”的重试会生成重复候选。created_by_execution_id 是审计归因，不属于幂等请求正文。
- Assessment 在保存前必须预校验所有 Evidence、material version、proposal target/base 和 snapshot version；只在完整校验后写 Assessment/Proposal，并由 typed-card projector 自身做 resource ID 去重。

## 2026-07-22 R3 Task 8 API 边界

- 非 Workspace 路径的材料/版本接口必须显式携带 `workspaceId`，并通过 MaterialVersion → Material 关联再次校验归属；稳定 ID 不能替代 Workspace 授权。
- Profile API 只投影安全文件名、处理阶段、Evidence locator/有界 excerpt、Proposal 计数和隐藏 ingest Execution 摘要；`storage_ref`、`text_ref`、完整标准化文本与 system Session ID 不进入响应。
- 上传、追加版本、重试和材料生命周期写入使用 `Idempotency-Key`；归档、恢复、主版本切换同时校验 Material aggregate `expectedVersion`。相同 key/相同请求返回原 Operation 标识，不同请求稳定冲突。
- `profile.ingest` 重试路由必须运行在异步 handler 中；若由同步 FastAPI handler 的线程池调用 scheduler，`asyncio.create_task` 无法取得主事件循环。

## 2026-07-22 R3 Task 9 页面与失败恢复边界

- `/profile` 使用现有 App Shell 和设计 Token；材料总览、版本工作区与 Evidence 详情是领域资源页面，不模拟聊天。桌面保持版本列表/主区/操作栏，767px 以下改为单列卡片。
- multipart 客户端必须让浏览器生成 boundary，不能复用 JSON `Content-Type`；`apiUpload` 同时保留 error envelope、AbortSignal 和幂等 Header。
- 处理阶段固定投影为“上传、文本提取、脱敏、Claim 提取、等待审核”，红色只用于真实终态失败；失败文案必须说明原文件和已完成步骤已保存。
- 浏览器暴露了自动测试未覆盖的跨层缺口：Graph 在首节点前因模型绑定缺失而失败时，Execution 已终止但 MaterialVersion 仍是 `uploaded/parsing`，前端会无限轮询。Execution failure handler 现在同步写入 retryable material 终态，页面显示配置模型后继续，无需重新上传。
- 响应式验收以 `documentElement.scrollWidth === clientWidth` 为硬证据；390、768、1024、1440 四档均无页面级横向滚动，console 无 warning/error。

## 2026-07-22 R3 Task 10 Claim 审核与安全删除边界

- 删除预检不是临时确认框，而是 15 分钟有效、可跨进程恢复的领域快照；因此新增持久 `profile_deletion_plans`，并锁定材料 aggregate version、Evidence、ClaimVersion、待决 Proposal、发布选择和活动发布关系。任一关系变化都返回 409，要求重新预检。
- Proposal 接受时必须再次校验 Evidence 仍属于当前 Workspace 且未 tombstone；仅在创建 Proposal 时校验无法覆盖“预检后并发接受/删除”的竞态。
- 永久删除先处理依赖发布，再在单事务中更新 Claim 支持状态或删除未受选择保护的 Claim、清空并 tombstone Evidence、标记材料删除；数据库保留无敏感正文的审计骨架，私有 artifact 在提交后按引用计数清理。
- 删除使用 item receipt 和幂等 operation receipt。artifact 清理失败时保存已完成阶段，重试只继续未完成清理，不重复 ClaimVersion、Evidence 或材料变更。
- Active Knowledge 的正式撤销状态机属于 Task 16；Task 10 只定义显式 revoker 协作接口。存在活动发布但尚未注入 revoker 时安全返回可重试冲突，不伪装撤销成功。

## 2026-07-22 R3 Task 11 Claim 审核交互边界

- 审核工作台直接投影 Claim/Proposal/Evidence 领域资源：队列负责筛选和状态，主区负责当前值与建议值对比，Evidence 按 materialVersionId 打开对应版本，避免把旧版本证据误标成当前简历。
- 批量选择在服务端回执前始终保留；部分冲突只移除 completed 项，冲突项继续留在选择中并刷新快照，避免用户重新勾选未受影响项目。
- 冲突、待确认和删除风险都使用图标加明确文案，不依赖颜色。永久删除与归档分开表达，必须先完成依赖预检、逐 Claim 选择、活动发布撤销确认和“永久删除”文本确认。
- 模态框打开后焦点进入关闭按钮，Tab 保持在框内，Escape 关闭并返回触发按钮；真实 1280/390px 页面无横向溢出，console 无 warning/error。

## 2026-07-22 R3 Task 12 Assessment 与受约束 Plan-and-Execute

- Assessment 只接受当前 confirmed profile snapshot，并递归校验结构化结果中的 Evidence ID；没有引用、引用已 tombstone 或快照过期都不能持久化，Assessment 文本不会自动成为 Claim。
- Action Plan 只接受六个显式 operation，创建前一次性校验顺序、目标、before snapshot、expected Claim version 和 Evidence；dispatch 使用固定分支，没有反射、任意方法名、代码执行、自由路径或直接知识发布。
- 每个 Item 独立记录 completed/failed/receipt，整体状态由逐项事实归并。重试只执行 failed/pending，completed 的 Receipt 保持不变；创建 Proposal 和 PublicationSelection 继续使用领域幂等键。
- 派生简历用稳定 `action-plan:<plan>:<item>` creator 标识恢复中间状态；即使“版本已创建、文本未写完”失败，重试复用同一 derived_draft，不制造重复版本，确认执行完成后才切为当前版本。
- `profile.action_plan.created/item_completed` Event 只含 plan/item ID、operation、ordinal、status 和计数；不包含 before/after、Evidence 正文或模型推理。

## 2026-07-23 R3 Task 13 Profile Manage 上下文与恢复边界

- `profile.manage` 的领域事实和对话记忆必须分开：每轮从 Repository 重建 confirmed snapshot 与稳定 focus ID；聊天历史由 `<session>:profile_chat` checkpoint 和既有 compaction 管理，不能再把产品消息全量拼进 Prompt，否则会与 Agent checkpoint 重复并放大 Token。
- 外层 Graph 使用 session thread，Chat/Assessment 使用 session 派生 thread，Planner 使用 execution 派生 thread。Planner 不继承跨 Execution 隐藏状态，唯一可恢复产物是持久 Action Plan。
- Runtime 的完整 Profile Tool 集只是服务端上限；Graph 再按问题是否涉及证据、版本或知识状态缩小 allowlist，并同时收紧 scope。模型无法通过输入扩大权限，Assessment 和 Planner 默认零 Tool。
- 同一 session checkpoint 会跨轮合并 state，因此每轮 assemble 必须显式清空旧 response/assessment/plan ID，并把 `text` 规范化为当前 `message`；否则上一轮终态可能泄漏到下一轮响应。
- Action Plan 必须按 execution ID 幂等，而不仅是 Item 执行幂等。这样进程在“计划已持久化、Execution 尚未完成”之间退出时，恢复不会生成第二份计划或重复 created Event。
- 无法确定目标、空计划或单项请求被模型扩展为多项时，安全返回澄清文本且不持久化；领域版本/Evidence 校验失败仍由服务端拒绝，模型永远不获得写工具。

## 2026-07-23 R3 Task 14 Profile Manage API 边界

- Profile 会话不是第二套 Runtime：只新增限定 `kind='profile.manage'` 的创建/列表入口，Execution、Cancel、Event replay/SSE、消息和 usage 继续使用 `/api/agent` 统一协议。
- `profile.ingest` 与 `profile.assess` 是 system Session，必须在通用用户创建入口显式拒绝；仅依赖“列表隐藏”不足以阻止用户伪造可执行 system graph。
- Action Plan 卡片只保存资源 ID 和安全摘要，完整 diff、Evidence、Receipt、stale/capability 每次从领域资源 API 读取，避免把可变计划状态复制进消息 payload。
- Plan GET 同时返回 base/current profile version；Confirm 再做服务端 freshness 校验。前端展示的 `canConfirm=false` 只是交互提示，真正并发保护仍是 expected plan version + profile snapshot 的 409。
- 重启恢复的验收对象是领域 Plan/Item/Receipt，不是模型 checkpoint：应用在计划创建后重启，确认仍执行固定领域 dispatch；再次重启读取到相同 Receipt，证明没有依赖进程内对象。

## 2026-07-20 Agent State 与 Context Offload 边界

- 自定义 `state_schema` 只用于单一 `create_agent` 循环中产生、被后续步骤消费、需随 checkpoint 恢复且不属于领域事实的可变工作状态；输入、输出、可信权限、业务状态和跨 Session 记忆分别归消息/response、`context_schema`、领域层和 Store。
- R2 role Agent 只需要默认 `AgentState`；轮次和发布状态由外层 Graph/领域 repository 拥有，因此 `AgentFactory` 未传 `state_schema` 是明确分层结果。
- 当前具备摘要 compaction、ToolMessage 清理和领域 ContextAssembler，但没有“持久 artifact ref + 可重读”的通用 Context Offload；把 ToolMessage 变成 `[cleared]` 不算完整 Offload。
- R3 先落领域 Evidence Offload：个人材料正文留在版本化 evidence store，上下文保存 ID、版本、摘要和 evidence ref，通过 `T1` Tool 有界读取；通用 Runtime Artifact Offload 等三个以上真实角色出现共同需求后再建设。

## 2026-07-20 全路线 Agent 能力分配

- R0-R8 不应统一启用 Tool、Time Travel 或自主 Planner：已知上下文的提取、评价、分类和总结保持无业务工具，只有 R3-R6 跨材料探索角色按 role 启用有界只读工具。
- 所有领域写入、删除、发布、掌握度、Todo 和外部消息继续由应用服务或显式 Graph 执行；复杂变更采用结构化 proposal、版本校验、差异确认和幂等 receipt，不给模型自由写工具。
- 全路线核心产品均不需要通用 Time Travel；长流程使用 checkpoint 恢复与产品事件回放，长期资产使用领域版本，重做通过绑定不可变快照的新 Session/execution 表达。
- Plan-and-Execute 分为固定领域 Graph、结构化变更计划、有界只读探索和 R6 固定单子 Agent 委派；不建设通用自主 Planner 或任意动态 supervisor。
- 正式决定记录为 `docs/superpowers/architecture-decisions/2026-07-20-agent-capability-allocation-across-roadmap.md`。

## 2026-07-20 领域 Agent 工具与写入边界

- R2 生产 Agent 当前均未启用业务工具：题目整理、命令解释、评价、报告和讨论接收应用层组装的有界输入；`ToolStrategy` 只负责结构化输出，不等同于领域工具。
- `question_tools`、`discussion_tools` 是扩展点，Runtime 仍具备 BaseTool、ToolPolicy、Workspace scope 与审计能力，但实际 execution context 的 allowlist 为空。
- R3 不能简单复制“全部无工具”：跨多份个人材料探索证据时允许角色级最小只读工具，并使用稳定资源 ID/evidence ref，禁止任意路径和未授权 scope。
- 修改画像、删除材料、设置主简历和发布知识不进入自由 ReAct 工具集；模型生成结构化 proposal，领域服务执行 `Validate -> Confirm -> Execute`，画像确认和知识发布保持两次独立授权。
- 正式决定记录为 `docs/superpowers/architecture-decisions/2026-07-20-domain-agent-tool-and-write-boundaries.md`。

## 2026-07-19 Agent 代码结构整理第一阶段

- 原 `agents/review.py`、`review_round.py`、`curation_command.py` 不能从文件名判断是单个 Agent 还是多个 runnable 聚合；现改为显式单数/复数 Agent 模块名，并将 `AgentFactory`、模型解析器和所有 Middleware 模块改为可搜索的语义名称。
- System Prompt 和 HumanMessage 输入渲染原本散落在 Agent 方法中；现集中到 `app/agents/prompts/`，每个 Prompt 具有稳定 ID、版本和独立 renderer。第一阶段只搬迁原文和等价渲染，不调整提示词行为。
- 四个 Agent 模块重复定义 `AgentRunnable` 和 role thread 配置；现统一为共享 protocol 与 `isolated_thread_config`，保持既有 `{session_id}:{namespace}` checkpoint 键不变。
- `CurationCommandModels` 实际拥有 classifier、summarizer、responder 三个 Agent runnable，已改名 `CurationCommandAgents`；单题 `ReviewAgents` 已改名 `SingleReviewAgents`，避免与轮次 Agent 混淆。
- 本阶段没有拆分 `ReviewApplication`、`ReviewRepository`、`AgentExecutionService`，也没有按 Agent 类型调整 middleware profile；这些属于后续高风险结构阶段。

## 2026-07-16 候选状态下钻与共享文件卡

- 右栏状态数字与会话总结消费同一份 `QuestionCandidate` 查询结果和同一组 mutation；共享组件负责表现一致，React Query/服务端继续作为状态真相。
- 右栏采用替换式下钻而不是原位无限展开：筛选列表占用运行概览位置并内部滚动；打开 Markdown 详情后关闭会返回原筛选条件。
- 右栏统计覆盖会话全部候选，未进入最新 summary 的候选标记“历史版本”，保证数量与列表一致且不伪造另一套状态。
- 1440×900 实页中右栏无自身滚动或横向溢出，文件列表高度 360px 内滚动，前三张卡片各 103px；控制台无 warning/error。

## 2026-07-19 整理会话总数与题目库口径

- 原“累计候选”按候选版本行计数，题目库则按 `groupLogicalQuestions` 展示逻辑题目；同题多个历史/候选版本会造成主页数字大于点击后的条目数。
- 整理会话主页现在直接复用题目库的逻辑归组结果：总数按 group 数，已发布按 group 的聚合状态计数。单个会话中的“候选数”仍表示该次整理生成的版本数，语义保持不变。

## 2026-07-16 题匠输入 Dock 视觉收敛

- 原输入区把模型、思考强度和回复框并列成表单，实际 textarea 只获得约一半横向空间，且 4px select 圆角与 16px 聊天框圆角形成两套视觉语言。
- 用户从三张效果图中选择紧凑聊天 Dock：textarea 成为主层级；模型与思考强度合并为一个渐进披露胶囊；发送为 44px 圆形主操作；停止态仍保留明确文字。
- `ui-ux-pro-max` 的营销紫色和夸张极简建议不适用于现有工作台；本次只采用渐进披露、统一圆角、44px 目标、可见 focus 和 390px 无横向溢出规则。
- 首轮 1280×720 局部复核不足：旧 `.curation-composer > div` 规则残留的 `align-items:center` 与 `justify-content:space-between` 让新 Grid 子项按内容宽度收缩；用户 Retina 截图对应的 903×689 视口因此出现发送按钮悬在中间的明显错误。
- 修正后 textarea 与 toolbar 显式横向 stretch，工具栏采用 `auto / 1fr / auto` 三列，空态提示缩短并以一行 textarea 起步。903×689 下输入 Dock 为 456.9×110px、发送按钮距右边 9px；1440px 保持同一边距，390px 无横向溢出，设置面板完整处于视口内，控制台 warning/error 为 0。

## 2026-07-16 整理右栏候选状态

- `session.stage=waiting_for_command` 是执行状态，不是用户可理解的“当前任务”；资料处理单元完成率也不等于候选题确认或发布进度，二者不应继续作为右栏主信息。
- 右栏改为消费选中会话的真实 candidate 资源，展示 draft/review_pending/published/rejected 汇总和最近更新题目；完整逐题文件操作仍由会话 timeline 的现有 artifact card 承担，避免两个区域重复承载同一任务。
- 原事件 effect 只读取最后一条 SSE，连续到达的 `publication.changed → execution.completed` 可能漏掉候选刷新；现改为一次消费全部未处理事件，并在 summary/command/publication/completion 后刷新 candidates，生成期间另有 1200ms fallback。
- 1280×720 实页下，候选卡、默认展开运行详情和提示同时显示时右栏 `clientHeight=scrollHeight=558px`，无右栏滚动、组件重叠或页面横向溢出。

## 2026-07-16 R2 可取消流式执行设计

- 通用 Agent Runtime 已有 execution、服务端 cancel、可重放 SSE 和 `assistant.delta`；缺口不是从零实现，而是整理命令同步 HTTP 链路绕过了这些能力。
- 可靠停止必须先持久化取消请求，再取消本地 task，并在模型与逐题发布之间设置安全点；AbortController 只能作为客户端请求清理，不能作为产品状态。
- 结构化意图分类的 JSON 不应展示或伪流式；只有面向用户的真实自然语言模型 chunk 才投影为 `assistant.delta`。
- 运行恢复不自动重复模型或发布副作用；遗留运行进入 interrupted，持久化取消请求进入 cancelled，用户显式重试创建新 execution。
- 单题发布事务一旦开始就完成当前题，停止只阻止后续题；批量重试只处理失败/未完成项并复用题目级幂等键。
- `task.cancel()` 不能无条件用于领域任务：模型等待阶段可立即取消，单题发布关键区必须只记录请求并在退出安全点后终止。
- graceful shutdown 与用户停止共享关键区边界，但终态不同：用户停止落 cancelled；无用户取消请求的进程关闭落 interrupted，供显式恢复。
- 首字等待的根因不是 SSE 人工切片，而是普通问答先同步完成 structured classifier，长上下文还可能先同步完成 summarizer；随后才启动第二次 responder 流。
- 安全路由应默认把不含副作用词的输入交给无工具 responder；漏识别的动作同义词最多得到解释，不可能绕过领域服务产生副作用。发布、拒绝、重写、生成、修改、删除、合并等词仍进入 classifier。
- classifier 只保留结构化 selector/feedback/clarification，删除重复生成普通回答的 `response`；普通问答的 overflow 摘要在 responder 首个 chunk 之后完成。

## 2026-07-15 Agent 上下文组装设计

- 固定最近 8 条消息只能修复近距离指代，不能作为正式记忆架构；正式方案使用 token 预算、完整 turn、结构化摘要、持久领域焦点和按需资源注入。
- 意图识别是常见分类步骤，但当前题库整理没有跨领域路由、工具循环或长期自主任务；`CurationIntentAgent` 应收敛为确定性 parser + 一次性 structured classifier 的 `CurationCommandInterpreter`。
- ContextAssembler 只负责通用预算与材料选择；candidate/JD/resume 等焦点、领域查询和副作用分别属于领域 adapter、repository 与 application/Graph，禁止形成持有全部 Runtime 状态的大中间件。
- 架构选型采用一项决定一份 ADR；涉及长期、跨阶段、状态所有权、安全或技术栈的取舍时先询问用户是否记录，局部可逆实现细节不触发询问。

## 2026-07-15 Agent 上下文组装实施结论

- 固定 `[-8:]` 消息窗口已从题库整理命令链路删除；连续指代由 `review_curation_context` 的稳定 candidate ID 焦点负责，产品 timeline 只作为首次恢复和完整 turn 材料。
- 明确序号、recommended 范围和唯一焦点指代在 application 内零模型完成；复杂自由表达才组装 token-budget prompt 并调用无工具、无 checkpoint 的 structured classifier。
- 压缩只处理预算外的早期完整 turn。成功后 CAS 推进结构化摘要和 cursor；失败只记录 `curation_context_summary_failed`，保留旧 cursor 并继续使用最近完整 turn。
- 幂等 receipt 在解释、压缩和焦点写入前查询；重复请求不会再次调用模型或推进 context version。焦点只依据 inspect、实际发布/拒绝/重写结果更新，普通澄清不创造焦点。
- 应用投影的 `currentTokens/thresholdTokens/contextCompacted` 来自实际 assembled prompt 与压缩结果，不再以消息条数推算；classifier 与 summarizer 仍受既有 middleware、usage、loop guard 和 observability 治理。

## 2026-07-15 R2 题库与 Agent 可用性补强（待验证假设）

- “思考过程”只能展示可公开的执行阶段、当前动作、耗时和重试信息，不能展示模型 Chain of Thought。
- 删除默认采用软删除并允许恢复；硬删除是显式高级操作，必须二次确认，并在活动 execution 或受发布题/复习快照引用时阻止或采用受控级联，不能直接散落 SQL DELETE。
- 题库视图采用 topic → 难度 → 题目层级，搜索和状态筛选仍可直接缩小集合；详情阅读与编辑从层级叶子进入。
- AI 重写必须绑定候选题的原 curation session，向同一 session/thread 追加有界命令和消息；没有来源会话的历史数据才创建迁移会话并明确标记。
- 相似题合并不应让多个自由 subagent 直接互相写库。推荐采用确定性召回/分组 + 可并行的只读结构化 merge worker + 单一 reducer/领域服务提交，最终保留所有 source/evidence links 和 merge reason。
- 已确认候选题的后端详情、PATCH 编辑和前端渲染/原文/编辑模式已经存在；当前问题主要是题库入口平铺、候选选择不明显，以及重写仍走独立 candidate endpoint，未明确恢复原 curation session。
- 已确认 curation session command 已支持 `rewrite`，而 `QuestionDetailPanel` 的“重新整理”仍调用 `/question-candidates/{id}/rewrite` 返回新 batch；需要统一到 session-bound rewrite。
- 当前 schema 和 repository 未发现 session/source 的 `deleted_at` 或统一删除服务；生命周期功能需要新增迁移，不能只隐藏前端记录。
- 当前合并输入会携带 `similar_questions`，但具体召回算法、Agent 裁决与 reducer 写库边界仍需继续读取 `ReviewApplication`/question curation Graph 后确认。
- 已确认 `question.curate` 使用与复习轮次相同的官方 middleware stack：`ProjectingSummarizationMiddleware` 在 role thread 达到 24 条消息时压缩并保留 10 条，thread ID 稳定为 `{session_id}:question_generation`。因此整理 Agent 已具备上下文压缩，但 curation resource/UI 没有暴露 `context_compacted`，用户看不到。
- `agent_runs` 已持久化 `started_at`、`finished_at`、`error_code`、`error_message`；curation resource 当前只返回 execution ID/status，运行面板因此无法显示失败原因、耗时或重试条件。
- 当前 session 状态可归档但没有 `deleted_at`；session 子资源大多通过 FK cascade 删除，source 则被 draft/source-link/curation JSON 间接引用。硬删必须由应用服务先做引用检查，不能直接依赖 cascade。
- 当前题目生成 Agent 只对同一次生成结果做规范化题干完全相等去重并并集 `source_refs`；已发布题仅以文本提示给生成模型，没有确定性相似度召回、独立 merge contract 或单一 reducer。因此“相似题合并”目前不是可靠的语义合并实现。
- 已将合并实现收敛为确定性召回/归并：规范化 Unicode、标点和常见问句套话，topic 不相交时禁止自动合并，会话内高阈值才合并；active catalog 使用较低阈值只标记 `duplicateOfQuestionId`，仍需人工确认且绝不覆盖原题。
- 当前实现没有实际启动多个 merge subagent。正式扩展点允许并行只读 worker 返回结构化 decision，但数据库写入、来源并集和最终冲突处理始终由单一 reducer 负责，避免并发写入和证据丢失。


## R2 Claude 修复审阅后的修正

- Graph execution input 是内部调用参数，不等于产品用户消息；R2 curation/review/publication/discussion execution 禁止自动投影 input，用户命令、回答和可见卡片必须走 typed timeline projector。
- 既有开发数据库可能已保存旧的 curation input JSON；curation resource 只返回允许的 message kind，以及带稳定 `resourceId` 的用户 text，避免旧 source excerpts 继续伪装成用户对话。
- 响应式不能只调整列宽：对话必须在 DOM 中优先，900–1199px 使用对话/状态两栏，1200px 以上才启用会话/对话/状态三栏，窄屏按对话、会话、状态降级。
- 轮次 `currentIndex` 表示当前题位置，非“已完成数”；活动轮次应显示“第 N/M 题”，只有 completed 状态显示“M/M 已完成”。
- 早期提交上的全量结果不能覆盖后续 UI 提交；每次记录证据必须注明对应 HEAD，最终全量只在修复稳定后运行一次。

## R2 会话化交互 Task 3 发现

- 回答 HTTP 必须在原子持久化 input receipt、attempt 与用户 timeline 后返回 `202`；评价继续运行时，页面导航和历史切换不应被 mutation pending 锁住。
- SSE 只发送 round/attempt/version/阶段等失效通知；回答、参考答案、评价正文和模型异常正文都由受权限控制的资源接口读取，不能进入 event payload 或错误日志。
- 评价失败必须保留已接受回答与 checkpoint；重试命令使用 durable receipt 幂等，启动对账不能把 `evaluation_failed` 轮次错误收敛为失败。
- history-first 与刷新恢复不冲突：刷新先回历史首页，重新进入同一服务端 round 后，回答、评价卡与必要追问从 timeline 恢复。
- 最小真实浏览器链路中，回答气泡约 282ms 出现且导航可用，真实评价约 56.4s 完成；同时发现三栏左侧历史把 `waiting_for_input` 显示为“已完成”，列入 Task 4 UI 审计修复。

## R2 人工浏览器验收发现

- 后端为 question batch 创建 session 不等于用户获得会话体验；当前前端扁平聚合所有 candidate，只轮询一个 batch 状态，隐藏了读取、分片、生成、合并、总结和发布过程。
- `ReviewApplication.submit_answer` 在恢复 execution 后继续 `wait` 到 LLM 完成，导致 HTTP mutation 长时间 pending；聊天体验必须先原子持久化用户消息/attempt 并返回 `202`，再由 SSE 驱动阶段和最终卡片。
- 当前 active catalog 不持有完整 question-source 多对多关系；如果允许多文件和重复整理，相似题合并后必须有独立 source/evidence link，不能只保留 candidate 临时 JSON。
- 题库内容管理与 Agent 执行过程是两个不同任务，应分别放在“题目库”和“整理会话”；复习历史首页、创建设置和活动聊天也必须是显式页面状态，不能靠是否选中最新 round 隐式切换。
- “思考中”只能表达系统可观察阶段；结构化评价/报告校验后整体投影，内部 Chain of Thought 永不进入 SSE、timeline 或持久化。
- 整理命令不能只存在于前端聊天气泡：持久 command receipt 必须绑定 summary version 与 idempotency key；明确确认文本可直接复用现有 publication HITL 语义，含糊文本只生成澄清消息。
- 多来源相似题合并时，去重不能丢弃后续来源；candidate 可合并内容，但 source/evidence links 必须累加，才能支持重复整理与来源追溯。
- 题库工作台应默认读取 curation session 投影；旧 batch/candidate API 只继续服务独立“题目库”内容管理，不能再作为 Agent 过程 UI。

## R2 Task 4 验收发现

- 阶段编号不是稳定代码语义：`r2_contracts.py` 同时混放两个 Agent 输出域和 Graph state，已按 question curation、review round 与 Graph ownership 拆分，避免后续出现 `V3`/`R3` 式命名。
- “Provider 连通性 ok”不等于完整 Agent 合约通过：真实 GLM-5.2 对 12 题来源先后只返回 3、6 题；仅强化提示仍无法保证结构化数组完整覆盖。
- 对可识别的编号题源，应按语义条目分片而不是无限重试整段提示；每 6 题调用后聚合并按题干去重，真实同批稳定得到并发布 11 个候选。
- 长模型调用不能让 batch 永久 `generating`：启动恢复必须把 interrupted/failed/cancelled execution 对应的生成批次和 running round 收敛到 `failed`。
- checkpoint 安全白名单必须包含 Graph 实际持久化的 strict Pydantic structured response；“外层已转 dict”不代表 role Agent 内部 checkpoint 不会保存原对象。
- 真实十题完成了两次重启、报告发布、派生讨论与 weak-point 选题，但 19 calls 消耗 102094 tokens；下一轮成本优化应隔离 evaluator 历史并收紧追问门槛。
- 最终回归发现的两个前端失败均是顶层测试仍断言已删除的 FlowSummary/旧引导链接；更新到 R2 setup/空态契约后 84/84 通过。
- 当前阻塞与 Langfuse 无关；本轮按约定没有配置或启动 Langfuse。

## R2 Task 3 实施发现

- question batch、candidate、active catalog 必须分别建模：上传只登记 source，Agent 输出落 candidate/draft，只有发布 receipt 才进入 active catalog。
- candidate 详情需要返回已发布重复题的结构化快照；只给 duplicate ID 无法支持人工比较。
- 模型产生的 source refs 只能引用当前 batch 的 source ID 或其 `sourceId#fragment`，否则回退到批次来源，避免伪造跨文档证据。
- 页面筛选必须真实传给服务端，来源证据和批次状态也必须来自资源接口；SSE 只触发 Query invalidation。
- completed round 只显示结果，不能同时重新打开创建表单；离开/继续依靠服务端 round/input facts。
- 当前浏览器插件与 Node 控制运行时存在初始化冲突：导入官方 browser client 即在其 `globalThis.process = processShim` 处抛出 `Cannot redefine property: process`。这是验收工具阻塞，不是项目页面错误；服务可达不能替代交互浏览器证据。

## R2 整理会话 UI 与回收站补强

- 整理会话与复习轮次应共享“历史首页 → 聚焦会话”的主交互，不应进入页面后自动选中第一条记录；这样创建入口、历史恢复和当前 Agent 工作区的职责更清楚。
- 重复/正在整理资料是可继续执行的提醒，不是阻断条件；运行侧只保留默认折叠的“资料提示”，避免挤压执行过程。
- 软删除若没有可发现入口就不构成完整生命周期；题库工具栏统一提供回收站，分别列出整理会话与原材料，并提供恢复和受引用保护的永久删除。
- 回收站查询必须显式使用 `deletedOnly`，普通列表仍只返回未删除资源；后端资源 DTO 同时暴露 `deletedAt` 作为可恢复事实。
- 旧三栏样式给 `.curation-conversation` 和 `.curation-runtime-panel` 保留了命名 `grid-area`；新聚焦工作区没有定义这些命名区域，浏览器把两者放进同一隐式网格位置，造成完全重叠。新容器必须显式重置 `grid-area` 并指定行列，不能只改 `grid-template-columns`。
- 历史页切入会话时不能保留用户在长列表中的滚动位置；应在聚焦工作区渲染后自动定位。复习右侧反馈栏也必须在固定视口高度内独立滚动，否则其内容会把 520px 对话区所在整行撑高到约 799px。
- 外层页面定位到工作区不等于聊天记录定位正确；复习和整理消息列表都必须在会话切换、消息新增及结构化总结更新后，于布局完成时把内部滚动位置校准到最新记录。
- 整理运行状态栏应采用渐进披露：当前阶段、整体进度、候选/待确认/已发布、耗时和 Token 是首屏扫描信息；执行状态、调用次数、上下文、阶段历史和资料警告属于按需展开信息。失败原因与重试是例外，必须始终可见。
- 固定高度 flex 状态栏中的原生 `details` 默认允许收缩；多个区域展开时正文会被压到标题高度并裁切，形成视觉重叠。详情项必须 `flex-shrink: 0`，并使用单开手风琴控制信息密度，溢出交给状态栏自身滚动。

## R2 Task 1 实施发现

- generation 2 可在保留数据的情况下引入有序 `runtime_schema_migrations`；fresh 与既有 generation-2 数据库都记录 baseline 1 后应用 R2 migration 2。
- `waiting_for_input` 必须同时进入 session/run CHECK 和单 session 活动 execution 唯一索引，才能与审批等待并列恢复。
- 题目候选与 active catalog 是不同事实：只有 publication receipt 与最终 draft version/hash 匹配时才投影 active question。
- round 在创建时持久化 question snapshots、model/reasoning settings 和 mastery-before；后续 catalog 编辑不改变进行中轮次。
- answer 幂等只持久化 value hash 和安全 receipt，不保存第二份明文答案；不同 idempotency key 在已解决 request 上稳定冲突。
- mastery proposal 以结构化 report proposal + expected version 做 CAS；不解析 Vault Markdown 作为领域事实。
- R2 长轮次应由领域 Graph 决定顺序、追问门槛、推进和完成；role Agent 只生成结构化评价/报告，不能控制 current index。
- input interrupt 与 approval interrupt 必须按 payload 分类并投影不同产品状态；重复 receipt 在恢复 Graph 前短路，避免二次评价和推进。
- no-progress 指纹只看模型文本会把不同题目的相似评价误判为循环；review profile 需加入 round/index/input request scope，同时沿用唯一 middleware pipeline。

## R2 UI 设计契约发现

- 当前 R2 以无 Langfuse 为默认运行与验收环境；不要求容器、登录、trace 查询或不可达端点测试，观测接入保持可选且不得成为业务依赖。
- “题库整理”是复习流程的上游一级能力，不能藏在知识库上传或复习历史中；“开始复习”是下游一级入口。
- 题库整理需要统一候选资源，而 active question catalog 仍只包含已发布题目；两者不能共用一个含糊列表状态。
- 复习轮次和题库整理都适合桌面三段布局，但区域职责不同：前者是会话/对话/运行状态，后者是导航/列表/详情。
- Markdown 阅读态默认渲染；原文只在编辑或显式原文标签下出现。
- HITL/确认卡必须绑定真实 pending decision；普通答题 input、浏览和已整理题目不显示占位确认模块。
- 效果图中的模型与思考强度必须落到服务端验证并冻结的 round 配置，不能只是前端下拉框。
- 为支撑刷新恢复，R2 API 需补 question batch 列表/详情与 candidate 搜索/筛选/详情/编辑；active questions API 继续只服务已发布 catalog。

## R8 Channel 与 R2 拆解发现

- 用户原始需求中的“移动端”是微信、飞书等原生聊天 Channel，不是 375px 移动浏览器；响应式 Web 可以保留为 UI 质量要求，但不得作为 R8 需求已满足的证据。
- R8 应建立外部账号/会话到内部 workspace/session 的可信绑定，把文本、命令、审批和产物通知转换为同一 application service 调用；不能复制 Agent、Graph、HITL 或知识发布逻辑。
- 当前 R2 正式设计已经覆盖题库整理、多题轮次、追问、报告、全局掌握度和派生讨论，但没有 implementation plan。
- R2 的“完整可用”是 Web 复习功能闭环；微信/飞书原生对话留到 R8，简历/JD/面试能力留在各自阶段。
- R8 总路线已改为微信/飞书原生对话 Channel：Channel Adapter 只负责 transport、可信身份/session 映射、平台交互降级和投递可靠性，内部继续复用同一 application service 与 Agent Harness。
- R8 验收必须有真实微信/飞书聊天证据；375px Web 页面不能替代 Channel 验收。
- R2 实施适合四个纵向任务：领域事实与迁移、Agent/Graph 与输入恢复、API/Web 闭环、真实验收与文档；每个任务都包含自己的测试和提交边界。
- 现有 execution 只区分审批等待，R2 必须增加 `waiting_for_input` 并按 interrupt payload 区分领域输入与 pending action，复用同一 checkpoint/execution。
- 当前 Runtime generation 2 没有增量迁移历史；R2 必须增加有序 migration history 并保留现有数据，不能再次通过 generation 不兼容清库。

## 后续路线对齐发现

- 总路线的 AgentMiddleware 权威规则已更新，但 R2 仍写“复用 Middleware 1.0”，底部“当前下一步”仍停留在 R0。
- R2–R8 只有路线图级需求，没有按新 Harness 编写的独立阶段 spec/plan；本轮只补 R2 spec。
- 已完成的 R1.2/R1.3/R1.4/R1.5/R1.6 和 Middleware 计划仍包含已删除的 `RunManager`、`AgentRuntime`、`GraphBuildContext`、Gateway、Registry/Executor 和 pipeline。
- 历史文档应保留当时事实，不做伪造式重写；统一增加“历史实现、禁止作为未来模板”标记，并链接当前权威设计。
- 后续阶段必须按 domain StateGraph、role Agent、标准工具、官方 middleware、LangGraph thread/checkpoint、产品投影和领域副作用七个边界设计。
- R7 主要是产品/知识库工程，R8 是 transport channel；不能为了统一而强行建立新 Agent Runtime。

## 开发期 Runtime 数据库启动问题

- `IncompatibleRuntimeDatabaseError` 来自框架收敛 Task 4，不是发布版本兼容逻辑。
- 本机注册的 demo 与 demo1 workspace 含 `runtime_schema_migrations`，属于重构前测试 schema；demo2 尚无数据库。
- 原实现把“允许丢弃测试数据”错误落成永久人工删除门禁，并使用了误导性的“旧版”异常和文案。
- 正确边界：已知开发 schema 先备份再重建；未知数据库原样保留并停止，避免把损坏或外部数据当测试数据删除。

## 架构

- `create_agent`、官方 `AgentMiddleware`、标准 `BaseTool`、LangGraph checkpoint/interrupt/stream 已成为唯一执行协议。
- domain StateGraph 仍负责评价、报告、草稿、审批和发布的业务拓扑；Vault/索引/补偿不进入通用 middleware。
- application 层只投影 session、execution、action、event、usage、draft、publication 与 audit，不镜像内部 Graph state。
- 新 schema 故意不兼容旧 Runtime；当前无用户数据，不建设迁移桥。

## 状态与恢复

- 外层 Graph thread 使用 session ID；评价和报告 Agent 分别使用派生 role thread，避免消息与 summary 污染。
- 真实压缩在新会话第 11 次 execution 触发；checkpoint 分组为外层 `66`、两个 role 各 `121` 条。
- HITL action 是产品投影，恢复事实由 LangGraph checkpoint 拥有；批准/拒绝通过官方 `Command(resume=...)`。
- 产品事件必须复用 ProductRepository 连接；独立 aiosqlite 写连接会与同步 repository 竞争锁。

## Provider 与安全

- 未知 OpenAI-compatible 模型不一定支持原生 `json_schema`；Pydantic response format 使用官方 `ToolStrategy`。
- 真实验收：`ChatOpenAI` 结构化评分 `good`；`ChatAnthropic` 流式报告 21 chunks。
- secret 只在 resolver 从环境/keyring 读取，不进入 AgentContext、Graph state、事件、repr 或错误响应。
- 标题、summary 指示器和 observability 是 fail-open 投影；路径/scope/limits/no-progress/hash conflict 是硬边界。

## 前端与验收

- 前端契约统一为 session/execution/action/event，旧 `graphId`、`/runs`、`latestRun` 和产品 `runId` 已清除。
- SSE 收到新 `execution.started` 时清理旧失败；draft 创建后立即投影 `review_pending`，批准后展示 publication target path。
- 浏览器实际覆盖桌面、375px、刷新、approve、reject、duplicate decision、后端 restart 与 Vault 发布。
- 本机 Langfuse 没有作为当前阶段业务依赖；内存 exporter 覆盖正常导出，不可连接 OTLP 覆盖真实 fail-open。

## 环境

- 当前 worktree 的临时 uv venv 不完整；最终测试复用锁定依赖的 Middleware worktree venv，并显式设置当前 backend `PYTHONPATH`。
- frontend `node_modules` 是指向主仓库已安装依赖的本地软链接，不纳入提交。
- 独立 `npm run typecheck` script 不存在；`npm run build` 先执行 `tsc`，因此构建成功即类型检查证据。

## 2026-07-15：整理会话执行反馈布局

- 执行阶段是 Agent 对话的一部分，不应在右侧状态栏重复堆叠；右栏只保留当前状态、运行指标和资料提示。
- 连续的 `stage` 消息按一次处理过程聚合为聊天卡片，运行中显示“Agent 处理中”，终态显示“Agent 处理完成/失败”；默认折叠并实时展示最新步骤，展开区固定最大高度、独立滚动且自动跟随最新记录。
- 普通聊天消息统一显示时间；结果和处理状态的耗时紧邻时间戳展示，避免把运行详情和对话结果割裂。
- 候选题总结属于某次 `curation_summary` 的结构化产物，必须插在该消息之后而不是固定放在 timeline 末尾；否则用户后续命令会在视觉顺序上跑到总结之前。长总结采用紧凑单行条目和有界内部滚动。
- 整理右栏只承载当前任务、题目统计和运行技术事实：耗时属于聊天结果；Token 统一以 `k` 展示并收纳进默认展开的运行详情；上下文只显示 middleware 投影的当前/阈值 Token 与圆环，不追加解释性状态提示。
- 产品消息数不是 Agent role thread 的真实 context，不能作为压缩指标。正式策略为模型 `maxInputTokens` 的 70% 触发、保留 20%，100 条消息仅兜底；middleware 在每次模型调用前用 provider-aware 近似计数投影当前/阈值 Token。

## 2026-07-15：候选 draft 与会话意图边界

- 每个候选题在生成时已有独立 `KnowledgeDraft.markdown`；UI 不应再把它们伪装成一张大总结，而应作为一次 Agent turn 的文件产物展示。
- 备注是候选题上的持久用户事实，不是 rewrite 命令；保存备注必须零模型调用，后续会话指令再统一消费 noted/unnoted 范围。
- 自由输入不等于把副作用交给模型：模型输出结构化意图，领域层以 summary version、稳定 candidate IDs、状态与幂等键完成安全解析和发布。
- “第 X 题怎么写”属于 inspect 意图，不应让模型重新概括候选内容；否则即使 draft 有关键点，模型仍可能删减。正确边界是模型只选中候选，领域服务按结构化 question facts 完整投影回复。
- loop guard 的隔离粒度必须是一次 Agent invocation，不能只用父整理 execution 的 run ID；否则多个独立会话命令输出相近时会累计同一 fingerprint。命令 scope 同时包含幂等键和 invocation ID，既避免跨请求误判，也保留单次 Agent 循环检测。
- FastAPI camelCase DTO 不是应用层内部字典契约；`candidate_resource()` 在进入 response model 前仍使用 snake_case 和通用 `id`。领域解析器必须归一化内部 `id`/外部 `candidateId`，测试也必须至少覆盖真实内部形状。
- SQLite `CURRENT_TIMESTAMP` 是 UTC 且不含时区；直接 `new Date("YYYY-MM-DD HH:mm:ss")` 会被浏览器当成本地时间。前端必须先补 `Z` 再显式按 `Asia/Shanghai` 格式化。
- 命令 Agent 在模型解析完成后才投影用户消息，不能用消息落库时间倒推完整调用耗时；请求入口必须记录 UTC `startedAt/submittedAt`。指代恢复也不能只依赖相同 thread ID：无 checkpointer 的一次性意图 Agent 必须显式接收有界最近对话和候选焦点。

## R2 cancellable streaming UI

- 延续现有内容优先、三栏 Agent 工作台，不更换品牌色；新增控制使用同一 4/8px 间距、44px 最小点击区和 150–300ms 状态过渡。
- Composer 只有一个主动作：空闲为“发送”，运行中原位替换为危险色“停止”；模型与思考强度是紧凑的渐进式设置，运行时锁定，避免中途修改执行快照。
- 流式临时消息占固定位置并按 execution 隔离；空内容显示“题匠正在理解你的指令”，取消/失败保留可辨识的终态与恢复动作，但绝不混入正式上下文消息。
- 一键发布先展示服务端预检数量；需复核和已发布题只解释跳过原因。文件列表与处理详情均设置最大高度和内部滚动，禁止异步内容撑高整页。
- 状态不能只依赖颜色：按钮、状态文案和 `aria-live` 同时表达运行、停止、失败与完成；键盘继续使用 Enter 发送、Shift+Enter 换行。
- 响应式优先保住会话、消息和 composer；窄屏把模型设置折叠到输入区上方，批量确认保持可关闭、无横向滚动。

## 候选状态下钻视觉门禁

- 右栏下钻不能另造候选状态副本：会话文件卡和状态筛选文件卡必须共享组件、query 数据及 mutation 回调。
- 正式并排比较需要在同一画布同时检查设计与实现；单独查看两张截图容易漏掉状态顺序、摘要密度和操作视觉层级差异。
- 最终保留产品既有 Lucide 图标与真实历史状态语义；这些一致性约束优先于机械复制效果图中的样例图形和伪数据。

## 题目库浏览器重构

- 原页面把分类、滚动列表和正文塞入同一双栏工作台，缺少全局搜索和状态筛选，目录层级也不稳定；题目多时无法快速定位。
- 选定方案将页面收敛为搜索/筛选头部与“主题目录—结果列表—Markdown 阅读器”三栏，保留既有产品壳层、颜色 token 和真实领域动作。
- 浏览器验收暴露 `listQuestionCandidates` 的默认分页把总数静默截断为 50；题库浏览器必须遍历分页，否则状态数量、主题统计和搜索结果均不可信。
- 视觉门禁第一轮发现隐藏标签泄漏、难度文案竖排和长标题不可发现，修复后正式同画布并排无剩余 P0/P1/P2。
- 题目确认后的 `ActionCenter` 原本位于题库主 section 之后，因此作为普通文档流内容出现在整页底部；发布审批应是当前题目的模态下一步，并按发起它的 execution ID 隔离，不能混入其他待发布动作。
- 通用 `ActionCenter` 直接塞进模态会暴露内部 action type、字段表单和诊断式层级；题目发布需要专用 presentation：默认展示渲染后的题目预览，编辑和拒绝理由按需展开，只保留一个明确主动作。
- 模态关闭不能等于丢失 HITL：关闭、Escape、点击遮罩都只收起界面，未决 action 继续保存在服务端，并通过固定的“发布审批待处理”入口恢复；页面刷新后也从 pending actions 恢复该入口。

## 发布审批即时恢复

- 发布 action 的幂等键只由 draft ID、版本和内容哈希决定；同一草稿已有 pending action 时，重新创建 execution 会因 session/run 身份不同触发幂等冲突，新的 execution 失败，而前端按失败 execution 轮询必然超时。
- 正确契约是服务端“获取或创建待审批动作”：复用同键 pending action，首次创建则等待 Graph 到达持久化 interrupt 后再返回；响应同时携带 action 和是否复用，前端按 action ID 精确展示。
- React Query 的列表请求可能在 mutation 写缓存后立即重新拉取旧快照，因此新 action 还需作为 ActionCenter 的直接输入；列表缓存仍负责跨页面恢复，不承担首屏正确性的唯一责任。
- 单题“确认入库”和全局“待审批 N”不能复用同一默认选中语义：前者绑定当前 action 并直达详情，后者必须先列出全部题目且保持无默认选择，用户明确选中后才展示正文和发布动作。
- 发布退回不能只终止 HITL action：receipt 是审计真相，candidate 是产品读模型，draft 是内容版本；退回处理必须一次同步三者。候选题保存理由、时间和 action ID，手动修订清空当前退回投影但保留历史 receipt，并通过新 draft 版本生成新的发布幂等键。

## 候选题生成会话解析

- 候选题到 batch、batch 到 Agent Session 有外键保护，正常运行中真正的底层会话断链概率很低；但 `review_curation_sessions` 是独立展示投影，开发期 migration 前生成的数据可以缺少该投影。
- “查看生成会话”不能依赖当前最多 50 条的会话列表查找；旧会话超出列表或进入回收站时，关联仍然有效，但前端会误显示为空。
- 正式读取按 candidate ID 在服务端解析 `available / recycled / projection_missing / missing`，可用会话返回完整资源，回收站会话显式恢复，缺失状态只解释、不隐式回填历史测试数据。

## 题目与 Session 生命周期解耦决定

- Session 是可清理的运行容器，题目是长期领域资产；永久删除 Session 不能再依赖会级联删除 batch/candidate/source evidence 的外键语义。
- 题目删除默认可恢复；已发布题只停用 active catalog，Vault 文件、publication receipt 和复习快照继续保留。批量删除必须消费显式 candidate IDs 并由一个服务端领域操作逐项返回结果。
- 原会话不存在时不能伪造原聊天，也不能把重写降级为不可恢复的临时调用；使用统一 Runtime 创建持久 `question.revise` 会话，并从题目版本、反馈、来源证据、相似题和发布状态组装有界上下文。

## 题目与 Session 生命周期解耦实现

- migration 014 将 batch/source link 的 Session 关系改为 `live nullable + immutable origin`；永久删除整理 Session 后，candidate、draft、evidence 和 publication 不再受 cascade 影响。
- 题目删除是 candidate 软删除事实；普通题库、会话统计和复习选题默认排除，已发布题同步停用 active catalog，恢复时重新激活，Vault 文件不参与删除事务。
- 单删与显式批删复用同一个事务入口和持久幂等 receipt；版本变化按题返回 `blocked`，不存在返回 `failed`，不会扩大到当前筛选结果。
- `question.revise` 复用正式 Graph/Execution Runtime；原 Session 存在则复用（归档会自动恢复），不存在则创建持久修订 Session。输入只包含当前题目 Markdown、反馈/备注/退回原因、来源引用、重复关系和发布状态，并只接受一个候选输出。
- 修订未发布题时递增原 draft version；已发布题创建同 document 的新 draft，旧 publication receipt 和 Vault 版本继续可追溯，新版本重新进入 review pending/HITL。
- 浏览器发现并修复既有回调歧义：重写 API 返回的是 Session，不能再把 Session ID 当 candidate ID 调原会话解析接口；现在直接打开返回的修订 Session。

## 逻辑题唯一 active 版本

- `published` 只表示某个候选曾经发布，不能等同于当前可复习版本；active 必须由 catalog 当前 `draft_id` 与 candidate `draft_id` 的一致性推导。
- “更新入库版”不能创建新逻辑题，也不能覆盖旧文件；应复用稳定 `question_id`，只原子更新 catalog 指针，并把旧 publication 作为历史证据保留。
- UI 发起更新时提交读取到的 active content hash；服务端准备修订和最终 catalog 投影均再次校验，避免两个页面同时更新造成静默覆盖。
- 已开始的复习轮次消费冻结快照，因此 active 版本更新只影响之后创建的轮次，不需要回写历史评价与掌握度事实。

## 复习轮次失败恢复与历史展示

- 追问输入被跳过后，旧图仍把空补充送回 evaluator，并尝试再次完成已处于 `waiting_for_follow_up` 的 attempt；这会触发冲突/no-progress，使 execution 失败、input 已 resolved、页面却没有可恢复动作。
- 新图在持久 input receipt 中识别 `operation=skip`，保留第一次评价并直接完成 attempt；durable receipt 检查同时允许旧 checkpoint 在重试时绕过第二次模型调用。
- Round 领域状态和 Execution 运行状态必须分层展示：未终止 round + failed execution 是“需要恢复”，cancelled round 即使保留 failed execution 历史也只能显示“已结束”。
- 历史“已作答”只统计非跳过且有答案的 attempt；轮次进度只统计 completed attempt，不能用 attempt 总数或 `currentIndex` 冒充完成数。
- 早期完成轮次没有消息投影，但仍保存题目快照、回答和评价；会话回放可从这些持久事实只读还原，并明确标注来源，不能显示空白或伪造新内容。

## 整理会话题目总数与题目库口径

- 原“累计候选”按候选版本行计数，题目库则按 `groupLogicalQuestions` 展示逻辑题目；同题多个历史或候选版本会造成主页数字大于点击后的条目数。
- 整理会话主页现在直接复用题目库的逻辑归组结果：总数按 group 数，已发布按 group 的聚合状态计数。单个会话中的“候选数”仍表示该次整理生成的版本数，语义保持不变。

## 深入讨论会话闭环诊断

- 当前“深入讨论”点击后立即创建 Session，并替用户发送固定问题、直接调用模型；这把“打开讨论”和“发送问题”错误地合并成一次操作。
- 初始 discussion input 只有题目快照、评价与 mastery suggestion，缺少用户原回答和追问回答，无法可靠兑现“结合本次回答”的产品承诺。
- discussion Session ID 只保存在页面局部状态，返回报告后没有持久入口恢复；按钮也没有 pending 防重，可能重复创建子 Session。
- 正确边界是 attempt 与 discussion Session 持久关联；打开时只准备或复用 Session 并初始化 checkpoint，用户真实发送后才启动模型执行，后续继续复用同一 thread。

## 深入讨论会话闭环实现

- 没有新增平行聊天 Runtime：首次打开使用一个无模型 initialization execution 把冻结题目和完整 attempt evidence 写入原生 LangGraph checkpoint，真实用户消息继续走通用 execution/SSE。
- attempt 与 discussion 的恢复关系从已有持久事实解析：父 Session、`review.discussion` kind 和 initialization input 中的稳定 attempt ID；因此旧数据无需迁移，新旧会话都能恢复。
- discussion evidence 现在包含原回答、补充回答、评价、掌握度建议和跳过事实；报告页按钮按真实关联切换“深入讨论/继续讨论”。
- 失败重试复用失败 execution 的原始消息但不再次投影用户气泡；停止复用统一 execution cancel，避免引入讨论专用取消状态机。
# 2026-07-19：深入讨论工作台审查

- 真实页面仍沿用“报告摘要 + 文档正文 + 输入框”的纵向堆叠，首屏被 2×2 上下文卡占用，长回复只有约 760px，右侧形成大片无效空白。
- 页面同时展示全局“返回历史”和局部“返回复习报告”，导航层级重复；深入讨论态只应保留回到所属报告的局部返回。
- 通用 execution 已持久化模型配置、耗时、usage 和 context-compacted，但讨论页未展示，也无法在发送前覆盖 `agent_chat` 模型与思考强度。
- `running` 仅根据最新 execution 状态判断；历史数据中 execution 状态滞后时，即使同一 execution 已有持久 assistant 消息，页面仍错误显示“停止”。持久回复应作为终态纠偏证据。
- `ui-ux-pro-max` 检索采用 content-first、data-dense Agent workbench：聊天是主任务，上下文和运行事实进入有界侧栏；保留现有品牌色、字体和 Lucide 图标，拒绝紫粉营销色、Comic 字体和 Landing Page 结构。
- 用户实页复核证明第一版 composer 仍是并排表单，模型/思考强度挤占输入层级，和题库整理 Agent 的紧凑聊天 Dock 不一致。
- 题库整理页已有成熟约束：textarea 独占首行、模型与思考强度进入渐进披露胶囊、44px 圆形发送、运行详情默认展开、上下文用量展示百分比圆环及 `current / threshold`。
- `agent_context_usage` 已由通用 `ProjectingSummarizationMiddleware` 为 `review.discussion` 持久化；缺口只是 `SessionDetailResource` 未返回 `ProductRepository.context_usage(session_id)`，不需要新造估算算法。

## 2026-07-19：复习 Agent 工作台比例根因

- 深入讨论打开后，普通复习工作台仍同时渲染在同一个 main 中，讨论工作台只是追加到下方；这是页面高度异常和大段空白的首要根因，不能只靠继续调整 `calc(100dvh - Npx)` 掩盖。
- `review-focus-workspace`、普通会话和讨论会话分别使用两套视口估算，父级其实已经是 `minmax(0, 1fr)`；子页面应消费父级可用高度，桌面端统一 `height: 100%`，窄屏再恢复自然高度。
- 两种 Agent 会话应共享 composer 和运行事实语言：输入独占首行、底部紧凑工具栏、单一圆形发送；右栏以掌握程度为首要反馈，模型、Token、上下文进入默认展开的运行详情，长关键点独立有界折叠。
- 普通复习轮次的上下文用量已经由通用 middleware 按 session 持久化，本次只需在 `ReviewRoundResource` 投影 `contextUsage`，不新建复习专用统计逻辑。
- 左右分栏等高不能只依赖 Grid 默认 stretch：子栏自身的 `overflow-y:auto` 会形成独立滚动容器和明显滚动槽，视觉上仍像两个不同高度的面板。桌面工作台应由共同父级裁切，聊天记录作为主滚动区，右栏整体禁止滚动；长关键点或上下文只在展开卡片内部有界滚动。
- 仅移除右栏滚动仍不满足单屏会话：`review-shell` 使用 `min-height: 100dvh`，同时聊天工作台保留 `min-height: 520px`，内容会反向撑高 shell 并触发 body 滚动。桌面会话态必须固定为 `height: 100dvh`、裁切 shell，并把所有中间 Grid 节点设为 `min-height: 0`；移动端再显式恢复自然文档流。

## Progressive question curation 与诊断 Trace

- 只限制输入字符不能解决结构化输出爆炸；必须分别限制每次识别的 section 数和每次补全的完整 candidate 数。
- 当前 Mybatis artifact 为 39,570 字符；sectioner 得到 797 sections/133 discovery units，所有 unit 均不超过 6 sections/6,000 字符。长文档因此增加可恢复 work item 数量，而不会扩大单次 Provider 输出。
- completed work item 是恢复边界；retry 必须重新绑定原 batch，不能创建替代 batch，否则会重复已成功的 Provider 调用。
- Agent Trace 的文件边界应是 Execution，而 Agent 区分应是行级 identity；这既保留跨 Agent 时间顺序，又能按 `agent_name` 精确筛选。
- Trace 安全不能依赖任意对象 `repr`；只白名单基础值、Pydantic、LangChain message 和受控字段，凭据 key 丢弃，未知对象只记录 type/unserializable。
- 真实渐进式重试证明结构化输出已恢复，但 Provider 仍可能违反“每个 section 最多一个 seed/candidate”的提示。重复的允许引用属于可恢复输出偏差，应稳定保留首项；未知引用仍是证据边界违规，必须硬失败。
- LangChain middleware 返回的 `ModelResponse` 是 dataclass 而非 Pydantic model；若不显式白名单其 `result/structured_response`，JSONL 会只记录 `unserializable`，无法兑现完整本地诊断目标。

## 2026-07-22 长任务跨层验收结论

- 六个 enrichment Work Item 的确定性 fake Provider 验收证明：首波同时活动调用峰值为 3；其中两项完成、一项失败后，恢复不会再次调用已完成项；恢复中的三个调用被暂停并清理为非 running；Runtime 重建后再次恢复可完成最后一个 Work Item，最终没有 running 残留。
- 跨层 RED 暴露了一个遗留状态语义：最终 reducer 已生成正式待确认候选，却仍把 Batch 标为 `completed`。按已确认状态机修正为 `review_pending` 后，Batch 状态与候选人工审核阶段一致，兼容读取仍保留 `completed` 处理历史数据。
- `review_pending` 不是永久终态：正式发布的单条/批量/逻辑重复修订最终都汇聚 `activate_question`，HITL 拒绝汇聚 `reject_candidate_for_draft`，自由命令拒绝汇聚 `update_candidate_status`。三条 Repository 写路径必须在同一事务内聚合候选状态；只检查“没有 review_pending”会把遗留 `draft` 候选误判完成，因此条件必须是至少有一项且不存在非 `published/rejected` 项。
- SQLite `BEGIN IMMEDIATE` 串行化最后候选的并发决策；再配合 Batch 的 `status = 'review_pending'` 条件更新，确保只有一个事务增加版本并投影 Session `completed`，重复发布/拒绝不会重复终态副作用。
- 修订 finalization 复用同一 Candidate ID 并有意保留其 origin `batch_id`；因此“Candidate 属于哪个历史批次”和“本次 Batch 提交了哪个 Draft Revision”不是同一关系。把 candidate 移到 rewrite Batch 会破坏血缘与唯一性，正确边界是独立持久化 `(batch_id, candidate_id, draft_id)` committed set。
- 决策聚合必须只选择与 Candidate 当前 `draft_id` 匹配的 Batch 关联，并在 Batch 全量判定时再次要求每个关联 draft 仍是 Candidate 当前 draft。这样新修订发布/拒绝只完成 rewrite Batch，旧 Batch 不会借用新版本状态误完成；migration 025 从 committed finalization 恢复升级前修订关联，并只在 Draft run 与 owner Batch run 一致时回填普通归属。
- migration 中的归属推断不能使用 NULL-safe `IS` 比较运行 ID：Session/Execution 永久删除会让 Draft 和 Batch 的 run_id 同时变成 NULL，同时 finalization claim 已 cascade 消失。只有双方 run_id 都非空且 `=` 才是普通归属证据；NULL/NULL 必须宁缺勿错，不得创建 origin 或 rewrite membership。Repository 中 `draft_id IS ?` / `IS NOT` 则比较已持久化 revision identity，属于刻意的 NULL-safe 等值，不是归属推断。
- 前端 interrupted hydrate → resume → 新 enrichment 快照 → 旧 discovery 快照晚到的契约直接通过；同 Batch/同版本按阶段拒绝回退，同阶段 completed/total/generated 取最大值，provisional 按稳定 ID 只增合并，因此页面不会倒退计数或缩短预览。
- 当前恢复能力的成熟度是单进程 bounded scheduler + SQLite durable Work Item，不是分布式任务队列。进程退出时未提交的 Provider 调用允许重发，completed Work Item 不重放。
- 隔离浏览器验收暴露了一个展示层遗漏：运行面板已中文化 paused/interrupted/terminated，但会话列表仍回退为原始枚举值，且 terminated 被计入“待处理”。状态词典必须覆盖新增阶段，终止态必须从 active 会话统计中排除。
- “没有识别出候选题”不是等待人工决策：空集合若仍进入 `review_pending`，既没有可操作候选，也无法满足要求非空 membership 的完成聚合器。零候选必须在 finalization 事务中直接将 Batch/Session 收口为 `completed`；只有非空候选集进入 `review_pending`。
- legacy Batch 与完整 Curation Session 共用执行管线时，warning 属于可选的 Curation 投影。领域候选已提交后，不能向不存在的投影写入并反向把 Execution 标记失败；投影存在性必须成为 warning 写入的显式前置条件。
- 真实 GLM discovery 连续暴露三类“整体 JSON/Tool Call 有效、局部不完全符合领域 Schema”的输出：单个 seed 缺少 `source_ref`/含 null 引用、返回 21 项超过 20 项上限、主引用没有排在 `source_refs` 首位。把 Provider 响应直接绑定严格领域模型会让整个 Work Item 丢弃其余有效项。
- 正确边界是分离 Provider 契约与领域契约：Provider 层只保证可解析的宽松形状，确定性 normalizer 截断至 20 项、删除无证据行、去除 null/空白/重复引用并把主引用移到首位，然后再构造严格 `QuestionSeedChunk`。未知引用和跨来源引用仍在 Agent 证据边界硬失败，不能被 normalizer 掩盖。
- 该边界必须覆盖每个模型输出阶段，不能只覆盖 discovery。真实 enrichment 又返回了“第三个候选缺少 `title/topics`”和“种子有两个证据引用、候选只返回一个”的部分偏差；前者发生在 LangChain structured-output 解析层，后者发生在 Agent 的精确证据校验层。
- Enrichment 的证据集合属于输入种子，而不是模型生成事实：Provider 仍需返回一个可识别的种子主引用，归一化器再从权威 seed 映射恢复完整顺序。缺失 title 可安全使用题干，缺失 topics 可进入“未分类”；未知引用、混入其他种子的引用和缺失核心答案/关键点不能伪造成有效领域候选。
- `frontend/package.json` 没有 `typecheck` script；本阶段使用权威等价命令 `./node_modules/.bin/tsc --noEmit`，production build 自身也再次执行 `tsc`。计划中的不存在脚本不能被记录为成功。

## 2026-07-22 随手记容错整理结论

- Work Item 适合审计 Provider 调用，但粒度过大，不能作为不规范材料的恢复边界；Seed Task 才能独立保存 completed/degraded/skipped，避免一个坏题回滚同批兄弟题。
- Provider 输出只能作为 observation。应用必须用稳定 seed key 和权威 source refs 关联结果，确定性补齐展示字段，无法建立核心答案或证据时跳过，不能靠位置猜测。
- `source / mixed / ai` 与 `supported / partial / unsupported` 是发布安全事实，不是 UI 标签；所有发布入口必须复用同一个 validator，mixed/ai 需要显式确认。
- 旧 Batch 的隔离快照显示 80 个 discovery、22 个 enrichment 均保留；22 个调用输出对应 66 个唯一 degraded Seed，重复 reconciliation 不改变任何计数且不触发 Provider。
- 真实失败页证明黄色复核与红色失败可以并存；颜色之外还必须依靠图标、文案和动作语义区分。390px 无横向溢出。

## 2026-07-23：Profile API 假 404 与 SQLite 连接所有权

- 目标材料版本始终存在且归属正确；同一 URL 在 404 前后均能返回 200，因此不是数据删除、Workspace 参数错误或前端缓存。
- 同期日志出现游标行字段异常、`sqlite3.InterfaceError` 和偶发 404。根因是 FastAPI 同步路由在多个 worker thread 中并发复用同一个 `sqlite3.Connection`；`check_same_thread=False` 只关闭线程检查，不提供并发连接所有权。
- Runtime 现在保留兼容现有 Repository 接口的连接代理，每个 worker thread 延迟创建并独占真实 SQLite connection；迁移只在初始连接执行，各连接继续启用 WAL、foreign keys 和 busy timeout。
- 线程隔离 RED/GREEN 测试证明 worker 不再看到创建线程的 TEMP 表；Profile API、画像 Tool 与时间线相关回归 `49 passed`。

## 2026-07-24：求职目标中心产品路线

- B（可信个人资料）、D（目标岗位差距分析）、C（个性化训练）不是三个并列产品：B 是长期资料底座，D 把资料放进具体角色/JD 语境，C 围绕差距进行项目深挖并沉淀可复用的项目讲解卡。
- 顶层业务聚合根应是“求职目标”，简历只是可复用资料资产。每次分析与训练都属于一个通用角色或具体 JD，岗位要求必须逐条确认并映射证据，首版不提供容易制造虚假精确感的单一匹配分。
- 训练中发现的新事实只能形成待确认资料补充；通用项目叙事事实归 Profile，岗位特定要求、追问与准备风险归 Job Target，避免同一事实被多份 JD 重复复制。
- 缺口分为四类并路由到不同动作：资料缺口生成资料补充建议，表达缺口进入项目讲解卡训练，知识缺口进入题目/复习，经历缺口记录为岗位风险且不得编造。
- R3 的核心下游契约改为直接读取当前已确认 Claim 的 `ConfirmedProfileContext`。pending/rejected、旧版本、无权限敏感项和原始简历正文必须排除；Active Knowledge 发布不再是 R4-R6 的消费门禁。
- 当前简历助手收窄为资料维护助手；项目深挖迁移到 R4 求职目标工作区。首个 R4 MVP 为：创建目标 → 确认要求 → 映射资料 → 选择项目深挖 → 分类缺口 → 生成项目讲解卡与待确认补充 → 更新准备状态。

## 2026-07-24：R3 路线收口实现

- PublicationSelection/Publication 数据表和旧 Repository 读取能力已经进入不可变 migration，直接删除会制造升级风险；正确做法是保留兼容层，但从当前结构化输出契约、Action Plan allowlist、Tool factory 和消息路由中撤出发布能力。
- Profile Agent 当前只暴露七个资料类只读 Tool；知识库检索与发布状态函数保留为未注册的兼容实现。Execution scope 必须从已暴露 Tool 名称推导，不能因为兼容 scope 仍在映射表中而继续授予 `knowledge.active`。
- `ConfirmedProfileContext` 是 Profile application service 的即时只读投影，不是新的领域表或 checkpoint 状态。它按消费目的、分类/Claim ID 和 50 项上限读取当前 confirmed 版本，并排除跨 Workspace、敏感 Evidence、敏感字段和未确认版本。
- unsupported Claim 仍返回并携带支持状态，让 R4 能区分“用户确认过但当前缺少依据”和“从未确认的事实”；完全依赖敏感 Evidence 的 Claim 不进入默认上下文。
- 直接 Profile 查询不应伪造 Agent Session/Event；未来 Job Target 是消费请求及其审计元数据的状态所有者。

## 2026-07-24：R3 核心浏览器闭环与结构化输出边界

- 隔离合成工作区真实完成 Markdown 上传、11 个脱敏原文片段、9 条候选、单条确认、简历助手问答、结构化修改方案和人工确认 Receipt；应用已恢复到原工作区。
- 真实验收发现结构化 Planner 的原始 token chunk 会短暂展示 Claim/Evidence ID 和分析过程；普通问答与结构化计划不能共用同一展示契约。前端现只流式展示普通问答，计划/评估运行时显示安全进度。
- 模型可能生成格式合法但缺少 `target.claimId` 或 expected version 的计划。Prompt 1.1 明确 target/version/before/after/evidence 复制规则；领域校验失败被转换为通俗的“未生成方案”，不再让会话无回复。
- Claim 理由、Diff 字段和计划摘要统一做用户化呈现，去除 Evidence、field、institution 和原文记录 ID；内部数据结构保持不变。
- confirmed-profile 真实查询返回 11 条安全事实；待确认、拒绝、敏感和不符合消费规则的内容没有进入响应。
