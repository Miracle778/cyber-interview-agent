# Agent Runtime 框架收敛关键发现

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
