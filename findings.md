# Agent Runtime 框架收敛关键发现

## 2026-08-04：现有 Observability Registry 尚未形成完整 Agent Control Plane

- 当前 Registry 已能统一顶层 Graph 的展示名、业务入口、控制能力、Eval Pack、系统组件和运行中心可见性，并通过生产 Graph 集合契约测试防止常规漏项。
- `CreateSessionCommand.kind` 仍是任意字符串，Session 创建前没有统一注册校验；`ProductionGraphFactory`、生产 Graph 集合和 Registry 仍是平行事实源。
- `AgentFactory.create()` 尚未校验父 Agent、子组件、model role、Tool 和 Scope 归属；影响业务结果的底层模型直调也没有统一代码门禁。
- 采用 Git 版本化静态 Agent Control Plane：Definition 同时拥有身份、Builder、Schema、策略、运行中心和 Eval 契约；新任务 fail-closed，历史未知 Agent 只读兼容；内部子 Agent 进入 Operation 树而不是顶层任务列表。
- 正式决定：`docs/superpowers/architecture-decisions/2026-08-04-agent-control-plane-and-registration-contract.md`。

## 2026-08-04：Agent Control Plane Phase 2 单一 Definition 与 Builder

- 原 `PRODUCTION_GRAPH_KINDS` 与 Observability Registry 只能做集合对拍，不能证明某个 ID 实际选择了哪个 Builder；岗位分析、项目深挖和面试复盘又通过独立 Agent bundle 工厂构建，因此“已登记”和“如何构建”仍是两套事实。
- 新 `AgentDefinitionRegistry` 同时持有稳定 `agent_id`、`definition_version`、`builder_key`、生命周期、用户创建权限、运行中心元数据和 Eval Pack；GraphFactory 启动时要求 Definition 的 Builder Key 与实际 Builder Catalog 双向完全一致，缺失和孤儿 Builder 都 fail-fast。
- `ProductionGraphFactory.__call__` 改为执行 `agent_id → Definition → builder_key → Builder`；岗位和复盘的公开 Agent bundle 工厂也经过同一路径。
- 运行中心、可观测服务、质量评估和公共 Runtime 门禁直接消费 `AgentDefinitionRegistry`。`app.observability.registry` 只作为旧 import 的兼容门面，不再保存注册项。
- 本阶段只统一当前 Definition 与 Builder；子组件 Tool/Scope 门禁和 Execution Definition Snapshot 仍属于 Phase 3、Phase 4。

## 2026-08-04：Agent Control Plane Phase 3 子组件与模型调用门禁

- 仅把 `child_components` 写进 Registry 仍然只是说明性元数据；真正的执行门禁必须让 Factory 先绑定顶层 Definition，再允许解析模型、创建组件或生成 Tool Policy。
- `AgentFactory.bind(agent_id)` 现在返回 Definition-bound Factory。组件创建前依次校验 `component_id`、model role 和实际 Tool；Tool Policy 创建前校验 Tool 与 Scope，任何越界都在 Resolver/Provider 调用前 fail-closed。
- 所有生产 Agent bundle 和上下文摘要模型都经过绑定后的 Factory。未绑定的 `AgentFactory.create/resolve_model/resolve_context_limit` 保留为显式失败入口，避免旧调用方式静默绕过控制面。
- 静态 AST 契约测试扫描 `backend/app` 对 `ChatModelResolver` 的直接导入；当前只允许控制面 Factory 和应用组合根。它不能替代运行时校验，但能在 CI 中阻止常见新增绕过。
- Trace 的每条模型请求/响应现在携带顶层 `agent_id`、`agent_definition_version` 和 `component_id`；上下文压缩也使用父 Agent 的 Definition 身份和固定 `context_summarization` 组件，不再成为匿名模型调用。
- 当前 Profile 三个顶层 Definition 仍共享一个会构造完整 Agent bundle 的 Builder，因此声明的是现有 Bundle 上限，而非每条 Graph 的理论最小组件集。进一步拆细 Builder 属于后续可逆优化，不阻塞本阶段的最小权限运行时校验。
- Phase 3 没有持久化完整 Execution Definition Snapshot；历史运行的 Builder、Prompt、Toolset 与模型绑定冻结仍属于 Phase 4，不能从当前 Trace 字段推断为已经完成。

## 2026-08-04：Agent Control Plane Phase 4 Execution Definition Snapshot

- Registry 表示当前可创建合同，不能用来解释历史运行；Execution 现在在 Graph 和 Provider 启动前冻结独立 Snapshot，并由数据库触发器禁止原地修改。
- Snapshot 保存稳定 Agent/Definition/Graph/Builder 身份、输入输出 Schema、Prompt Schema 版本表、子组件与模型角色、Tool/Scope 合同及摘要、实际模型绑定摘要、上下文/重试/Trace Policy 和 Eval Pack 版本。模型摘要只包含 Definition 声明的 role，工作区其他模型绑定不会污染历史指纹。
- 迁移前运行统一回填显式 `legacy=true`，运行详情明确提示“未保存快照”，Eval 仅在 legacy 路径保留旧 Registry 兼容；系统绝不把当前 Definition 反推成旧运行事实。
- 非 legacy 运行的质量评估只允许冻结的 Pack ID/version；当前代码不再保留的历史 Pack 版本会稳定返回“不支持”，不会悄悄换成新版规则。
- 高级运行详情折叠展示冻结的 Agent、Graph、Builder、Schema、Prompt、Eval 与策略/摘要；普通任务列表仍只读轻量 Summary，不把控制面技术字段暴露成日常噪音。
- 当前多数 Prompt 仍是代码内字符串，尚未成为独立版本化资产，因此 `prompt_schema_versions` 会显式冻结为空表；这表示“未版本化”，不是伪造版本。后续 Prompt 资产化时只需补 Definition 声明，不需要改 Snapshot 格式。

## 2026-08-02：轻量创建契约需要前后端保持一致

- 正式规格允许复盘流程只填写岗位名称创建轻量求职目标，但前端按钮和后端 Service 都沿用了“岗位 + 职级成对必填”的旧规则，导致用户已填写公司和岗位仍无法保存。
- 可选性必须同时体现在字段标签、按钮门禁和服务端校验中；这次统一为“岗位必填，公司与职级可选”，并只禁止职级脱离岗位单独出现。

## 2026-08-02：规范必须同时落到结构、防御样式和实页状态

- 工作台声明四行、正常 DOM 只渲染三个直接子节点时，Grid 会把主工作区放进第三个 `auto` 行，把真正的 `1fr` 伸展行留空；条件错误条必须包进固定控制区，不能通过永久预留可选行维持布局。
- 业务页的宽泛 `header span` 再次命中共享 Button 的内部标签，说明书面约束不足以防止同类回归；业务侧必须改用语义类，共享 Button 标签也必须以更高组件选择器继承颜色、字体并清除外部边距。
- “无横向溢出”不能证明桌面布局正确。工作台验收还必须测量主区域是否抵达视口底边、空状态是否只有一个主叙事、主按钮计算颜色是否符合共享组件，以及未选中的同级标签是否已经拥有真实计数。

## 2026-08-02：面试复盘渐进分析的身份与恢复边界

- QuestionUnit 归属于确认后的 CleanupVersion，而不是某一次 AnalysisRun；重试时删除再插入会级联删除旧逐题分析。实现必须按服务端 stable key 对账并复用 QuestionUnit ID，未再次出现的问题标记 superseded，才能保留运行历史。
- “工作项完成后再停止”不等于重新跑整场。问题提取和每道题都要独立提交；继续时只领取 pending/retryable/interrupted，已完成提取的 attempt count 保持不变。
- 渐进页面允许用户在后台仍运行时确认推断题。若直接把 running finalizer 改回 pending，旧处理会在完成时发生状态冲突；使用 `rerun_requested` 标记，让当前临界区落盘后自动回到 pending，可以保证修订不被迟到结果覆盖。
- 同一个已确认 CleanupVersion 和冻结上下文摘要必须幂等复用；显式 retry 通过 `retry_of_analysis_run_id` 创建新运行。两者不能混为一种，否则刷新会制造重复分析，或真正重试会覆盖历史。
- 推断题可以先生成 draft 逐题分析用于预览，但只有 confirmed 问题进入最终汇总；rejected、superseded 和 pending 都不能进入正式报告、候选资产或整场统计。

## 2026-08-01：Evaluation v2 真实回归验收

- 同一输入、同一模型配置仍可能产生不同业务结果；真实题目整理 A/B 中一边出现模型补充截断，另一边完整，说明回归必须比较重新生成的 Outcome，不能只重新 Judge 历史文本。
- 盲评内部使用 A/B 随机顺序，但持久化结果会重映射为 `baseline/candidate/tie`；产品页面必须展示“来源配置/当前配置”，不能泄露 A/B 或原始英文状态。
- 对话与题目整理的真实案例均证明 `separateSandboxes=true`、`productionWrites=false`，且无基础设施失败；这足以证明当前模型配置比较链路成立，但两边仍使用 `codeMode=current_process`，不等同于任意 Git 历史代码回放。
- Judge 对模型补充的技术正确性只能给语义信号；来源忠实度、补充透明度和处理计数由字段级 provenance 与确定性规则分别约束，任何 Judge 胜负都不进入发布门禁。

## 2026-07-31：Evaluation v1 实现审计与 v2 边界

- 当前 5 个 Pack 的 21 个维度由 Judge 统一输出 0–100 分，没有 N/A 或证据不足状态；宽泛 Pack 被多个业务目标复用，存在任务不匹配。
- `evaluate_deterministic_rules()` 只判断所需 Trace 事件是否存在，`blocking` 字段没有接入领域门禁，因此只能称为评估证据完整性检查。
- 回归案例虽然保存 `snapshot_json`，但回归端点仍调用 `evaluate(case.execution_id)`；它会重新构建并 Judge 原 Execution，不会用案例输入运行候选业务 Agent。
- 当前 Judge 读取完整 `FrozenEvaluationSnapshot`，外部模型可能得到超出任务需要的私有 Trace；v2 必须先构建任务级最小 `EvaluationView`。
- 题目整理已经有 `source_answer`、`supplemental_answer` 和 `answer_basis`，但最终候选合并为 `reference_answer` 后会丢失字段级来源语义；来源忠实度不能用来惩罚明确标记的模型补全。
- 相似度阈值只适合召回疑似重复项，不能替代 exact/same-core/parent-child/related 等关系判断和用户合并决定。
- 画像、JD 和项目评估都需要把“未记录/未评估/推断/本人确认”与“直接来源”分开；没有证据不能推断用户没有某项经历。
- 真正回归必须冻结输入与必要领域状态，在隔离环境分别运行基线和候选 Agent，再比较最终业务结果；重新 Judge 历史结果只能验证评估标准变化。

## 2026-08-01：Evaluation v2 确定性规则证据边界

- 最终业务结果可以直接证明 Workspace/Execution 身份一致、稳定 ID 唯一、公开计数守恒以及 direct/normalized 字段是否保留来源引用。
- 最终快照不能独立证明迟到结果没有覆盖、Tool/写入边界始终合规或 Receipt/Event 全程一致；这些维度必须等待领域 Adapter 投影状态转换历史、审计和 Receipt，当前返回 `insufficient_evidence`。
- 规则结果新增领域 `evidenceRefs`，不再把领域行引用塞进 `citedEventHashes`；所有规则保持 advisory，初始合成校准用例只能证明规则实现符合标签，不能证明真实数据误报率足以启用门禁。
- Phase 3 的公共 Adapter 可以统一投影 ID、终态、计数、来源和用户决定，但任务不变量必须继续由领域语义解释：例如 `review.currentIndex` 只能与通过/跳过结果比较，画像更新/拒绝必须有 expected version，JD quote 必须满足 `body[start:end] == quote`。
- 最终快照不能证明“讨论前后题号完全没变”、迟到 Provider 结果是否曾尝试回写等时序事实；这类规则保持 `inconclusive`，后续需补前后状态快照或 Receipt，而不是让 Judge 推断。
- 题目答案过去只保留合并后的 `reference_answer`；迁移 043 新增 `source_answer` 与 `supplemental_answer`，新候选可以分别评价原文忠实度和模型补全质量，旧候选仍保留兼容读取并显式暴露证据缺口。
- 真正可恢复的回归快照必须在 `run_prepared/run_background` 启动前冻结，而不是 `prepare` 结束时冻结；题目批次、画像材料等领域关联可能在两者之间才完成绑定。
- 对话 Agent 回归除 runtime DB 与材料外还必须冻结 `checkpoints.sqlite`，否则只能重放单轮输入，不能复现当时的会话上下文。
- 当前进程能够真实比较“来源模型配置”和“当前模型配置”，但没有旧代码制品加载器；结果会明确记录 `codeMode=current_process`，不能宣传为任意 Git 历史提交回放。
- 质量门禁只接受经过真实案例校准并显式批准的确定性 rule ID；Judge 胜负、语义等级、Token 和延迟不能自动阻断。当前批准集合为空，因此门禁保持默认关闭。

## 2026-08-01：面试复盘版本与跨领域边界

- 复盘不能只保存 Markdown、聊天消息或 Agent checkpoint；原始输入、说话人整理、问题确认、逐题分析和用户决定需要独立不可变版本与业务表。
- 求职目标是强制父级，但正式题库、统一画像、通用项目讲解和 Knowledge 继续由各自领域拥有；删除复盘或目标不能级联删除这些已确认资产。
- 分析处理 Session 与持续对话 Session 分离，避免后台事件污染用户对话，也避免聊天消息成为分析状态源。
- 长转写整理同样需要持久化窗口工作项；仅有逐题分析工作项无法满足整理阶段的停止、恢复和幂等 Reducer。
- 首版新增 `retrospective_analysis` 和 `retrospective_chat` 两个模型用途，分别复用岗位分析和项目深挖的既有绑定完成升级回填。
- runtime migration 045 新增 13 张复盘领域表；app migration 010 扩展为 10 个模型用途，既有 Workspace 可无损升级。

## 2026-07-29：项目级 Agent 可观测与质量评估设计

- 当前 per-Execution JSONL 已能保存模型和 Tool 的真实交换，但 UUID 文件布局、无查询索引和无产品化 UI 使其仍是诊断基础设施，不是产品级可观测能力。
- Product Event、Usage Projection、JSONL Trace、Checkpoint、领域表和 OTel 的职责不同，不能合并成单一“日志”或互相替代。
- 项目级入口必须覆盖全部 Agent；业务页只保留当前运行摘要和下钻入口，不能把全局运行中心放在复习或题库子页面。
- 采用本地 Trace Ledger：JSONL 是完整正文，SQLite 是可重建索引，大型正文使用受控 Artifact；不建设第二 Runtime 或独立 Gateway。
- 高级查看允许读取 Prompt、上下文、Tool 和 Provider 原始响应，但 secret 永不保存；思维过程只展示 Provider 实际返回字段。
- 初始目标设想为共用内核与角色专用版本化 Eval Pack；2026-07-31 审计确认当前 v1 规则不能阻断，后续按任务级 Pack 与真实业务不变量迁移。
- 默认长期保留元数据、完整正文保留 90 天；Workspace 可配置永久、定期清理或不保存正文。
- 当前产品没有账号或权限系统；高级正文使用本地高级诊断开关，Workspace 和路径校验仍由 API 强制执行。
- 当前生产 Trace 写入 v2，Reader 只需兼容可能存在的 v1；完整父子树通过下一版 Schema 实现，不能把“兼容”误写成“本地已经存在两版数据”。
- 顶层运行统计以业务 Execution 为单位，内部 Agent 和系统模型组件进入执行树；Registry 是覆盖新增 Agent、能力按钮和 Eval Pack 的强制入口。
- Judge 是独立评估模型，不是业务 Agent 自我反思；失败/部分成功/降级等自动触发，普通成功默认采样 5%，每 Workspace 每日自动上限 20。
- 产品展示 Token、上下文和延迟，不展示费用，也不维护 Provider 价格表。
- 实施计划采用一个总索引与四个纵向 Slice：运行中心、高级 Trace、质量评估、保留与安全投影；每个 Slice 都包含真实后端、API、前端与浏览器验收，禁止用 mock 页面提前宣称交付。
- 为避免再次触发 SQLite 写锁，Trace Writer 热路径只追加 JSONL；查询索引由工作区增量扫描器在启动、查询和 SSE 轮询时短事务同步，并可从 JSONL 全量重建。
- 当前后端依赖已经包含 OTel/OTLP，但没有 Langfuse SDK；保留与投影 Slice 明确交付 OTel 安全元数据投影，不把 Langfuse 宣称为已实现功能。
- 当前应用数据库没有独立迁移测试，计划在高级诊断 Slice 新建 `test_app_migrations.py`，覆盖本地高级开关和后续 Judge 设置迁移。

## 2026-07-28：画像依据不足误判

- `profile_claim_versions.evidence_ids_json` 只包含接受当前建议时的 Evidence，
  后续相同 Claim 的其他简历来源保存在 `profile_claim_sources.source_ref_json`。
- 删除影响预检只读取前者，是“另一份简历仍有依据却被标黄”的直接根因。
- 历史删除还留下 13 条指向已删除版本但状态为 active 的 Source，导致来源标签继续失真。
- 当前 Claim identity 采用精确字段匹配；表述稍有变化不会自动合并。该边界应保留，但需要
  用“相关内容待核对”承接近似描述，不能把它与完全缺失混为一类。
- 开发数据修复后：16 条有直接支持，3 条找到相关内容待核对，4 条确实没有相关原文。

## 2026-07-25：求职目标与项目深挖需求共识

- 本轮规格细化并收窄 2026-07-24 ADR：一个目标首版最多一个当前 JD；全局项目不需要在目标内重复关联 CRUD；正式准备项目采用一个核心项目和最多两个补充项目。
- 岗位要求状态统一为“已有可靠证据 / 待深入验证 / 资料待补充 / 暂无相关经历”，分别替代旧 ADR 中较含糊的“部分匹配 / 资料不足 / 经历缺失”表达。
- 一个求职目标对应一个具体准备目标，首版最多一个当前 JD；没有 JD 时生成明确标注为“岗位方向参考”的要求草案，所有要求都需人工确认。
- 统一画像和全局项目集合继续作为长期事实来源；求职目标只保存 JD/要求版本、映射、项目优先级、岗位针对性问题和准备状态，不复制简历或项目事实。
- 项目深挖采用有界 Plan-and-Execute 与最小 `state_schema`，支持暂停、终止、恢复；不采用 Time Travel、自由 ReAct 写入或无限 Planner。
- 岗位分析是可恢复后台任务，项目深挖是持久会话 Agent，项目题训练复用现有复习执行框架并使用项目题专用评价规则。
- Agent 只获得角色级最小只读 Tool；画像、叙事、岗位要求和题目入库均通过结构化建议、Diff、确定性领域服务、人工确认和 Receipt 完成。
- 消息与执行必须解耦：一条用户消息可由多个 Execution 重试；原消息只持久化一次，失败/停止输出不进入正式上下文，修改后重试以替换关系排除旧消息。
- 长任务必须展示阶段、进度、耗时和最近进展，支持检查点恢复；已完成中间产物不能因模型失败从头重算。
- 项目经历题是题库正式类型，按项目和能力维度组织；深挖完成后批量生成候选、去重、确认入库，并形成最小训练闭环。
- `R4` 只作为路线图阶段名；UI、API 业务对象、架构标题和提交信息使用“求职目标、岗位分析、项目深挖、项目经历题”等可理解名称。
- 现有 `ExecutionService.prepare(..., project_input_message=False)` 已支持“原消息不重复投影、为同一输入创建新 Execution”的重试基础；新设计应补稳定 `inputMessageId/retryOfExecutionId` 关联，而不是另建第二套消息系统。
- 现有 `ProfileService.confirmed_profile_context(...)` 可作为求职目标读取已确认画像的入口；目标域保存读取快照版本与 ClaimVersion 引用，不复制画像正文。
- 前端路由和一级导航集中在 `frontend/src/app/layout/AppShell.tsx` 与导航组件；求职目标应作为新的一级入口并采用现有 workspace page shell。
- 当前题库 catalog 没有正式题型字段；项目经历题需要 additive migration 和目录投影扩展，不能只依赖 topic 标签模拟类型。

## 2026-07-24：统一个人画像后端检查点

- “本人直接编辑”与“Agent/简历建议”必须分流：本人保存可直接生成 confirmed ClaimVersion；简历、对话和系统归纳仍进入 Proposal，不能共用一条隐式写路径。
- 统一画像不需要新建第二套事实表。Claim/ClaimVersion 继续承担事实版本，来源和类型化关系独立建表，展示顺序只保存稳定 Claim ID。
- manual confirmed Claim 可以没有 Evidence；可信性由 `source_kind=user_input` 和来源标签表达，不能因为没有简历片段而从下游上下文消失。
- 来源已删除不等于画像卡片删除。来源状态要保留并投影成“原来源已删除，本人保留”，让用户决定是否继续保留事实。
- 清理开发期画像数据必须把数据库归属、精确 Workspace、活动运行、共享 artifact 引用和非 Profile 数据保护都作为硬门禁，不能用通用级联删除代替。
- 画像完整性只生成具体缺失项，例如项目结果、本人角色和经历时间，不计算难以解释的总分。

## 2026-07-24：统一个人画像产品纠偏

- 当前 R3 的后端可信边界基本正确，产品问题不是 Evidence 缺少行号或片段标题，而是前端把来源资产当成了画像主对象。
- 个人画像被重新定义为 Workspace 级、岗位无关、经过确认的长期能力档案；简历只是来源之一，无简历也可以由用户手动或通过对话逐步建立。
- 现有 `profile_claims/profile_claim_versions` 已具备稳定身份、确认版本和卡片级历史，继续作为单一画像真相；不再另建一套 Profile Entry 存储。
- 来源必须区分 `resume_extraction`、`user_input`、`conversation` 和 `agent_inference`。用户主动编辑保存直接确认，其他来源先进入 Proposal。
- 职业概况、能力方向和代表性亮点同样需要版本、来源和确认，内部复用 presentation Claim Type，并通过 `supported_by` 关系引用已确认事实。
- 项目保持独立，可关联工作或教育；技能展示实际使用关系，不让模型生成无依据熟练度；基础画像只展示明确缺失项，不生成总分。
- 页面主线改为“我的画像 / 待确认 / 简历与来源 / 画像助手”。Evidence、页码和行号降为“查看依据”的二级能力。
- 当前本地 Profile 数据未正式使用，可在新模型稳定后按精确 Workspace 受控清除；数据库迁移本身不得隐式删数据，其他 R2 数据必须保持不变。
- 纠偏规格、ADR 和 9 Task 计划已建立；下一步按计划以内联单 Agent 执行，不创建不必要的子 Agent。

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

## 2026-07-24：统一个人画像纠偏结论

- 简历文件、原文 Evidence 和待确认候选是来源与处理状态，不是用户要阅读的个人画像。页面主对象必须是由当前 confirmed ClaimVersion 投影出的统一画像。
- 同一 Workspace 只维护一份画像。简历、本人输入、对话和 Agent 归纳统一进入来源模型；本人在结构化编辑器保存可直接确认，其他三类来源必须先形成 Proposal。
- 新版简历采用确定性增量合并：完全重复只增加来源，变化形成更新或冲突建议，简历中缺失旧事实不能自动删除已确认内容。
- 画像助手的可见范围不是前端提示语，而是服务端将请求卡片/类别与当前 confirmed、Workspace 和敏感策略求交集后的授权边界。
- 空白画像真实浏览器闭环证明：新增项目后立即形成可读卡片和“本人补充”来源，页面给出具体缺口，删除后恢复干净空状态。
- 当前 Workspace 重置前 dry-run 命中 2 份材料、12 条画像、16 条建议和 4 个画像会话，并明确保留 1746 条题库整理数据；执行后 Profile 数据和两个私有引用已清除。

## 2026-07-24：简历工作台可用性补强

- 页面反复出现整页下滑的根因不是单个卡片，而是应用顶部导航占高后，子页面仍使用独立的 `100dvh`/最小高度，且没有明确滚动所有权。现统一由共享工作台占用“剩余视口”，桌面只允许列表、详情等内容区内部滚动；窄屏恢复自然文档流。
- 长任务进度只能展示可验证的业务阶段、已保存数量和真实耗时，不能用模型无法保证的百分比。停止复用 Execution 取消语义，已经持久化的材料、原文和建议不回滚，继续会创建新的 Execution。
- 一键确认不是“确认所有数据库记录”。安全集合必须排除冲突、空值和简历来源不完整的建议，并在弹窗中同时告诉用户可确认数与排除数。
- 完整原文阅读属于私有用户能力，不等于给 Agent 增加原文读取权限。文档 API 继续执行 Workspace 校验，原文和脱敏版在服务端分开返回，Agent 输入仍只走脱敏证据。

## 2026-07-24：Agent 会话工作台统一

- 画像助手原来的永久左会话栏、顶部资料范围和底部运行详情同时挤压消息区；固定 `calc(100dvh - Npx)` 还会与个人画像页头、页签重复扣减。Agent 工作区应由父级传递剩余高度，消息和右侧依据分别承担内部滚动。
- Session 只拥有会话身份、标题、生命周期和默认偏好；运行中、失败、中断属于 Execution。不同 Session 可以并发，同一 Session 仅允许一个活跃 Execution，不能用全局禁用按钮掩盖资源并发问题。
- 会话记录与选中会话是两个界面状态。默认归档进入回收站，永久删除只在回收站出现；手动标题将 `title_source` 切换为 `user`，后续标题中间件不得覆盖。
- 快捷问题只填入输入框，模型和思考强度随 Execution 快照保存；正文统一 Markdown，Tool/Event 名称收进一个用户化过程卡。持久化终态继续优先于可能滞后的 SSE 状态。
- Session 列表提供最近消息摘要，使“搜索标题或最近消息”由后端事实支持，而不是前端占位文案。

## 2026-07-24：画像整页滚动与“超长标题”辨析

- `profile-shell--reading` 只有 `min-height: 100dvh`，在应用导航已经占用视口的情况下会随画像卡片继续增长；读取型页面也必须明确滚动所有权，由固定高度 Shell 承载唯一的内容滚动区。
- 会话记录中的 `title` 与 `lastMessagePreview` 是两个展示层级。最近回复不能未经清理直接铺在卡片里，否则 Markdown 长文会被用户误认为会话标题；卡片必须使用短摘要，完整回复只在会话内展示。
- CSS 的 `text-overflow: ellipsis` 只有作用在可收缩的实际文本容器上才可靠。标题文本与重命名按钮同处 flex 标题时，应把文本包进 `min-width: 0` 的独立 span。

## 2026-07-25：画像概览与会话列表实页纠偏

- “我的画像”虽然已从整页滚动改为内部滚动，但把所有工作、项目、教育和成果连续铺开仍会让它像资料数据库。首页应只回答“我是谁、有什么重点、各类资料有多少”，完整条目通过分类切换渐进展开。
- `ProfileBackgroundTask` 是条件节点，而 Shell 使用四行 Grid；任务条不渲染时，主内容被自动放到第三行，真正的伸展行留空，导致会话页底部出现约 199px 无效空间。隐藏文件输入固定到第一行、主内容固定到第四行后，有无任务条都使用同一高度契约。
- `.profile-session-list > header span` 误命中按钮内部的 `.btn__label`，造成蓝底蓝字。所有视觉规则都必须限定到组件自身的直接语义节点，不能用跨组件的宽泛后代选择器。
- 单条会话使用 `auto-fill` 双列网格会只占半宽；会话记录是纵向扫描列表，改为单列后标题、摘要、状态和操作形成稳定阅读顺序。
- 最近回复摘要应取第一段有效自然语言，再移除 Markdown 和截断；把全文压成一行仍会把表格、分隔线和后续章节污染到列表。
- 画像主页的永久右侧栏即使使用 `sticky`，也会在左侧长内容继续滚动时形成右侧空档；正确模型不是继续调列宽，而是取消永久右栏，让分类内容占满同一主轴。
- 一级画像页签由 Shell 行固定，分类子页签在唯一内容滚动区内吸顶；实测子页签 top 与一级页签 bottom 同为 141.32px，避免两套导航重叠或漂移。
- 概览三卡不能简单等高：18 个技能标签会把同一 Grid 行撑到 262px，再次制造空白。默认只展示技能摘要和前两项待完善，完整内容由用户主动展开，三卡高度收敛到 136–175px。
- 长项目表单不是靠缩小字段解决。编辑器应将头部、可滚动表单体和底部操作栏分成三个所有权区域；桌面使用宽版双列，窄屏改为全屏单列，保存操作始终可见。

## 2026-07-25：Agent 时间与耗时回归根因

- `Intl.DateTimeFormat(timeZone: "Asia/Shanghai")` 只负责显示时区，不能修复输入时间本身缺少时区的问题。SQLite `CURRENT_TIMESTAMP` 返回无后缀 UTC 字符串，直接 `new Date(value)` 会按浏览器本地时间解释。
- Agent 组件必须统一通过 `parseApiTimestamp` 把 SQLite 无时区时间先解释为 UTC，再投影为北京时间；禁止组件自行复制日期解析。
- Execution 实时耗时不需要服务端每秒推送。持久化 `startedAt` 配合前端一秒 tick 即可实时显示；终态改用 `finishedAt` 冻结，刷新后仍能得到相同耗时。
- 该问题不是 Agent 页面专属。题库、知识库、画像、简历版本、回收站等普通业务页曾继续各自调用浏览器日期 API，导致既有 Agent 规范无法阻止回归。时间规则必须提升为全应用开发准则，并通过唯一共享格式化入口落实。
- 题目候选的 `sourceRefs` 是证据级引用（例如 `source-id#section-0168`），知识库来源筛选值是资料级 `source-id`。来源筛选、来源计数和服务端查询必须显式解析引用中的资料 ID，不能做字符串完全相等比较，也不能把片段数显示成资料份数。

## 2026-07-25：求职目标与项目训练实施结论

- JobTarget 拥有目标、JD 版本、要求确认和项目优先级；Profile 继续拥有跨目标共享的项目事实；Session/Message/Execution 只拥有交互和执行尝试。三者不能用一个 Graph state 代替。
- JD 保存后应自动启动分析，否则用户只看到“已保存”但不知道下一步；无 JD 时则必须给出“先添加岗位描述”的确定动作，不能展示无效的通用入口。
- 长任务的可恢复单位必须是持久工作项和 Execution，不是前端转圈。暂停只停止新工作，已保存结果不回滚；重试创建新 Execution 并关联原 Message，避免上下文出现重复问题。
- 要求批量确认只能处理安全集合，并在成功后清空选中状态；过期、冲突和缺少事实的项继续留给逐项判断。
- 项目深挖不需要自由 ReAct。七个明确维度、一次回答一次主要模型调用、最小只读 Tool 和显式完成条件更容易恢复、计费和解释。
- 项目题属于正式题库的一种来源与分类，不应另建训练 Runtime。候选确认后投影进现有 Review 选择器，复用回答、评分、冲突和状态机。
- Agent 页面必须把完成、暂停、失败作为真实终态处理：完成后禁用输入，暂停后提供继续，失败后提供原文重试/修改重试/放弃；“停止”不能在无活跃 Execution 时继续显示。
- 响应式验收应同时检查 `scrollWidth == clientWidth` 和滚动所有权；只看截图无法发现页面级横向溢出或固定区随内容漂移。

## 2026-07-25：求职目标真实页面纠偏

- “配置了模型用途”不等于“业务调用了模型”。必须从 Runtime 注入、Agent 调用、
  Execution、usage/context 投影到页面逐层取证；本次首轮代码虽然存在
  `JobTargetAgents` 类型，生产 Application 从未收到实例。
- JD 创建应先保存唯一可靠输入，再异步提取元数据和要求。强迫用户重复填写 JD
  已包含的信息，会把模型能力变成额外表单负担。
- Session 的暂停/结束和单次 Execution 的停止是两套状态机。一个按钮同时承担两者，
  必然产生“暂停后仍显示停止”“停止后消息是否进上下文”等歧义。
- 接口不声明响应模型时，后端 snake_case 记录不会自动变成前端 camelCase；时间、
  executionId 和 resolutionStatus 会静默失效，页面看起来仍能渲染却丢失关键行为。
- 总览中的数字和步骤如果没有导航动作，只是装饰性报表。工作台摘要必须回答
  “现在发生了什么、下一步去哪、点哪里继续”。

## 2026-07-25：UX 审计 P0 根因

- Session ID 只能隔离会话，不能证明同一会话里的某条消息已经被正确解释。项目深挖缺少“输入意图”门禁，且把同阶段第二个产物无条件视为完成，导致自由提问被当成职责答案写入并推进。
- 结构化模型输出仍需业务 Reducer 做不可绕过的状态约束。只有回答意图可产生 narrative、gap 和 stage completion；模型的错误分类不能直接改业务状态。
- 标题中间件读取的是模型输入消息，而画像 Agent 会先把用户消息包进包含画像快照的内部提示，因此内部状态被误当标题。跨 Agent 的稳定事实应从产品消息表读取，不应从模型提示反推。
- 失败恢复需要显式的 Message→Execution 关系。正常发送时只把 `run_id` 写在消息上、却不回填 `input_message_id`，会让通用重试无法稳定定位原消息；新的绑定保证重试不复制用户消息。

## 2026-07-25：岗位要求终态展示与分类边界

- JobTarget 摘要和 Analysis Run 是两份不同的查询数据。只轮询 Analysis Run、不在其终态刷新目标列表，会让已完成的业务事实被旧摘要覆盖成“识别中”。
- “无法从 JD 提取岗位名称”不是运行中状态。它应是可行动的“待补充”状态：用户可继续核对要求，也可再补充岗位信息。
- 背景分类必须识别“应用服务团队”这类短标签，但不能把“可能需要带团队”这类推断要求当背景；因此标签规则需与候选人要求词共同判断。

## 2026-07-25：运行时间与跨页查询一致性

- API 时间语义必须在入口统一：SQLite 形如 `YYYY-MM-DD HH:mm:ss` 的时间是 UTC，任何组件直接用 `new Date()` 解析都会在本地时区发生偏移；实时耗时和展示时间都应复用共享解析器。
- Mutation 成功后只刷新当前列表不足以保证产品事实一致。画像确认还会影响顶部待确认数和材料详情；候选题发布还会影响题库概览与复习可用题，必须显式失效这些投影查询。

## 2026-07-25：移动端求职目标的信息优先级

- 桌面侧栏在 390px 继续横向堆叠，会先消耗掉最稀缺的垂直空间，再把正文裁成难以阅读的一列。移动端应把“选择目标”降级为紧凑控件，让当前任务内容优先。
- 四个同级页签不应缩到单字。此处允许导航容器横向滚动，但页面内容本身必须维持 `min-width: 0` 和 `overflow-x: hidden`，避免把导航滚动扩散成整页横向滚动。

## 2026-07-26：工作区与模型设置边界

- 当前工作区并没有显式“当前选择”记录；`get_current()` 只是按 `updated_at` 取最近一条，重命名、重新关联或可用性更新都可能意外改变当前工作区。
- 工作区运行数据位于工作区根目录下 `.cyber-interview-agent/runtime.sqlite`，全局 Provider、密钥引用和模型用途绑定位于应用级 `app.sqlite`。因此永久删除必须先卸载该 Workspace Runtime，再清理应用运行数据；用户的 `knowledge-vault` 和原始文件夹保持不变。
- Workspace Runtime 按 Workspace ID 独立缓存连接和 Execution。切换前端上下文不需要终止原工作区任务；删除则必须在运行中 Execution 存在时阻止。
- Provider 与密钥保持全局复用，模型用途绑定继续以 Workspace 为粒度。
- 模型设置当前把 Provider 长表单和八个用途选择器全部平铺；重构采用渐进展开、业务分组和固定保存反馈，技术 ID 默认进入高级信息。

## 2026-07-27：复习轮次读取失败与主题选择器

- “开始复习”并非创建失败：轮次、Execution、首题输入和消息已经持久化，但读取资源时访问了缺失的 `review_question_assistance` 表，响应变成 500，形成“写成功、前端报错、重试又重复创建”的假失败。
- 真实数据库已记录 migration 031，但该版本后来补入的两张表没有出现在已应用数据库中；已发布迁移文件不可原地修改，必须新增幂等修复迁移，才能让已有数据库获得缺失结构。
- 532 个 Topic 不应在创建页一次平铺。默认紧凑展示 18 个，支持搜索、已选项优先、清空和显式展开；专题复习在没有选择主题时不允许提交。

## 2026-07-27：数据库结构检查采用独立只读脚本

- 暂不把 Schema 校验加入后端启动路径，避免为当前本地单用户阶段扩大运行时状态和错误处理边界。
- 检查脚本从现有 app/runtime migration 自动构建期望结构，再比较数据库的迁移版本、表、字段、generation 和外键，不维护第二份易漂移的 Schema 清单。
- 脚本只读且不自动修复；它适合开发启动前、合并后和故障诊断，不能替代未来发行版本的启动保护。

## 2026-07-27：复习辅助操作“成功后报错”

- “查看答案”已经持久化用户消息、助手回复和辅助状态，但接口随后返回 500；因此它不是输入、模型或数据库写入失败，而是典型的部分提交假失败。
- 根因是业务层新增并发布 `review.turn.responded`，却没有把该事件登记到 `ProductEventStream` 的允许集合；发布阶段抛出 `unsupported product event`，对应事件也没有写入 `agent_events`。
- 新事件必须同时登记服务端事件白名单和前端 SSE 订阅列表。领域写入后再发布事件的路径仍应警惕部分提交；当前先修复确定性白名单遗漏，不扩大为 Outbox 重构。

## 2026-07-27：当前题目卡与历史题回看

- 当前题目卡体积异常的主要来源不是题干，而是把 `missingDirections` 完整列表与右侧“待补充关键点”重复展示；焦点卡只需要覆盖计数和待补充数量摘要。
- 题目进度条此前完全由静态 `li` 组成，没有选择状态或点击回调。活动轮次资源已经包含历史 `attempt.questionSnapshot`、回答、评价、覆盖状态和跳过状态，无需新增后端接口即可实现只读回看。
- 回看必须与当前答题状态分离：只允许打开已有 Attempt，未来题保持不可点击；返回当前题不恢复 Graph、不提交输入，也不改变 `currentIndex`。

## 2026-07-27：待补充关键点通用布局修复

- 数据并未缺失：真实页面 DOM 中存在 4 条关键点，但右栏 Grid 只给对应 `details` 分配了 52px，高度之外又被多层 `overflow: hidden` 裁掉。
- “给内部列表增加滚动”无法解决没有有效可用高度的父容器；文本换行、关键点数量或视口高度变化后仍会复发。
- 右侧运行栏改为唯一纵向滚动所有者，内部模块按内容自然增高，不再嵌套裁切或嵌套滚动。该约束同时覆盖任意关键点数量和多行内容。

## 2026-07-27：复习评价的流式进度边界

- 复习评价返回的是需要经过 Schema 校验和业务 Reducer 的结构化结果；直接逐字渲染模型生成中的 JSON 会产生半截字段、错误分数或错误推进状态，因此不能把最终评价伪装成文本流。
- 用户真正缺少的是运行可见性。评价节点现在通过安全的自定义 SSE 事件公开“对照必答方向、生成反馈与下一步”等阶段，事件只包含轮次、尝试和题号，不暴露回答、必答点或模型推理。
- 对话消息与右侧运行栏都从持久化的 `evaluationStartedAt` 计算实时耗时，完成后以 `evaluationCompletedAt` 冻结；最终评价卡仍在结构校验通过后原子展示。自由文本讨论继续使用真正的 `assistant.delta`。

## 2026-07-27：复习题来源不能使用题目文档 ID

- `QuestionSnapshot.document_id` 指向发布后的题目文档（如 `question_<uuid>`），不是生成题目的原始资料；将它标成“冻结来源”既暴露内部标识，也无法回答“来自哪个文档”。
- 原始来源应读取 `review_question_source_links`，再通过 `KnowledgeSourceService` 解析原始文件名；一个资料的多条 evidence ref 应合并成一份文档及连续片段范围。
- 来源面板现在只展示原始文件名、可读片段范围和资料可用状态；缺少关联时展示明确空状态，不再回退显示任何内部 ID。

## 2026-07-27：复习题目步进器的省略范围必须可达

- 长轮次只渲染首题、当前题附近和末题时，“…”不能是纯视觉占位；否则被折叠的已完成题虽然可回看，却没有任何可达入口。
- 省略范围应保留明确起止题号，点击后渐进展开该范围；已完成/已跳过题可进入只读回看，未来题明确显示待开始且不可操作。
- 展开内容放在步进器下方的独立选择区，避免浮层被步进器 `overflow` 裁切；选择题目后自动收起，并保持当前复习进度不变。

## 2026-07-27：回答后立即展示参考答案

- 结构化评价可能持续较长时间，但参考答案来自冻结题目快照，不依赖评价模型；没有必要让用户等评价完成后才能对照学习。
- 首次正式回答与自动参考答案应在同一事务落库，评价仍只读取提交时冻结的回答。自动展示不写入 `review_question_assistance`，因此不降低本次独立掌握语义。
- 回答前主动查看提示或答案仍属于辅助行为；否则用户可先看答案再照抄，却被系统错误记录为独立掌握。补充回答也不重复展示同一份参考答案。

## 2026-07-27：评价运行态不能复用等待输入态的跳过协议

- 回答被接受后，pending input 已经解决并清空；评估过程中仍要求 `inputRequestId/version`，必然会报“当前轮次没有待跳过输入”。
- 只取消异步任务后直接跳到下一题也不安全：LangGraph checkpoint 中原 `evaluate_answer` 仍是待执行节点，重新恢复时可能与新题路径并行，造成旧结果回写或双重推进。
- 通用修法是先取消 Provider 任务并持久化控制结果，再用 `skipped=True` 恢复原 checkpoint；评价节点从持久化 attempt 识别跳过并短路，继续唯一的 `persist_attempt -> advance` 路径。
- 停止评价与跳过语义分离：停止保留回答和当前题，进入可继续评价状态；跳过保留回答作为回放记录，但不生成评价并进入下一题。两类命令均有独立幂等 receipt。

## 2026-07-27：报告确认区被放在错误的轮次分支

- 轮次进入 `report_pending / waiting_for_approval` 后，活动答题工作区已经卸载；原实现却只在活动答题分支内部渲染 `ActionCenter`，因此结果页显示“右侧确认”，实际 DOM 中没有任何确认区。
- 报告列表使用空的 `details`：状态为待确认但没有正文或操作，用户点击标题看不到反馈，进一步放大了“报告点不了”的感受。
- 结果页应拥有自己的“报告列表 + 确认区”布局。确认区按当前 Execution 读取待确认动作，展示报告正文和业务化按钮；报告条目展开后提供显式定位入口，不暴露 draft ID、report kind 等内部字段。

## 2026-07-27：结果页不能由题目和报告共同撑高

- 原结果页把全部题目、评价和两份报告连续平铺；题量增长会持续拉长页面，右侧确认区只能依赖 sticky 和自身最大高度，天然无法与左侧形成稳定工作区。
- 通用布局应把“题目集合”与“当前阅读对象”分离：左侧题目索引内部滚动，右侧只显示一题详情；页面高度不再依赖题目数量。
- 每题深入讨论已经由 `attempt.discussionSessionId` 持久关联，集中管理只需投影现有状态并复用创建/恢复接口，不应另建一套讨论会话存储。
- 报告确认区与结果卡共享同一工作区高度；正文是唯一滚动区，编辑和确认操作保持可达。窄屏改为上下排列，避免继续压缩正文或产生横向滚动。

## 2026-07-27：两份报告不是两个同时可确认的 Action

- 复习 Graph 先生成复习报告和掌握度更新两份草稿，但人工确认动作按顺序创建：只有当前草稿存在 pending action，处理完成后才进入下一份。
- 原页面只把“打开确认区”当作滚动和聚焦，没有传递报告 ID，因此两份报告看起来都能点，右侧却始终停留在同一个 action；这是按钮“无反应”的直接原因。
- 页面选择必须以 pending action 的 `preview.draftId` 识别“当前待确认”，不能用报告数组顺序或是否存在 publication 猜测。用户可以预览确认顺序，但未轮到的报告必须显示受控说明，不能伪造可确认按钮。
- 左右分栏属于同一个任务工作区：默认并排用于对照，任一侧都应能收起，让当前阅读任务获得完整宽度；移动端不应隐藏任一业务内容。

## 2026-07-27：报告动作状态不能决定工作台是否存在

- 第一份报告确认后，Execution 会短暂从 `waiting_for_approval` 进入 `running`，用于推进 Graph 并准备下一份 Action；这是正常的运行状态变化，不是路由跳转。
- 如果前端只在 `waiting_for_approval` 时挂载报告栏，确认成功会立即卸载当前阅读对象，用户感知就是“页面跳走”；工作台可见性应由轮次是否仍有待处理报告和用户是否正在查看报告共同决定。
- 已确认报告是持久化业务产物，不应在 Action 解决后失去正文。轮次资源必须继续返回 Markdown，操作状态与阅读权限分离：确认/退回动作只能执行一次，报告正文可以反复回看。
- 选中报告不应在查询刷新时被初始化逻辑覆盖；确认后保留刚处理的报告，下一份通过显式“继续确认”进入，避免非用户触发的焦点跳转。

## 2026-07-28：版本删除不能等同于材料删除

- `profile_materials` 表示一份逻辑简历，`profile_material_versions` 才表示一次上传。只提供材料级永久删除，会迫使用户在“保留测试版本”和“清空所有版本”之间二选一。
- 版本删除的清理边界落在目标版本，但安全门禁必须覆盖整个 Workspace：只要还有任一待确认 Proposal，所有版本都不能删除。待确认项可能跨版本复用历史 Evidence，不能仅凭当前直接引用关系推断某个版本已经安全。
- 预检与执行必须重复检查同一门禁；若预检后新增待确认信息，执行返回稳定的 `profile_material_version_has_pending_proposals`，不能降级成模糊的“影响发生变化”。
- 删除当前版本会改变材料聚合状态，因此替代版本选择、材料版本号递增、Evidence 墓碑和文件引用清理必须处于同一受控执行链；仅在前端切换选中项会留下悬空当前版本。
- 保留已删除版本的最小墓碑并从普通查询隐藏，既避免版本号复用和审计断裂，也不把已清除文件继续呈现给用户。
- 删除影响预检不能只返回 Claim 类型和内部 ID。用户要决定“保留”还是“同时删除”时，必须看到当时确认的结构化内容快照；否则多个同类型要点无法区分。
- 批量处理必须基于显式选择集：复选框、全选、已选数量和“仅修改所选”组成同一交互闭环，未选择的要点保持原决定；受保护项即使被选中也不能被批量改成删除。

## 2026-07-28：岗位分析并非没有进度，而是前端隐藏了过程

- 岗位分析接口已经提供当前阶段、完成数、活动任务、单次/累计耗时、最近更新时间和已保存产物；原页面只展示 `5/5` 与“查看详情”，导致真实运行数据没有形成过程感。
- 分析可见性应公开稳定的业务阶段，不展示模型思维链。页面使用“读取岗位内容、核对个人资料、分析项目相关性、整理分析结果、等待你确认”五步，并继续强调逐步保存。
- 运行中或暂停时默认展开过程；结束后仍可回看。最近更新时间统一转换为北京时间，避免再次出现时区不一致。
- 左侧目标列表属于辅助导航，桌面端可收起为图标栏，但仍保留目标切换能力；平板和移动端继续使用紧凑下拉选择，不增加无意义的收起状态。

## 2026-07-28：删除结果不能只停留在删除弹窗

- 版本删除已经把“保留简历要点”写成 `support_status=unsupported`，但统一画像投影没有返回该字段，用户关闭弹窗后看到的卡片和来源文案都没有变化，无法判断删除是否生效。
- `unsupported` 是画像内容状态，不是删除页的临时状态。统一画像 API 必须持续返回它；原简历来源在投影层改为“原来源已删除，本人保留”，画像总览同时给出缺少依据总数和逐项标识。
- 删除完成摘要应保留在当前页面，明确区分“已从画像移除”“保留但缺少来源”“仍有其他来源支持”，并提供直达画像入口；刷新后临时摘要可消失，但画像上的依据状态必须持续存在。

## 2026-07-28：来源核对入口与画像会话状态筛选

- “待确认建议”与“已确认画像的来源状态”是两套不同队列。原页面只显示来源异常数量，却没有独立入口，用户无法集中查看；不能把这两类状态继续混入“待确认”页签。
- 画像来源核对现按 Claim 的 `related/conflicted/unsupported` 状态形成独立列表，并保留从职业名片数量、顶层页签、状态筛选到具体画像编辑器的完整路径。
- `agent_sessions.status` 是会话生命周期，通常会保持 `completed`，不能代表当前模型任务是否运行或失败；运行态必须读取最新 Execution，待处理态还要合并未解决 Action 数量。
- 会话列表 API 现投影 `latestExecutionStatus` 与 `pendingActionCount`。前端“正在运行”按 Execution 活动态筛选，“需要处理”按失败/中断/取消或待处理 Action 筛选。

## 2026-07-28：来源核对页再次发生内容裁切

- 根因不是卡片数量，而是新页面虽然被标记为工作台，却没有复用共享 `TaskWorkspace/TaskWorkspacePane`；父容器通过页面专属类名名单分配高度，新页面遗漏后被外层 `overflow: hidden` 裁切。
- 修复不能停留在给名单补一个类名。来源核对页已接回共享工作台组件，父容器同时识别通用 `.task-workspace` 标记；标题与筛选占固定行，卡片列表是唯一滚动区。
- 移动端继续恢复自然文档流。布局准则新增强制复用共享工作台组件的条款，避免后续子页再次复制一套高度计算。

## 2026-08-02：渐进报告必须同时投影持久结果与响应式焦点

- `interview_gaps` 已经随逐题分析落库，但原报告资源只返回 analysis，导致前端无法展示四类差距。领域报告契约必须投影 gap，而不能让页面从原始工作项 JSON 反推。
- 渐进列表的默认焦点属于持久业务状态的视图规则：失败优先，其次高风险、已完成；一旦 URL 中的用户选择仍有效，新结果到达不能抢走焦点。
- 768 宽度下，应用侧栏、复盘记录栏、问题栏和详情四层并排会把正文压缩到 247px。1023 以下应把问题栏与详情改为上下布局，390 再把外层记录与详情改为自然单列。
- 共享 `.task-workspace` 的后加载 `display:grid` 会覆盖同权重的移动端 `display:block`。页面断点应使用组件双类名提高选择器优先级，避免依赖 `!important` 或页面高度计算。

## 2026-08-02：面试复盘候选与跨领域写入边界

- 候选生成必须读取已落库的 confirmed QuestionUnit 和 formal QuestionAnalysis；模型输出本身不能直接触达题库、画像、项目叙事或 Knowledge。
- 相似题分数只用于展示匹配选项，不能自动合并。`link_existing` 必须再次读取目标领域的当前资源并验证 Workspace。
- `create_new` 进入 Review 自己的 `review_pending` 草稿/候选链，不直接激活正式题目；只有已关联的 active Review Question 才能生成“立即练习”链接。
- Profile 与项目叙事通过 Profile 所有者创建带 `agent_inference` 来源的待确认 Proposal；复盘 Receipt 只在领域调用成功后落库。
- 被拒绝候选以 fingerprint 保留，重复 finalizer 不重新打开；批量部分失败只把失败项留在 failed，成功项及其 Receipt 不回滚。
- Knowledge 发布草稿只从确认问题、正式分析、已确认经历、行动项和稳定链接投影，原始转写、pending 推断、Prompt、Provider 响应和聊天消息没有进入渲染输入。

## 2026-08-02：面试复盘候选审核界面边界

- 逐题复盘、准备资产、行动与发布是同一场复盘的三个视图，入口必须始终可见；切换候选分组不能让其他分组消失。
- 候选批量操作只能提交用户明确勾选的稳定 candidate ID。刷新后成功项退出待处理计数，failed 项继续处于可选状态并显示稳定错误原因。
- Profile 项目建议不能依赖前端临时拼装完整领域对象；后端适配器从候选事实生成合法默认 proposal，更新已有项目时先合并当前确认版本，再交给 Profile 领域校验。
- “立即练习”只在正式 Review Question 已关联后展示；Review 待确认候选不能伪装成可练习题目。
- 发布界面只提供安全章节选择，不出现原始转写选项；草稿生成后提供返回 Knowledge 的明确入口。

## 2026-08-02：复盘对话纠正与局部重算边界

- 复盘对话复用用户可见 chat Session，但模型只获得七个精确只读 Tool；Workspace 与 retrospective ID 由服务端 `AgentContext` 注入，模型参数只允许当前复盘内的 question ID 或搜索词。
- 普通解释只追加消息，不创建分析版本。题目文字、片段归属、说话人和结论重判必须先持久化为 pending 纠正建议；拒绝只改变建议状态。
- 问题文字/片段/结论纠正保留原 CleanupVersion，创建一个局部 AnalysisRun，只调度目标问题与 gap、candidate、projection 三个 finalizer；其他问题分析复制到新运行，报告不会在局部重算期间丢失。
- 说话人纠正属于整理证据变化，必须复制为新的 CleanupVersion 并重新执行整场问题提取，不能原地修改已确认整理版本。
- 确认命令在调度模型前先保存确定性变更、结果版本和建议状态；即使后台模型失败，也保留可恢复的新版本，不会重复应用同一纠正。

## 2026-08-02：面试复盘聚合与生命周期收口

- 求职目标聚合只读取非回收复盘及其 active AnalysisRun，返回场次、最近轮次/结果、未完成行动项与四类 gap 数量；不复制报告正文，也不制造跨轮次总分。
- 清除原文是不可逆的能力降级，不等同于删除复盘：源正文、整理片段正文、工作项输出和分析摘录被清空，哈希、结构化结论、行动项及已发布的外部资产继续保留。
- `activeSourceVersionId` 仍用于稳定指向历史源版本，因此 API 另外投影 `activeSourceAvailable`。页面据此隐藏重复清除和重新整理动作，并明确显示“原文已清除”。
- 永久删除只删除复盘私有聚合；复习题、画像/项目 Proposal 与 Knowledge 草稿属于各自领域，删除影响预检必须明确说明保留边界，并要求输入“永久删除”。
- 创建复盘包含“保存原文”和“启动整理”两个提交边界。模型未配置时后者失败，页面仍必须关闭创建弹窗、选中已保存记录并提示稍后继续，否则会诱导用户重复创建。
- 实页验收发现 disabled cleanup query 被手工 `refetch()` 后会请求 `/cleanup-runs/null`。禁用查询不是不可执行查询；调用方必须在稳定 ID 存在时才显式 refetch。

## 2026-08-02：复习模式与题目范围必须分离

- 随机混合、薄弱优先、专题复习等是选题策略；自主、岗位、项目是题目来源范围。把“项目专项”做成新模式会把策略和数据边界耦合，后续无法在项目范围内继续使用薄弱优先等策略。
- 范围只保存稳定来源 ID 和用于展示的冻结名称，实际题目仍使用既有 Catalog 元数据筛选；轮次创建后继续冻结 Question Snapshot，不复制岗位或画像事实。
- 范围匹配为零时必须阻止创建并说明原因，不能退回全部题库，否则用户以为在练岗位题，实际练到无关题目。
- 旧轮次 settings JSON 没有范围字段时默认 `ordinary`，因此不需要数据库迁移，也不会改变既有复习历史。

## 2026-08-02：复盘整理的运行可见性与失败恢复

- Session 的 `visibility=system` 只决定它是否出现在普通会话列表，不能把一个 Registry 中的业务 Agent 变成系统 Agent；运行中心是否默认可见必须以可观测 Registry 的 `system` 分类为准。
- 历史复盘 Session 使用 `.analysis` / `.chat` graph ID，新运行改用规范的 `interview.retrospective`；可观测与质量评估入口必须解析旧别名，避免已有运行永久消失。
- Cleanup 正式段落只在所有窗口完成后落库，但每个完成窗口已经保存结构化输出。运行中或失败时应从工作项投影只读的部分结果，并公开完成数、总数、当前窗口和稳定错误码。
- 实际 9,850 字首窗口发生 Provider 超时，原 24,000 字窗口过大。初步修复曾改为 6,000 字、500 字重叠，长文本调度增量又收紧为自然边界优先的 4,000 字、400 字重叠；尚无任何完成窗口的旧失败任务在重试时安全重排，已经有部分成果的任务绝不删除已保存窗口。

## 2026-08-02：一小时转写不能依赖串行窗口与 SDK 隐式重试

- 设置页连接测试只发送 `ping` 并要求 1 Token；Cleanup 自动测试使用确定性 Fake。二者都不能证明近万字结构化输出能在真实 Provider 时限内完成。
- 原 Cleanup 没有专用调用策略，Anthropic 兼容客户端按默认 30 秒及两次隐式重试形成约 91 秒黑盒等待。长任务必须关闭 SDK 隐式重试，由持久工作项记录每次应用尝试。
- 单纯缩小窗口仍会让一小时转写串行等待。安全并发边界为首窗串行建立说话人提示，后续最多并发二；Worker 只写各自输出，Reducer 继续独占正式片段顺序。
- 重叠窗口不能只靠文本完全相同去重。窗口必须区分可读上下文和允许输出范围，以 `emitFrom` 阻止模型重复输出重叠区。
- 超时不能重跑整场。大窗口原子替换成更小持久窗口；单窗失败继续处理其他窗口，最终以 failed + 部分结果等待用户重试。

## 2026-08-02：问题提取必须按证据段落 Map/Reduce

- Cleanup 分窗只能解决说话人整理；原分析仍把前 60,000 字一次送入问题提取，超过部分会静默遗漏，不能支撑一小时转写。
- 问题窗口必须沿用用户已确认 Segment，而不是重新按原文字符切割；这样锚点、说话人修正和后续逐题分析共享同一证据 ID。
- 相邻窗口的语义连续由原始段落重叠负责，不能把上一窗自然语言摘要当作下一窗证据，否则候选人单边录音容易累积模型推断。
- 去重键不能只看问题文字。同一问题在不同位置重复出现是两次面试事件；同锚点才合并证据，不同锚点必须保留。
- 正式 QuestionUnit 必须等全部 Map 成功后再由确定性 Reduce 创建。失败时可以展示窗口进度，但不能把不完整题目集合伪装成整场结果。

## 2026-08-02：转写修订必须成为可审计证据层

- 手机录音转写的错别字和技术词错误会污染后续问题识别与分析，但“语言更通顺”不能成为覆盖原文的理由；不可变 SourceVersion、模型建议、用户决定和最终采用正文必须分层保存。
- 低风险格式/识别修订可自动采用；否定、数字、主体和技术结论一律升级为高风险。未解决高风险项是确认门禁，不是普通提示。
- 整段手动编辑表达了比逐条模型建议更高优先级的用户决定。同一批请求同时出现手工正文和旧 correction decision 时，应保留旧修订为 superseded 审计历史，但不能让旧决定反向覆盖手工正文。
- Cleanup 的窗口完成数可以作为确定进度，当前窗口运行时长只能作为活动反馈；刷新后的计时必须来自服务端工作项时间，不能从页面挂载时间重新开始。
- 运行中心的绿色只表示 Provider 已返回，不表示对象正文“正确”。对象数组应使用普通矩形字段块，只有基础值数组适合紧凑胶囊标签。

## 2026-08-02：长文本结构化输出的容量与证据正确性必须分开解决

- 真实 Cleanup Trace 中，成功窗口已返回 40～60 条修订并消耗 7,356～8,159 输出 Token；失败响应统一由 Provider 以 `stop_reason=max_tokens` 截断，不是后端主动截短完整 JSON。
- 即使响应完整，模型生成的绝对 offset 与 `originalText` 在真实样本中仍无法通过不可变原文校验。只提高输出 Token 只能缓解容量，不能修复证据正确性。
- Cleanup 协议改为由程序切稳定 Source Unit 并拥有 offset；模型只返回 `unitId`、说话人和 `correctedText`；程序通过 Diff 物化 CorrectionRecord，并保守升级数字、否定、时间和不确定改写。
- Cleanup 关闭结构化 Tool 内部自动纠错。一次 Provider 响应失败后回到持久工作项层；超时、截断和 Schema/单元不一致只拆分当前窗口，不解析残缺 `raw_arguments`，不重放已完成窗口。
- 这是“模型负责语义、程序负责事实与门禁”的 Tradeoff：增加了单元切分和 Diff 规则，但换取了可估算的输出规模、可证明的证据位置和有界恢复。

## 2026-08-02：高级运行详情的“实时”是索引刷新，不是残缺结构化响应流

- Trace 中间件在 Provider 调用前落 `model.request`，只在完整响应返回后落 `model.response`；对于 Tool/Schema 输出，这是正确的原子边界，不能为了视觉流式而渲染尚未闭合的 JSON。
- 原页面三个 Query 都没有刷新策略，因此进入详情后只看到进入时的静态快照。运行态应刷新执行摘要、Operation 和事件索引，并在终态转换时补一次收尾读取，防止执行状态先于最终索引可见。
- 等待用户输入/确认不是后台模型仍在生成，不应持续轮询；首版只对 `queued` / `running` 刷新。

## 2026-08-02：字符 Diff 不能直接等价为用户审核任务

- 真实一小时转写产生 1,006 个 pending 高风险项，不是存在 1,006 个关键语义错误，而是模型轻微润色后，`SequenceMatcher` 的每个非格式差异都被默认升级为高风险。
- 程序可承载这些记录，但用户无法逐条审核；同时原更新命令最多接受 1,000 条决定，导致页面即使提供批量操作也无法处理该真实数据规模。
- 修订应分成三类：确定安全则自动采用，关键语义变化则人工确认，无法唯一判断的普通措辞变化则保留原文并丢弃建议。Diff 负责定位，不负责制造待办。
- 历史运行无法重新解释 Provider 输出时，最安全的恢复动作是批量保留原文；新运行通过严格 Prompt 和物化过滤避免再次产生修订爆炸。

## 2026-08-02：对话还原失败的主因是输出契约，不只是 Prompt 文案

- 旧契约强制一个 Source Unit 只返回一个说话人，并禁止拆分；当单元同时包含提问和回答时，模型即使理解说话人切换也无法表达。
- “直接交给聊天模型”看起来效果更好，是因为模型同时执行了 ASR 纠错、对话轮次切分和问题反推；产品实现必须把三者的数据性质分开，避免推断问题冒充录音原话。
- 让模型返回字符 offset 不可靠；让每个轮次重复完整原文又会放大输出。折中方案是单轮次默认覆盖整个稳定 Source Unit，仅在多轮次时返回逐字局部 `sourceText`，由程序验证完整覆盖并计算 offset。
- 候选人单边录音中恢复问题是合理能力，但应落在已有 QuestionUnit 的 `origin=inferred`、`answerSegmentIds` 和 `inferenceBasis`，而不是插入 Cleanup Segment。

## 2026-08-02：运行详情固定多出 480 分钟是 SQLite UTC 字符串被当成本地时间

- Runtime/SQLite 返回的无时区时间形如 `2026-08-02 09:00:00`，项目约定其语义为 UTC。
- 高级运行详情使用浏览器 `Date.parse`，在北京时间环境把它解释为本地 09:00；与真实当前 17:00 相减后固定多出 8 小时，即 480 分钟。
- 项目已有 `parseApiTimestamp` 将 SQLite 格式显式补为 `Z`。实时耗时与其他业务页面必须复用该入口，不能直接解析无时区字符串。
## 2026-08-02：Cleanup Schema 失败被误判为窗口过大

- 真实 18:18 Provider Trace 证明重复输入并非普通 400 字窗口重叠：首个 `0–3973` 窗口在应用校验失败后被拆成 `0–2159` 等子窗口，父子请求重复 2,159 字；部分子窗口随后又被原样自动重试。
- Provider 的主要不兼容是省略可确定的 `displayName`、偶尔省略按顺序可恢复的 `unitId`，以及多轮次未返回逐字 `sourceText`。这些属于输出契约适配问题，缩小输入窗口不能修复。
- Cleanup 现在由程序补齐显示名和缺失的顺序单元 ID；多轮次完全缺少边界证据时安全合并为一个 `unknown/待确认` 段，不伪造 offset。
- 只有超时和输出截断可以拆分窗口；Schema/结构化输出缺失不再自动拆分或原样重试，首窗出现全局契约错误时立即失败，避免继续消耗后续窗口 Token。
- 用户显式点击继续时重新武装所有未完成窗口并重置其尝试预算；已完成窗口及输出保持不变，因此修复前的部分失败运行可以直接继续，不需要从头创建。

## 2026-08-02：复盘整理核对页面认知负担

- 原页面把段落、说话人、全部文字修订、批量兜底和生命周期动作同时铺开；三栏本身不是问题，问题是每一层都拥有相同视觉权重。
- “高风险待处理”与“格式整理 + 模型置信度”同时出现，会让用户误以为标点修改也需要逐项决策；置信度是模型诊断信息，不是用户决策依据。
- 工作台继续保留队列与详情，但详情改为单项核对器；自动整理只提供折叠审计，关键修改处理后自动推进，低频和生命周期操作降级到菜单。

## 2026-08-02：模型建议稿与审核正文差异的真实原因

- 前端没有取错字段；原实现让运行中心展示 Provider 的 `correctedText`，复盘核对页却展示确定性门禁重建的 `SegmentRecord.body`，因此产生两套正文。
- 原分类器只自动采用格式变化和“Diff 建议文本本身等于术语提示”的变化，因此口头禅、紧邻重复以及术语内部单字修正会被静默恢复为原文。
- 真实响应证明逐 opcode 白名单会把完整 `correctedText` 几乎全部静默恢复为原文，并产生 `corrections=[]`。正确边界是先在整轮层面拒绝低相似度、异常长度和明显内容搬移；通过门禁后，普通 ASR 错字、口头语和断句修正自动采用，数字、否定和职责升级继续阻塞。
- 当前改为审核页直接显示 `correctedText`；确定性门禁只决定是否需要用户确认以及最终采用模型稿、原文或手工稿，不再偷偷改写可见正文。
- Provider 还会在多轮输出中省略第一轮 `sourceText`，甚至格式化后续证据标点。模型证据只能作为轮次起点锚点；程序在内容锚点唯一且高相似时从不可变原文重建正文，任意中间缺失、定位歧义或内容差异过大仍必须拒绝。

## 2026-08-02：首窗直接失败来自 Provider 修改证据标点

- Execution `2943dfa5-3b85-48d6-8796-a9699a5bfb25` 在 27.5 秒内正常返回 6 个 Source Unit，失败不是超时或截断，而是后端物化阶段的 `schema_validation_error`。
- `unit:2247:2920` 的首轮 `sourceText` 被省略，后续证据又把原文“然后的话呃出于”改成“然后的话呃 ，出于”。旧恢复逻辑要求后续证据构成逐字精确后缀，因此拒绝首窗；首窗失败后调度器按防浪费策略不再调用后两个窗口，所以页面表现为直接失败。
- `sourceText` 不能继续被当成最终证据正文。程序现在只用其去除标点后的唯一前缀定位轮次起点，再从不可变 Source Unit 切出真实正文和 offset；锚点内容相似度不足、中间缺失或定位不唯一仍拒绝。
- 同一次真实响应在新逻辑下离线重放成功，得到 8 个连续段落，角色顺序为 4 个 candidate、1 个 interviewer、3 个 candidate。
- 重试 Execution `24842e8a-f4d8-4348-8c3a-469b26c742ce` 又暴露第二种违约：第三轮 `sourceText` 不只是格式化标点，而是几乎直接复制了 `correctedText`。轮次边界仍可由其开头的唯一原文锚点确定，因此不应拿整段 `sourceText` 做证据相似度门禁；真正的正文安全性应由不可变原文切片与 `correctedText` 的整体有界 Diff 负责。
- 第二次真实响应在修复后同样离线重放成功为 8 段；后端开发进程使用 `uvicorn --reload`，无需手工重启即可加载修复。

## 2026-08-02：复盘整理重试仍失败的真实根因

- 真实 Execution `025f877c-084f-4a1d-a543-e16f497b9d69` 并非 Provider 全部不可用：首窗成功，后两窗分别因为只返回 2/3 个 emit Source Unit，以及多轮 `sourceText` 无法逐字覆盖不可变原文而失败。
- 原实现把“单元缺失”和“轮次边界不可证明”都升级成整个窗口的 `schema_validation_error`；显式重试会再次遇到同类非确定性输出，因此用户看到连续任务失败。
- 修复边界调整为：响应整体可解析时，Schema 漂移只降低受影响单元的自动整理质量。缺失/未知单元保留原文并标记说话人待确认；边界不可证明时合并完整 Source Unit 为单段。程序持有的原文和 offset 始终是唯一证据权威。
- 三组真实响应离线回放结果：首窗 expected/returned `6/6`；第二窗 `3/2` 并安全补齐 1 个原文单元；第三窗 `5/5` 并对不可验证边界执行单段降级。三窗均不再抛异常。
- 新鲜验证：复盘后端定向回归 `118 passed`，相关 Ruff 检查通过。

## 2026-08-02：转写 Cleanup 必须以完整文档为 Artifact

- 真实一小时样本证明，模型窗口、Source Unit、说话人 turn、字符 Diff 和用户审核段落不能共用同一业务颗粒；否则内部处理规模会直接变成上千项用户操作。
- DeerFlow 的 Artifact/Context Engineering、LangGraph 的 Map-Reduce、GraphRAG 的 Document/Text Unit 分层和 Haystack 的 Cleaner/Splitter/Writer 流水线都指向同一边界：切片用于容量、隔离和来源追踪，最终产物仍是完整文档或报告。
- 新设计以 `CleanTranscriptVersion.body` 作为 Cleanup 唯一用户产物；WindowResult 和 Diff 留在运行/诊断层，只有无法安全决定的术语、数字、主体和职责变化形成稀疏 ReviewIssue。
- 问题提取只读取 confirmed CleanTranscriptVersion，并在确认后确定性生成 Anchor；不再读取模型 turn 直接持久化的段落队列。
- 真实验收必须加入与“直接把同样文本交给同一模型整理”的盲测基线。接口成功、自动测试通过和 Trace 可读都不能替代最终文档质量。
# 2026-08-02：审核段落应该直接显示模型整理稿

- 之前 Materializer 对高风险 Diff 自动恢复原文，导致段落正文与 Provider `correctedText` 不一致；再从 Trace 临时查响应只制造了第二套正文来源。
- 审核阶段现在以 `correctedText` 作为可见候选稿；风险由 Correction 门禁表达，而不是通过偷偷换回原文表达。
- `pending` 不等于采用已确认：它只表示页面先展示模型建议，但用户未决定前不能确认整理结果或进入分析。

## 2026-08-02：单文档实现后的边界结论

- 产品正文与内部计算颗粒已经分离：目标窗口可拆分、重试和并发，只有拼接后的 `document_body` 能进入人工核对与后续题目提取。
- 上下文重叠不能进入 Provider 的所有权输出。窗口协议必须显式区分 `beforeContext / targetText / afterContext`，否则任何 Reduce 去重都只能依赖脆弱的文本相似度。
- 对长文档最稳妥的确认边界不是保存模型 turn，而是确认完整文档后由程序按自然段和有界长度生成证据锚点；它既能支撑 QuestionUnit 的证据引用，又不会把锚点数量暴露为用户任务数。
- 整篇编辑后 ReviewIssue offset 只适用于当前审核会话，因此问题决定必须与最终全文一起保存；确认后全文不可原地修改，后续变更创建新 CleanupVersion。
- 删除源材料时，仅清数据库派生正文仍不足以覆盖诊断 Trace；Trace 有独立保留策略和清理流程。业务清除与诊断保留是否强制联动仍是未关闭的隐私边界，不能在浏览器验收前略过。

## 2026-08-03：准确转写双栏比例被通用断点规则反转

- 单文档工作台默认把完整正文设为主栏、待确认项设为 280–360px 辅栏；但 `max-width: 1023px` 下更靠后的 `.cleanup-workbench__workspace` 通用规则重新把第一栏固定为 240–280px，并让第二栏占满剩余空间。
- 结果是在常见 1024 附近视口中，正文编辑区比待确认区更窄。修复必须在同一断点为 `clean-transcript__workspace` 明确恢复“正文约 64%、辅栏约 36%”，而不是继续修改默认桌面规则。
- 768–899px 可用详情宽度不足以稳定容纳两栏，改为上下布局；右侧长原文仅作为核对预览，限制高度并内部滚动，避免挤压主要文档。
- 待确认列表原先使用内容高度行，下面的长详情参与 Grid 尺寸计算后会把列表压缩到接近 0，只剩上下边框。列表必须拥有 160–280px 的稳定可见区，详情占剩余空间并独立滚动。

## 2026-08-03：单文档核对页仍存在三块等权竞争

- 修复正文/待确认双栏比例后，外层复盘列表仍在 1024px 附近占 34vw；它与内层正文、待确认栏叠加后形成三块近似等权区域，用户无法一眼判断当前主任务。
- 复盘列表是导航，不是核对内容。选中记录后应限制在 220–300px，并把剩余宽度优先给完整文字；待确认区继续作为稳定辅助栏，而不是再次平分详情区。
- 页面标题、生命周期控制、列表标题、生命周期菜单和核对标题连续堆叠时，会在正文前形成多层横向分隔。无需删除功能，但必须收紧垂直间距，让“完整文字 + 待确认问题”更早进入视野。

## 2026-08-03：问题提取上下文与结构化输出膨胀根因

- `_analysis_context_snapshot` 同时服务问题提取和逐题分析，使提取请求无条件携带岗位文档摘录和已确认画像 Claim；这些数据既不是“面试中问了什么”的证据，也会增加隐私暴露、Token 和履历补题偏差。
- `QuestionExtractionOutput` 直接作为 Provider Tool Schema，把 `ordinal`、`anchorSegmentId` 和分类等确定性/非关键字段交给模型；真实响应漏掉这些字段后产生批量 Pydantic 校验错误。
- ToolStrategy 的 `handle_errors=True` 会把无效响应与校验错误重新注入同一 Agent 调用，应用层又对整个窗口自动重试，因此错误请求不是恒定大小，而是发生上下文膨胀。
- 修正后提取使用独立 `QuestionExtractionModelOutput`：模型只返回问题语义和证据；程序分配序号、锚点并校验证据范围。提取输入固定为 `transcript_only`。
- Schema 隐式回灌关闭；首次错误最多用错误候选及其引用证据做一次紧凑修复，第二次失败或越窗证据直接停止当前窗口，已完成窗口仍保留。

## 2026-08-03：逐题分析失败不是单纯的超时参数不足

- 真实失败请求把冻结 `contextSnapshot` 中的完整画像和岗位文档重复发送给每一道题；单题输入随画像增长，既增加延迟与隐私暴露，也让无关履历干扰当前问题分析。
- 旧逐题 Agent 没有显式 `ModelInvocationPolicy`。Provider 约 30 秒超时后被 SDK 默认重试两次，最终表现为单题约 90 秒才失败；单纯调大超时只会继续放大最坏等待。
- 修复采用三层边界：请求层按题检索证据并设置硬上限；调用层关闭 SDK 隐式重试；工作项层按题隔离、应用级最多两次尝试，预算耗尽后继续处理其他题。
- 最终汇总依赖全部逐题结果，因此某题耗尽预算时运行仍标记失败，但失败发生在其他题推进之后；恢复同一 AnalysisRun 时，已完成的问题提取和逐题结果不会重算。
- 该模式可承受未来 `QuestionExtractionContext` 增长：冻结全量上下文只作为证据仓，模型调用读取经过检索和预算裁剪的视图，输入不会随资料总量线性增长。

## 2026-08-03：复盘讨论 SQLite 锁与模型请求 Trace 缺失

- 真实失败不是模型未调用：首轮 `model.response` 已返回 Tool 计划，随后并发只读 Tool 在审计和产品事件写入之间触发 `database is locked`，因此没有进入第二轮模型请求。
- `ProductEventStream.publish` 在异步事件循环直接执行同步 SQLite 写入；当它等待异步 Tool 审计持有的写锁时，会阻塞持锁协程继续提交，WAL 和 `busy_timeout` 无法修复这种调度互锁。
- `model.request` 缺失是另一条独立故障：真实 LangChain Tool 被当作普通 Pydantic Model JSON 序列化，其参数 Schema 含 Python Model 类，Trace fail-open 后业务继续执行但请求事件静默丢失。
- 修复把产品事件同步写入移到工作线程，保留有界锁重试；Trace 对 Tool 只记录公开合同，并为 Pydantic 序列化增加不可抛出的降级路径。
- 该问题属于所有共享 SQLite 的 Agent 运行时边界，已记录独立 Tradeoff ADR：`docs/superpowers/architecture-decisions/2026-08-03-async-sqlite-agent-runtime-write-boundary.md`。

## 2026-08-03：复盘讨论上下文与 Tool Call 恢复边界

- 旧实现把最近 12 条产品消息嵌入当前 `HumanMessage.recentConversation`，固定条数既不能约束 Token，也让消息级压缩无法识别完整问答轮次。
- 复盘讨论的 7 个 Tool 均为本地、有界、只读查询；当前没有必要为它们引入持久化 Checkpointer 和 ToolInvocation 状态机。取消中途调用后由用户重试安全重放，成本和一致性风险更低。
- 产品消息是跨运行的长期事实；`AIMessage.tool_calls` 与对应 `ToolMessage` 是单次运行态。两者不应写入同一产品消息表，否则恢复时容易重复工具调用或污染用户可见对话。
- 新上下文装配器按 Token 预算从新到旧选择完整 `user + assistant` 轮次，忽略未完成的历史 user 消息，并把各角色恢复为独立 LangChain Message；当前请求只保留消息、选中题目和裁剪统计。
- LangChain Summarization 的安全 cutoff 会在切点落入 `ToolMessage` 时回退到对应 `AIMessage(tool_calls)`，因此不会制造孤立 Tool 结果；取消检查位于模型调用后、助手消息落库前，保证不保存半截回复。

## 2026-08-04：复盘后续动作与质量页不能混用内部状态和用户决策

- 行动项的 `completed / dismissed` 只是当前复盘里的整理状态，并没有产生外部副作用；把它们做成不可撤销会迫使用户害怕试用勾选和忽略。
- 候选的拒绝状态在尚未写入目标领域前同样只是筛选决定；恢复时必须复用原候选和 fingerprint，不能重新生成一条候选。
- “发布”在这里实际是生成一个可继续审核的 Knowledge Draft，不是对外公开；用户界面应说“生成复盘文档”，架构层继续保留 Draft/HITL/Receipt。
- 单次运行质量页最严重的问题不是维度多，而是来源不可信：指定 Execution 没有报告时旧页面会显示另一条历史报告。质量页必须先锁定来源，再谈对比；对比结果必须合同兼容且由用户显式开启。
- Token、Runtime 和检查配置是诊断信息，不应与“能否使用、先处理什么”同级常驻。

## 2026-08-04：注册门禁必须区分新建 fail-closed 与历史读取 fail-open

- 只在 `ProductionGraphFactory` 遇到未知 kind 时失败已经太晚：Session 和 Execution 已经落库，运行中心会留下无法解释的脏任务。
- 新建边界必须先校验注册、生命周期和 `user_creatable`，并在任何数据库写入或 Provider 调用之前返回稳定错误。
- 历史数据不能复用同一 fail-closed 规则，否则已删除 Agent 的运行会从运行中心消失；历史投影必须无 Builder、无控制能力、无业务跳转，只允许查看。
- 测试或诊断 Harness 使用的临时 Graph 应通过构造时注入的测试门禁显式声明，不能迫使生产 Registry 收录只为测试存在的 Agent。

## 2026-08-04：质量支持能力不能从当前运行操作反推

- 运行时 `capabilities` 是“现在允许做什么”的动态集合；未完成运行会移除 `manual_judge`，因此它不能回答 Agent 是否在架构上支持质量检查。
- 质量支持能力必须来自 Execution 冻结的 Agent Definition Snapshot 中的 `eval_pack_id`；当前是否可开始检查再叠加运行状态判断。
- 历史运行需要保留创建时合同，不能用当前 Registry 反推，否则新增 Eval Pack 后旧运行会被误报成当时已经支持检查。
- 报告汇总和优先问题必须共享同一个 `dimensionOutcome` 判定；对 `insufficient_evidence` 另写过滤条件会产生“有关注项但没有问题”的用户矛盾。

## 2026-08-05：质量检查可读性不是逐项翻译问题

- 英文检查名来自未知维度直接展示内部 `dimension_id` 的兜底逻辑；只补翻译仍会让业务质量和 Runtime 保护规则争夺同一视觉层级。
- 用户首先需要知道结果是否可用、哪里需要确认；任务归属、幂等写入、迟到结果和来源追溯属于系统可靠性检查，应默认折叠。
- Receipt、Event、hash、locator 和原始缺口代码是排障证据，不应进入结论、优先事项或默认展开的检查说明。
- 无历史基线时展示“之前 / 变化”只会产生两列横杠；单次报告应只保留“检查内容 / 本次结果”，由用户显式开启历史对比后再增加变化列。

## 2026-08-05：动态总结不能依赖父级 Grid 自动落位

- 历史检索父容器原本只有一个弹性内容行；总结动态插入后先占用该行，检索工作区被推入隐式行，在固定高度与 `overflow: hidden` 组合下发生视觉重叠。
- 仅给总结设置 `max-height` 不足以解决问题：Grid 的自动轨道仍会按总结的固有高度参与分配，可能把结果区压缩到 0。
- 修复使用一个固定占据父级弹性行的 `history-search__body`，内部显式划分总结洞察区和检索结果区；有总结时最多占 40%，结果区保留其余空间，无总结时结果区占满。
- 5175 实页几何证据：720px 高窗口中洞察区 114px、结果区 171px，边界相接且交叠为 0px。

## 2026-08-05：SQLite 单例应是连接管理器，而不是跨线程共享物理连接

- `check_same_thread=False` 只关闭 SQLite 的线程归属检查，不会让一条物理连接上的 Cursor、事务状态和 `sqlite3.Row` 元数据变成并发安全。
- 应用 lifespan 注入的 Workspace、Provider、Settings 回调会被多个 AnyIO 工作线程并发调用；共享同一物理连接时，一次列表查询可能被另一线程的查询状态干扰，表现为偶发 `IndexError: tuple index out of range`，随即重试又恢复。
- 正确边界仍是一个应用级连接管理器，但它按线程延迟创建物理连接。这样 Repository 无需改接口，同时每个同步请求只使用当前线程的事务和 Cursor。
- WAL 负责读写并发，`busy_timeout` 负责短暂写锁等待；它们不能替代连接隔离，也不能把一个长事务自动变安全。
- 回归测试用一个线程持有事务、另一个线程读取 `in_transaction`：旧共享连接会观察到 `True`，线程连接管理器必须稳定返回 `False`。

## 2026-08-05：后台 LLM 工作必须进入统一运行控制面

- “页面正在检查”不是运行状态：刷新、切页或多端查看后，组件内 loading 无法回答任务是否仍在执行、卡在哪一步、为什么失败。质量检查和画像整理必须先创建一等 Product Execution，再由业务页读取其状态。
- Execution、Trace 与业务结果各自生成 ID 会形成三个事实源。质量检查复用同一 ID 作为 Execution ID、Trace run ID 和 Evaluation report ID，使运行中心、质量页与诊断记录天然可关联。
- `system`、`user_creatable` 和“运行中心默认可见”是三个正交维度。画像抽取和质量检查可以禁止公共 API 直接创建，同时仍应默认出现在运行中心；不能再用 `system=true` 一刀切隐藏。
- 用户进度必须来自 Execution/Operation 的真实状态，而不是按时间增长的假百分比。当前阶段映射为准备检查依据、AI 检查业务结果、保存质量报告；中断、失败与完成均由终态驱动。
- 全局运行角标属于 AppShell 级控制面状态，应由桌面和移动导航共享一个快照与 SSE 刷新源；0 时隐藏，只统计当前工作区默认可见的运行中任务。
- 模型批量设置无需新增第二套配置协议。现有 replace-all API 已具备原子语义，前端只需把用户选择展开到全部角色一次提交，逐项设置继续作为高级调整入口。

## 2026-08-05：运行中心列表不能二次覆盖注册中心可见性合同

- 后端已经用 `run_center_default_visible` 区分“禁止用户创建”和“运行中心默认可见”，但前端仍按旧规则无条件过滤 `system=true`，导致质量检查 Trace 已存在、导航角标也能统计，却无法从任务列表发现。
- 导航角标、列表快照和 SSE 增量必须消费同一个 Agent Definition 可见性字段；否则同一 Execution 会在不同入口呈现相互矛盾的状态。
- 修复后，`quality.evaluate`、`profile.ingest`、`profile.assess` 默认展示；真正的内部 system Agent 仍保持隐藏。可见性由注册中心控制，不由前端根据 `system` 身份自行推断。

## 2026-08-05：题目整理的 section 覆盖不等于题目召回

- 本地 `Java.md` 被稳定切成 112 个 section，但现有确定性 planner 只直接识别 4 个题目锚点；模型随后生成候选只能说明调用成功，无法构造材料中“应有题目”的可靠分母。
- 对同一窗口重复调用同一个生成模型会产生相关性漏题，不能充当独立查漏。新方案必须组合确定性显式锚点、语义 Discovery 和独立 coverage audit，最后由单一 reducer 去重、保留来源并持久化。
- `completed_units == total_units` 只能证明运行完整。发现或 audit 未完成、候选达到上限但后文未审计、或存在失败窗口时，业务状态必须表达为“部分完成/需要查漏”。
- Gold Set 不要求用户从零标注：系统先预标注，人只删除伪题、补漏题和确认拆分粒度。未经人工确认的 manifest 只能诊断，不能形成正式召回率。
- 首个本地草稿绑定 `Java.md` 的 source ID 和 SHA-256，预标注 36 项；原文与 manifest 均保留在被 Git 忽略的本地验证目录，避免把用户材料提交到远端。
- 扩展后的确定性锚点在同一 Java 材料中从 4 项提升到 19 项；对预标注草稿的一对一来源锚点评估为显式题 95%、关键题 75%，但隐式题仍为 0%，说明仅继续堆正则不能替代独立语义查漏。
- 查漏必须是新的 Agent 组件和新的持久化 `audit` 工作阶段，而不是把 Discovery 再跑一次；它读取全文窗口和已有题目索引，只返回缺失题，并与 Discovery 种子统一归并。
- 正式完成语义采用 fail-closed：独立查漏连续两次无法形成合法结果时整批失败并保留已完成工作，不能进入“整理完成”。
- Gold 对齐按来源锚点做一对一匹配，避免同一候选重复抬高召回；草稿状态必须显式 opt-in 才能生成临时诊断，默认只能使用人工确认且 hash 匹配的 Gold。
