# Agent Runtime 框架收敛进度

## 2026-08-02：复盘内快速新建求职目标门禁修复

- 复盘新建流程的轻量目标现在只要求岗位名称；公司与经验/职级明确标为可选，填写公司和岗位后即可保存。
- 后端同步移除“岗位与职级必须同时填写”的旧限制，避免前端放行后接口仍拒绝；仍拒绝只填职级、不填岗位的无效组合。
- 新鲜证据：前端复盘创建/页面测试 `10 passed`，后端目标服务与复盘 API `13 passed`；TypeScript、production build、Ruff 与差异检查通过。

## 2026-08-02：面试复盘桌面空状态与共享按钮回归修复

- 修复复盘页面为条件错误条预留固定 Grid 行导致正常状态把伸展行空置的问题；标题、控制区和工作区现在稳定占用三行，错误条收进控制区，1440×900 下工作区底边与视口底边同为 900px。
- 标题说明改用独立语义类，停止用宽泛 `header span` 命中 Button 内部标签；共享 Button 标签同时强制继承按钮颜色和字体，实页主按钮背景 `rgb(64, 86, 180)`、文字 `rgb(255, 255, 255)`。
- 三个生命周期标签并行读取当前求职目标范围内的真实数量，加载期间显示占位，不再等点击后才显示数字；空集合改为单一整页空状态，不再同时出现空列表和空详情。
- 新鲜证据：页面测试 `7 passed`、TypeScript、production build 与 `git diff --check` 通过；浏览器只读复核覆盖 1440×900 和 390×844，均无水平溢出，控制台 warning/error 为 0，未创建或修改复盘数据。

## 2026-08-02：面试复盘 Task 5 渐进分析后端闭环

- 新增严格的问题提取与逐题分析输出：保留 original/inferred 来源、片段引用、推断依据、证据等级、四类缺口和建议答案，不提供整场总分。
- 分析按 `question_extraction -> question_analysis:* -> gap_verification -> candidate_generation -> final_projection` 持久工作项渐进执行；问题在整场完成前即可读取，单题完成后原子保留。
- 冻结求职目标、当前 JD 摘要、已确认画像版本与有限条目、Prompt/模型身份、题目/Knowledge 引用集合；Provider 只收到有界片段，不收到存储路径或完整画像文档。
- 停止保留已完成提取和逐题结果，继续只处理未完成项；相同摘要幂等复用，显式重试复用稳定 QuestionUnit 并保留旧 AnalysisRun 历史。
- 推断题默认 pending；确认/编辑只重跑该题和聚合 finalizer，拒绝/废弃只重跑聚合。并发决策使用 rerun 标记避免覆盖正在完成的旧工作项。
- 新增分析启动、详情、停止、继续、重试、问题列表、问题决策和渐进报告 API；报告只投影真实持久状态与已完成结果，不在客户端合成缺失项。
- 新鲜证据：Task 5 聚焦 `30 passed`；复盘全域、画像上下文和数据库组合 `54 passed`；岗位域回归 `7 passed`；Ruff、Python compileall 与 `git diff --check` 通过。计划中已不存在的 `test_execution_cancellation.py` 由新增的真实后台停止/继续集成用例覆盖。
- 产品成熟度：渐进分析资源已接入报告优先工作台，用户可边运行边查看完成题目、处理推断题和定位失败题；真实 Provider 内容质量仍待最终阶段验收。
- 下一步：Task 7 确定性候选适配器与 Receipt。

## 2026-08-02：面试复盘 Task 6 报告优先渐进工作台

- 新增持久进度、问题时间线和逐题分析详情；运行中只轮询活动状态，已完成题目立即可看，不生成整场总分。
- 失败题使用错误色并成为默认焦点；无失败时依次选择高风险、首个已完成问题。用户选择写入 `questionId`，渐进刷新不会覆盖有效选择。
- 推断题显示推断依据与确认/拒绝动作；分析详情覆盖证据等级、优点、提升点、遗漏、四类差距、回答结构、参考表达和原文清除提示，空区块不渲染。
- 报告接口补回已落库但遗漏投影的 gap 列表；高级运行详情接收受限 `returnTo`，可返回原复盘和原问题。
- 1440 保持问题栏与详情并排；768 改为上下布局，390 外层记录、问题列表和详情均为单列。浏览器实测无横向溢出。
- 自动证据：前端 75 个测试文件、357 项全通过；Task 6 相关 21 项通过；后端复盘分析/API 14 项通过；TypeScript、production build、Ruff、Ruff format 与差异检查通过。

## 2026-08-01：面试复盘 Slice 1 捕获与整理闭环

- 新增一级入口 `/retrospectives` 与求职目标深链，提供进行中/已归档/回收站生命周期页签、稳定目标筛选、复盘列表和响应式主从工作台。
- 新建流程支持录音转写/事后回忆、粘贴或导入 TXT/Markdown、500,000 字限制，以及不离开当前流程的轻量求职目标创建。
- 整理工作台接通后台进度、停止/继续/失败重试、说话人校正、全局身份对调、段落忽略、版本化保存和确认门禁；版本冲突会提示并重新载入最新结果。
- 新增“当前整理版本”读取端点；离开页面后从一级导航返回，不依赖旧 URL 也能恢复未确认进度。确认后的版本仍由 `activeCleanupVersionId` 读取。
- 自动证据：后端复盘 API `4 passed`，前端最终受影响集合 `42 passed`，Ruff、Python compileall、TypeScript、production build 与 `git diff --check` 通过；仅保留既有大 chunk 提示。
- 浏览器假模型闭环覆盖 1440×900 与 390×844：创建目标、粘贴文字、启动整理、修订未知说话人、保存、确认、刷新恢复均通过；两档 `scrollWidth == clientWidth`，控制台 warning/error 为 0。原生日期控件的自动填充未触发 React `onChange`，已用后端 camelCase API 与前端日期组件测试确认产品字段正常。
- 产品成熟度：Slice 1 可用于文本捕获和整理确认；尚未提取问题、生成逐题分析、候选沉淀或复盘对话。
- 下一步：Task 5 渐进问题提取与逐题分析后端。

## 2026-08-01：面试复盘 Task 3 后台整理闭环

- 新增无 Tool 的 `retrospective_analysis` Cleanup Agent、严格结构化输出、24,000 字窗口与 1,000 字重叠 Reducer；偏移回退、窗口越界和未知字段会被拒绝。
- 新增持久 CleanupVersion/WorkItem 调度：启动立即返回 Execution，停止保留已完成窗口，继续只领取未完成窗口；应用重启会把被中断的运行转换为可继续状态。
- 新增面试复盘 camelCase API、停止/继续控制及幂等重放，覆盖创建、原文版本、整理、人工修订/确认、归档/回收/恢复和删除影响分析。
- Runtime 已注册“面试复盘”运行中心元数据；Trace 写入失败保持 fail-open，不改变整理结果。
- 新鲜聚焦证据：受影响后端组合 `55 passed`，Trace fail-open/停止继续补充测试 `2 passed`；Ruff、Python compileall 与 `git diff --check` 通过。完整前端回归已在迁移基线运行 `339 passed`，本任务未重复运行。
- 产品成熟度：Slice 1 后端已可供页面调用；用户尚无前端入口，真实 Provider、浏览器和窄屏验收留到 Task 4。
- 下一步：Task 4 捕获与整理工作台 UI。

## 2026-08-01：面试复盘迁移到最新产品基线

- 确认本地 `feature/review-agent-workspace` 的 `a4fb776` 才是最新产品基线；旧复盘分支基于过期远程主线，未继续在错误基线上开发。
- 从 `a4fb776` 创建独立 `codex/interview-retrospective-agent-v2` 工作区，迁入复盘 Task 1–2 与清洗契约三笔提交；原 feature 工作区的未提交前端文件和 handoff 文档保持不变。
- 为避开 Evaluation v2 已使用的 runtime 041–044 和 app 009，复盘迁移顺延为 runtime 045、app 010，并同步修正连续升级断言与正式计划引用。
- 新基线验证：复盘/迁移/Repository/Service/Projection/契约定向 `27 passed`，受影响后端组合曾达 `72 passed / 1 stale assertion`，修正后失败项通过；前端完整 `68 files / 339 passed`。
- 下一步继续 Task 3 的真实 Cleanup Agent、后台执行和 API，不再回到旧复盘分支开发。

## 2026-08-01：Evaluation v2 Phase 1–5 阶段收口

- 在开发工作区开启显式本机回归输入记录，用不含个人资料的 Redis 合成问题完成深入讨论与题目整理两条真实 Provider 路径。
- 两条路径均完成 v2 Judge、可运行案例冻结、来源/当前模型配置双沙箱重放和匿名 A/B Judge；正式工作区零写入，基础设施失败为 0。
- 质量实验室已展示 v2 适用性、确定性规则、AI 分级、人工判断、精确实现版本、双沙箱/零正式写入、盲评结论和趋势分组，不再直出 `completed` 等内部状态。
- 最终验证：后端 `1005 passed`；前端 `68 files / 333 passed`；TypeScript、production build 与浏览器验收通过。构建仅保留既有大 chunk 提示。
- 完整回归发现并修正两个旧测试契约：应用迁移清单补到 9，候选资源断言接纳 `sourceAnswer/supplementalAnswer`；产品代码未因测试失败降级。

## 2026-08-01：Evaluation v2 Phase 3 核心迁移

- 新增题目改写、复习轮次/单题/讨论、画像提取/评估/助手/写入边界、岗位要求分析、项目深挖/项目题生成共 11 个 v2 Pack；连同题目整理共 12 个。
- 新增通用 SQLite Outcome Adapter 和 Pack 级最小 Judge View，默认 Observability Registry 已切换到对应 v2 Pack，仍保留显式 v1 历史复检。
- 迁移 043 分开保存原资料答案和 AI 补充，题库详情与整理产物页分别展示来源。
- 任务级 advisory Rule 已覆盖复习推进、画像 Evidence/Tool/写入、JD offset/推断边界、项目 Gap/题库关联；不可证明项返回证据不足。
- 定向验证：后端 84 项持久化/迁移/Adapter/服务用例、规则与服务 29 项；前端 TypeScript、题目详情 6 项及展示语义 4 项通过。

## 2026-08-01：Evaluation v2 Phase 1 Task 2

- 新增不可变 `BusinessOutcomeProjection` 公共契约，hash 只由业务输入摘要、最终领域状态、处理单元、候选、来源类型和用户决定生成，不包含 Trace 正文。
- 首个题目整理适配器可从原始或恢复 Execution 定位批次，投影 work item、seed task、候选状态、确认/拒绝/忽略决定和 Graph/领域版本。
- 对 `mixed` 答案同时标记 direct 与 inferred，并明确记录 `source_supplemental_answer_not_separated`；当前存储无法恢复原文答案与模型补充时不伪造字段。
- 定向回归覆盖投影内容、hash 稳定性、用户确认后 hash 变化、评估契约和题目整理工作单元，共 `46 passed in 3.58s`；compileall 与 `git diff --check` 通过。
- 本任务没有把投影接入 v1 Judge，也没有新增外部模型调用；其他业务域适配器留在各自 Phase 3 Slice。

## 2026-08-01：Evaluation v2 Phase 1 Task 1

- 新增 runtime migration 041，以增量字段保存契约版本、任务类型、运行类型、业务结果 hash、Judge 数据范围，以及维度适用性、等级、严重度和证据缺口。
- v1 创建路径保留默认契约并明确标为 `historical_review`；当前 Judge 的真实数据范围记录为 `legacy_full_snapshot`，没有伪装成最小视图。
- 新增 `JudgeDimensionResultV2`，强制适用维度提供等级/严重度/置信度，不适用或证据不足维度不得携带质量评级。
- 迁移验证覆盖 v1 运行和维度行原值保留；Repository/API/Judge 受影响定向回归共 `54 passed`，Python 测试耗时 3.77 秒。
- 本任务没有改前端、没有迁移现有 v1 评估结果、没有启用阻断规则，也没有运行全量测试。

## 2026-07-31：Evaluation v2 文档边界完成

- 逐项审计 5 类 v1 Eval Pack、21 个维度、确定性检查、Judge 输入与回归 API，并与用户完成 32 项口径确认。
- 新增 ADR，决定以最终业务结果为评估对象，分离 Rule/Judge/人工职责，并明确历史复检不等于真实 Agent 回归。
- 新增 v2 规格，覆盖业务结果投影、适用性、等级/严重度/置信度、最小 Judge 视图，以及题目、复习、画像、JD、项目深挖的任务级维度。
- 新增分阶段迁移计划：v1/v2 共存、确定性不变量、五个业务迁移 Slice、隔离业务重跑和后续趋势/门禁。
- 修订 2026-07-29 规格、ADR 和计划的成熟度表述；README 改为如实说明当前“历史结果复检”和规划中的“真实回归”。
- 新增 README 手绘图 `assets/readme/08-agent-quality-evaluation-boundary-v2.png`；旧图保留，未删除任何历史资产。
- 本轮未修改后端、数据库或前端代码，未迁移或删除 v1 评估数据。

## 2026-08-01：面试复盘需求冻结与 Task 1 完成

- 通过 27 个单项产品决策冻结首版范围：目标归属、文字输入、说话人确认、推断问题、无总分、四类缺口、候选审核、局部重算、渐进运行、报告优先、双入口、移动端和发布边界。
- 新增正式规格、版本/证据/跨领域 ADR 和 10 Task 实施计划；计划按四个可独立验收的纵向 Slice 执行，并由单 Agent 内联完成。
- Task 1 在最新产品基线上使用 runtime migration 045、app migration 010，新增复盘领域 records/errors 和前后端两个模型用途；补齐整理窗口工作项这一计划自审缺口。
- RED 明确验证缺表、缺角色和设置页缺入口；GREEN 后迁移/数据库/Provider 受影响回归 `46 passed`，设置组件 `2 passed`，TypeScript、Python compileall 与 `git diff --check` 通过。
- 下一步：Task 2 实现复盘生命周期、源版本、整理版本与删除不变量。

## 2026-08-01：面试复盘 Task 2 领域生命周期完成

- 新增 Workspace 安全 Repository/Service、源版本幂等导入、500,000 字符和 `.txt/.md` 边界、整理片段确认门禁与正文安全投影。
- 原文清除会删除源正文、整理片段正文、工作项正文和分析来源摘录，同时保留哈希、结构化元数据与下游资产边界。
- 归档、回收、恢复、运行阻断删除、永久删除私有 Session 和删除影响预检已具备确定性领域语义。
- RED/GREEN 覆盖归属、幂等、输入边界、未知说话人、原文清除、活动 Execution、生命周期、投影和删除影响；合并 Job Target 受影响回归 `20 passed`。
- 下一步：Task 3 接入真实 Cleanup Agent、后台 Execution、API 和运行中心 Registry。

## 2026-07-29：Agent 可观测与质量评估实施计划完成

- 根据已确认规格与 ADR，完成一个总索引和四个纵向 Slice 计划，共 1,268 行：
  - Slice 1：Observability Registry、Trace v3 层级、可重建 SQLite 元数据索引、ExecutionSummary、API/SSE、全局运行中心与只读执行详情；
  - Slice 2：本地高级诊断开关、受控 Trace 正文读取、复制反馈与隐私标注导出；
  - Slice 3：版本化 Eval Pack、隔离 Evaluation Runtime、人工/自动 Judge、人工反馈、回归案例与版本比较；
  - Slice 4：90 天默认保留、两阶段清理 Receipt、索引修复脚本、OTel 安全投影和长期质量趋势。
- 计划明确不在 `AgentTraceWriter.append()` 热路径同步写 SQLite，避免可观测能力重新制造数据库锁竞争。
- 自审确认正式计划无未决 TODO/TBD，所有引用文件存在或明确标注为 Create；`git diff --check` 通过。
- 本轮只更新正式文档和本地 current-state 记录，没有修改业务代码、数据库或前端。

## 2026-07-29：Agent 可观测与质量评估设计确认

- 用户确认三张高保真方向：项目级 Agent 运行中心、单次运行高级详情和质量评估实验室。
- 纠正第一版误放在“复习”子功能的信息架构；运行中心提升为独立一级入口并覆盖所有 Agent。
- 新增完整设计规格，定义前后端能力、Trace Ledger、API、Event 契约、上下文追踪、本地高级诊断开关、保留、Eval Pack、质量门禁、三页布局、设计 Token、响应式和验收标准。
- ADR 已从 Proposed 更新为 Accepted，决定本地 JSONL 正文 + SQLite 可重建索引 + 独立 Eval Engine；OTel/Langfuse 只作为可选安全投影。
- 经逐项核查补齐业务/系统 Agent 分层、Observability Registry、控制能力声明、统一 ExecutionSummary、人工 Judge、自动采样、Judge 人工纠错、回归案例隐私、评估隔离和真实纵向交付门禁。
- 三张已确认高保真图已纳入 `docs/superpowers/assets/agent-observability/`，作为实现并排验收基准。
- 本轮未修改业务代码、数据库或前端；下一步根据确认规格编写分 Slice 实施计划。

## 2026-07-24：统一个人画像 Task 1–3 后端检查点

- migration 029 扩展 Claim 类型，新增来源、关系、展示配置和逻辑删除；旧 Claim 数据保持可读。
- Repository 已支持本人直接确认、幂等重放、乐观锁、卡片关系和来源追踪；手动修改与恢复都追加新版本，不改写历史。
- 新增精确 Workspace 安全重置脚本：强制绝对路径、dry-run、确认短语和活动任务检查；共享文件、其他 Workspace、题库和普通 Agent Session 保持不变。
- `unified_profile()` 已把底层 Claim 投影为职业归纳、方向、亮点、经历、项目、技能、教育、认证和成果卡片，并生成可行动缺失项，不计算画像分数。
- 手动新增、编辑、版本恢复和逻辑删除服务已完成；无简历也可形成可用画像，manual confirmed Claim 无 Evidence 仍可进入 confirmed-only 上下文。
- 定向验证：migration/runtime/repository 62 passed；repository/reset 38 passed；projection/service/context 11 passed。未运行全量回归或浏览器。
- 下一产品任务：Task 4 增量简历摄入，只生成新增/修改/可能删除建议，不覆盖本人补充和当前已确认画像。

## 2026-07-24：统一个人画像纠偏设计完成

- 使用 `grill-me` 连续确认 29 个产品决策，覆盖画像定义、正式/草稿边界、手动补充、固定栏目、归纳确认、助手职责、来源可见性、跨简历增量、无简历入口、项目深度、能力推断、来源删除、页面导航、卡片编辑、技能关系、版本历史、模型上下文范围和完整验收标准。
- 新增补充规格 `2026-07-24-r3-unified-personal-profile-correction.md`。
- 新增 ADR `2026-07-24-unified-profile-and-source-model.md`，决定继续复用 Claim/ClaimVersion，增加多来源、类型化关系、统一投影和直接用户写入，不给 Agent 直接写 Tool。
- 新增实施计划 `2026-07-24-r3-unified-personal-profile.md`，拆为 schema、repository/reset、projection/service、增量 ingest、API、画像首页、待确认/来源、画像助手和最终验收 9 个任务。
- Task 1–3 已按上方后端检查点完成；当前 Workspace Profile 数据尚未执行清理，新页面尚未实现。
- 下一产品任务：执行 Task 4 增量摄入，再接 Task 5 API。

## 2026-07-23：R3 Task 15 - Profile Agent 工作区实现

- `/profile` 的“Agent 会话”已开放：紧凑会话栏、对话时间线、当前 Material/Version 焦点、运行状态、上下文压缩状态、持久 Composer 和停止控制已接入统一 Runtime/SSE。
- Assessment 与 Action Plan 使用资源卡片按 ID 读取最新状态；Plan 展示有序 before/after、Evidence 数量、stale 警告、确认/取消/失败项重试与 Receipt 状态，不把未确认方案表达成已修改事实。
- Tool 生命周期只显示“正在读取已确认画像/已读取证据”等安全阶段，不渲染参数、返回 JSON 或私有正文。运行结束后焦点回到 Composer；移动端变为横向会话条 + 单列对话/状态，无页面级固定宽度。
- `ui-ux-pro-max` 的高密度、44px target、加载反馈、可见焦点和响应式规则用于实现；其紫粉 AI 配色、手写字体和 Landing 模式与已确认 R3 视觉契约冲突，继续使用现有浅色语义 Token。
- 定向前端 `5 passed`，`npx tsc --noEmit` 与 `git diff --check` 通过。项目没有 `npm run typecheck` script，因此使用等价 TypeScript 命令；未跑全量前端、build 或浏览器。
- 产品成熟度：Task 15 代码和自动门禁已完成，桌面/390px 实页、键盘焦点和真实 Provider 流式/停止仍待下一步验收，暂不宣称 Task 15 正式关闭。

## 2026-07-23：R3 Task 14 - Profile Manage 与 Action Plan API

- 新增 Profile 专用会话创建/列表入口，只能创建 `profile.manage`；通用入口拒绝用户伪造 `profile.ingest/profile.assess` system Session。消息执行、取消和 SSE 继续复用统一 Agent Runtime。
- 新增 Assessment 详情和 Action Plan 详情/确认/取消/重试 API。计划资源返回 base/current profile version、stale/capability、完整 before/after diff、Evidence ID、逐项状态、Receipt 和 error code。
- Action Plan 在确认前重验当前 Profile snapshot，过期统一返回 409；跨 Workspace 的 Assessment/Plan 返回 404。无效计划返回 422，不暴露数据库或模型原文。
- 新增应用重启恢复验收：计划创建后关闭应用，重开后通过 API 确认，再次重开仍读取同一 completed item Receipt。
- 聚焦 API 测试 `5 passed`；合并通用 Agent route、manage Graph、Action Plan 与 migration 回归共 `61 passed`；compileall 与 `git diff --check` 通过，未运行全量回归或浏览器。
- 产品成熟度：后端已经可供页面完整调用；下一产品任务 Task 15 实现画像 Agent 工作区，完成后用户即可在页面测试连续问答、评估、停止和方案确认。

## 2026-07-23：R3 Task 13 - `profile.manage` 与有界 Chat Tool loop

- 新增显式 `profile.manage` Graph：服务端确定性区分问答、评估、单项修改、多项计划与澄清；Assessment 复用独立子图，Planner 只输出结构化计划且没有写工具。
- 新增 `profile_agent_context`，只保存 Material/Version/Claim/Proposal 稳定 ID；每轮从领域仓储重新装配 confirmed snapshot，不把旧聊天或 ToolMessage 当作画像事实。连续对话仍由 `<session>:profile_chat` checkpoint 和既有 compaction 管理。
- Runtime 先授予服务端 Profile Tool 上限，再按本轮问答意图取交集；Chat 仍受 6 次总调用、相同调用 2 次、50 项/2,000 字符结果上限约束。Assessment/Planner 的 Tool allowlist 为空。
- Action Plan 以 execution ID 幂等：恢复或重放同一 Execution 返回同一 Plan，异输入稳定冲突；外层 session checkpoint 每轮清除旧终态字段，避免上一轮卡片泄漏。取消会向下传播且不留下计划半成品。
- 产品 Message 只投影完成后的文本、Assessment Card 和 Action Plan Card；Tool 原始参数/结果与模型结构化原文不进入产品消息。定向验证覆盖路由、上下文、线程、工具、预算、取消、多项计划和重放恢复，最终 `82 passed`；compileall 与 `git diff --check` 通过。
- 产品成熟度：R3.3 后端会话 Graph 已具备，但用户还不能通过页面发起/确认方案；下一产品任务是 Task 14 API，随后 Task 15 才进入 Agent 工作区页面测试。

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

## 2026-07-22：R3 Task 8 - 材料、版本与 Evidence API

- 新增 9 个 R3.1 API：材料上传/列表、版本追加/列表/详情/重试、归档/恢复/主版本；上传与重试返回 `202 Accepted`，后台继续复用隐藏 `profile.ingest` Execution。
- 资源使用 camelCase，包含处理阶段、Evidence offset/limit 分页、locator/2,000 字符内 excerpt、Proposal 计数、retry capability 和安全 Execution 摘要；未暴露私有存储引用、完整文本或 system Session ID。
- 所有非 Workspace 路径重新校验 `workspaceId`；写操作接入 Profile receipt，材料生命周期操作增加 aggregate version 检查，错误统一为中文 `code/message/retryable` envelope。
- RED 为新 API 文件 `5 failed`（端点均不存在）；GREEN 后 Task 8 `5 passed`。受影响旧 material service 与 restore invariant 合并验证后最终 `16 passed`；Python compileall、OpenAPI 9 端点扫描和 `git diff --check` 通过。未运行全量回归、前端或浏览器。
- 下一产品任务：Task 9 实现材料版本与 Evidence 页面，完成后用户可以开始 R3.1 第一批页面功能测试。

## 2026-07-22：R3 Task 9 - 材料版本与 Evidence 页面

- 新增 `/profile` 一级入口、资料总览、简历版本、确定性处理阶段、失败重试、归档/恢复/主版本、Evidence 定位和 390px 单列布局；`/review` 继续是默认路由。
- 新增 multipart `apiUpload` 与 Profile 类型/API 客户端；上传支持 picker/drag-drop、PDF/DOCX/Markdown/TXT 和 10 MB 前端校验，所有写请求携带幂等键。
- 有效 RED 为 4 个目标文件缺失与 `apiUpload is not a function`；GREEN 后 4 个聚焦文件 `13 passed`，TypeScript、Python compileall、`git diff --check` 通过。只额外重跑受影响的 ResumeVersions 单文件，未跑全量回归或 build。
- 隔离临时工作区浏览器验收发现并修复“模型未配置时 Execution 失败但 Material 仍处理中”的无限轮询缺口；重试后材料落 retryable terminal status，页面显示保留与恢复说明。
- 390/768/1024/1440 均 `scrollWidth === clientWidth`，桌面/移动截图已保存到本地 verification assets；console 0 warning/error，`design-qa.md` 最终为 passed。
- 产品成熟度：R3.1 的上传、版本、Evidence 与失败恢复现在可在页面测试；成功 Claim 数据仍依赖配置 `profile_extraction` 模型，Claim 审核从 Task 10 开始。
- 下一产品任务：Task 10 Claim Proposal 审核与删除影响分析。

## 2026-07-22：R3 Task 10 - Claim Proposal 审核与删除影响分析

- 新增 Claim 列表/详情/版本、Proposal 接受（含编辑后接受）/拒绝、批量决定 API；响应保留 Evidence 定位与逐项冲突回执，写操作支持 expected version 和幂等回放。
- 新增 15 分钟持久删除预检与安全永久删除：逐 Claim 选择删除或保留为 unsupported，已进入发布选择的 Claim 禁止直接删除；活动知识要求显式撤销，未接入 Task 16 revoker 时安全失败。
- 删除事务会重新校验材料、Evidence、ClaimVersion、待决 Proposal、选择和活动发布快照；并发接受使旧计划返回 409，已接受 Claim 不会引用被清空的 Evidence。
- 删除后保留无敏感正文 tombstone，artifact 按引用计数最后清理；部分失败保存 item receipt，重试不会重复领域写入。
- 新鲜 Task 10 定向 `11 passed`；受影响 Profile 仓储/材料/API/迁移回归 `59 passed`；Python compileall 与 `git diff --check` 通过。未运行无必要的全量回归。
- 产品成熟度：Claim 审核与删除安全后端已完成，但尚不能从页面操作；Task 16 接入正式 Knowledge revoke 后才形成活动发布材料的完整删除闭环。
- 下一产品任务：Task 11 Claim 审核前端。

## 2026-07-22：R3 Task 11 - Claim 审核工作台

- `/profile` 的“画像与经历”已开放：支持状态/分类筛选、Proposal 队列、冲突文字标识、当前值与建议值并列对比、理由和 Evidence 跳转、单项接受/拒绝及逐项选择的批量接受/拒绝。
- 批量提交前选择持续可见；部分冲突回执只清除成功项，保留冲突项并刷新快照。Evidence 详情按自身 MaterialVersion 加载，不误用当前简历版本。
- 永久删除对话框先读取后端 deletion plan，展示 Evidence/Claim/unsupported/publication 数量，逐 Claim 选择处理方式；归档与永久删除文案分离，要求输入“永久删除”，活动发布额外要求撤销确认。
- 自动验证：ClaimReview、DeletionImpactDialog、ProfilePage 三个目标文件 `7 passed`；`tsc --noEmit` 与 `git diff --check` 通过。
- 浏览器验收：1280px 与 390px `scrollWidth === clientWidth`，console 0 warning/error；Escape 关闭删除框后焦点返回“永久删除材料”。只执行删除预检，没有提交永久删除；本轮服务已停止。
- 产品成熟度：R3.2 Claim 审核页面闭环已完成；真实 Claim 建议仍依赖成功配置并运行 `profile_extraction` 模型，活动知识关联删除仍等待 Task 16 revoke adapter。
- 下一产品任务：Task 12 Assessment、受约束 Action Plan 与 Receipt。

## 2026-07-22：R3 Task 12 - Assessment、受约束 Action Plan 与 Receipt

- `ProfileService` 新增 confirmed snapshot Assessment 门禁和 Evidence 引用校验；相同 Execution 的相同结果幂等返回，Assessment 不写 confirmed Claim。
- Action Plan 创建时限制六个操作并整体校验 immutable ordered item、before/after、expected version、Evidence 和 Workspace；确认、取消、局部失败、重试与最终聚合状态均使用乐观锁。
- 固定 dispatch 只调用 Claim Proposal、derived material version、publication selection 和 reassessment request 的领域路径；没有 generic tool/method dispatch、任意代码、自由路径或直接 Knowledge publish。
- 派生简历失败恢复使用稳定 item creator，重试复用已创建版本并只补文本/状态/主版本步骤；completed item 不重复执行，Receipt 不变化。
- 安全 Event 只投影 ID、operation、ordinal、status/count。目标 Assessment/Action Plan `7 passed`；合并 Profile Repository 回归 `38 passed`；compileall 与 `git diff --check` 通过，未跑全量回归。
- 产品成熟度：R3.3 的领域计划与执行状态机已具备；模型如何生成计划、连续对话和 HITL API/UI 仍由 Task 13-15 接入。
- 下一产品任务：Task 13 `profile.manage` 与有界 Chat Tool loop。

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
- Task 7 评审补齐人工审核终态：发布投影、正式拒绝和自由命令拒绝都在候选写事务内调用同一个 Repository 聚合器；仅当 Batch 至少有一个候选且全部为 `published/rejected` 时，原子推进 `review_pending -> completed` 并同步活动整理会话为 `completed`。
- 新增最后发布、最后拒绝、尚有 pending、正式拒绝、并发最后两项和幂等回归；RED 为 `4 failed`，GREEN 为 `4 passed`，受影响套件 `94 passed`，最终后端 `633 passed`（1 条既有 warning）。记录时间：2026-07-22 07:44 CST（UTC+08:00）。
- 第二轮评审修复修订 Batch 边界：新增 migration 025 的 `(batch_id, candidate_id, draft_id)` finalization 关联，保留候选原始 `batch_id` 与逻辑题血缘；发布/拒绝按当前 draft revision 聚合 rewrite Batch，origin 不被新修订决策误完成，活动 `question.revise` Session 同事务完成。
- 修订发布/重启后拒绝 RED 为 `2 failed`（origin 被误完成）；旧库 committed revision 恢复 RED 为 `1 failed`（新 draft 被误回填至 origin）。GREEN 后 Repository+Migration `60 passed`、受影响 `168 passed`、完整后端 `637 passed`（1 条既有 warning）。记录时间：2026-07-22 07:59 CST（UTC+08:00）。
- 第三轮评审收紧 migration 025 推断：Session 永久删除会把 Draft/Batch run_id 同时置 NULL 并级联删除 finalization claim，`NULL IS NULL` 不能证明归属。新增 v24→永久删除→v25 RED（错误产生 1 条 origin membership），改为双方 run_id 非空且 `=` 后 GREEN；Repository+Migration `61 passed`、受影响 `169 passed`、完整后端 `638 passed`（1 条既有 warning）。记录时间：2026-07-22 08:09 CST（UTC+08:00）。
- 浏览器验收使用隔离数据完成桌面与 390px：实时耗时递增、处理中预览、暂停冻结、刷新恢复、新 Execution/同 Batch、终止确认、终态无恢复、resume 409、Trace UTC/北京时间和 console 0 均有证据。无模型绑定的恢复 Execution 按预期失败；未调用真实 Provider。
- 浏览器发现会话列表直接显示 `paused` 且将 terminated 计入待处理；新增组件 RED 后补齐四种中文控制状态并修正终止态统计。相关前端 `37 passed`，最终前端全量 `167 passed`，TypeScript 与 build 通过。
- 产品成熟度：单进程 bounded scheduler，不是分布式 jobs；真实 Provider 性能和真实材料完整运行仍待具体授权。下一产品任务回到 R3 Task 8；非阻塞练习见本地 verification 指南。
- 最终整片审查发现并修复两个边界：零候选不再永久卡在 `review_pending`，而是把 Batch/Session 原子收口为 `completed`，跳过合并/总结中阶段并明确提示“无需确认”；legacy `/question-batches` 没有 Curation Session 投影时不再写 warning，避免 Execution `failed` 与已提交 Batch 终态分裂。可恢复 `failed` 会话同时纳入前端“待处理会话”。新增 RED 均稳定复现，修复后后端完整 `641 passed`、前端完整 `167 passed`，TypeScript、build 与 `git diff --check` 通过；整片复审 Approved。
- 用户真实整理第一次恢复的 Execution `d0bdb1a1-003c-4711-92f6-042afddf94ff` 因 GLM 第 20 个 seed 缺少 `source_ref` 且含 null 引用失败；第二次恢复的 Execution `3bad1a8e-32c5-4ff5-91c9-8f858fb7cb7f` 又分别遇到 21 个 seeds 和主引用顺序错误。数据库保留原 Batch `907129b5-0a8c-47cb-b8a0-be42b73459a9` 的 75 个 deterministic、3 个 model completed Work Item，仅 unit 0、79 待重跑，即 78/80 discovery 单元已保存。
- 以有效 RED 覆盖严格领域模型拒绝、Provider 超量、null/重复/顺序偏差和无证据行后，改为宽松 `ProviderQuestionSeedChunk` → 确定性 normalizer → 严格 `QuestionSeedChunk`；未知引用、跨来源引用仍硬失败。受影响的 Agent/Graph/Planner/Scheduler/Work Item/Trace 套件 `115 passed`，compileall 与 `git diff --check` 通过；未由 Codex 自动再次调用真实 Provider。
- 第三次真实恢复 Execution `2f240749-d407-4f20-89fc-c2415101dd37` 已完成全部 5 个 model discovery 和 22/42 个 enrichment Work Item，随后同一并发波次出现两个失败：一个 GLM 候选缺少 `title/topics`，另一个候选把种子的两个合法引用缩成一个。Batch 保留 75 个 deterministic、5 个 model discovery 和 22 个 enrichment completed，仅 2 个 enrichment failed、18 个 pending。
- 根因是 Provider/领域契约分离只落在 discovery，enrichment 仍直接使用严格 `QuestionCandidateChunk`。TDD RED 为 `3 failed`，补充引用顺序 RED 为 `1 failed`；现扩展为宽松 `ProviderQuestionCandidateChunk` → 基于 seed 的证据归一化 → 严格领域 Chunk，缺失 title/topics 使用确定性展示回退，未知/跨种子证据仍硬失败。受影响套件 `119 passed`；本次真实 Trace 中原先少一个引用的响应离线归一化后恢复 3 个候选和 `[1,2,4]` 引用长度，未调用 Provider。

## 2026-07-22：随手记容错整理 Tasks 1–8 完成

- 后端完成 migration 026、Seed Task/手工重试状态机、来源分类、Provider observation normalizer、旧 Work Item reconciliation、每次最多 3 Seed/最多 3 并发/单 Seed 最多 2 次自动调用、局部失败 reducer、质量资源、安全事件与统一发布门禁。
- 前端完成五类 Seed 进度、来源警告、质量筛选、候选 provenance/support、单题重试和 AI 补充确认；黄色人工复核与红色执行失败语义分离，390px 无横向溢出。
- 综合跨层验收 `1 passed`；前端完整 `172 passed` 与 build 通过。后端首次完整为 `683 passed, 1 failed`，修正旧 PDF 低信号测试夹具后受影响 `7 passed`，未做无必要的第二次完整回归。
- 隔离真实数据库快照保留 80 completed discovery、22 completed enrichment，并恢复 66 个唯一 degraded Seed；两次 reconciliation 幂等、终态不可自动 claim、外键检查为 0、Provider 调用为 0。
- 浏览器完成真实失败会话桌面/390px 语义与布局验收；未在用户材料上执行 Provider 重放。服务已停止。
- 产品下一步回到 R3 Task 8；真实 Provider 下暂停/恢复/单题重试/mixed 发布作为非阻塞用户练习。

## 2026-07-22：真实批量发布 SQLite 锁修复

- 根因定位到 durable publication 完成后的候选投影回写：瞬时 SQLite writer contention 使 HITL delivery failed，随后 Operation 失败收口也被同一锁打断，造成 running item 悬挂。
- 增加仅针对 SQLite locked/busy 的同回执有界重试，并补 retryable 终态 running item 的 reconcile；不重复文件发布，不重跑已完成条目。
- 两个新增故障/恢复场景与既有批量取消重试场景共 `3 passed`。真实 Operation 已从 35 completed/1 running/89 pending 恢复并续跑到 125 completed，125 个候选均为 published。
- 后端开发服务已重启并加载修复。下一产品任务仍为 R3 Task 8。

## 2026-07-22：题库二级导航比例修正

- 根因是 `catalog-workbench` 被外层 Grid 拉满剩余视口后，内部 auto rows 默认平分多余高度，导致工具栏和“整理会话/题目库”导航被纵向拉伸。
- 工作台改为内容起始对齐；二级导航保持 54px 外框、44px 点击区，两项桌面端各 112px，390px 下各 176px 均分整行，并补 focus-visible。
- 实页计算尺寸与桌面/390px 视觉检查通过；QuestionCatalog 定向语义测试 `1 passed`，`git diff --check` 通过。下一产品任务仍为 R3 Task 8。

## 2026-07-23：R3 历史材料“等待文本提取”卡死修复

- 实际 Execution 已于 2026-07-22 16:48:34 CST 失败，Trace 明确为 `profile ingest identifiers are required`；材料版本仍为 `uploaded`，导致前端轮询永不结束。
- 根因是 Service 传 camelCase、LangGraph `ProfileIngestState` 仅声明 snake_case，未声明字段在首节点前被过滤。
- 摄入/重试输入已统一为 snake_case；失败状态按阶段收敛；修复前的历史失败记录由 API 投影为可重试失败态。
- 用户首次真实重试成功创建 snake_case Execution，但 `profile.ingest.parsing` 被共享 ProductEventStream allowlist 拒绝；补齐 ingest 三事件后，测试改为完整 Graph 经过真实事件流落库。
- 定向 API + Graph + 既有 Event Stream `15 passed`，`git diff --check` 通过；开发服务已热更新。失败的真实重试已安全收口为 `parse_failed`，下一步由用户在原版本再次点击重试。

## 2026-07-23：R3 画像会话 ToolRuntime 注入修复

- 用户真实问答中材料检索阶段进入 Tool loop，但 `get_profile_claims` 抛出 `missing 1 required positional argument: runtime`，导致并行画像/知识查询失败和 Execution 终止。
- 8 个画像只读 Tool 的显式 Pydantic args schema 未包含注入型 `ToolRuntime`；业务单元测试绕过 ToolNode，未覆盖生产注入路径。
- 严格输入基类现声明服务端注入 runtime；模型可见参数仍只有 query/evidence/claim/version 等业务字段。新增真实 ToolNode 测试，一次执行全部 8 个 Tool 并验证上下文注入。
- 后端画像 Tool/预算/chat/manage `37 passed`；前端 Tool 状态/工作区 `3 passed`，TypeScript 与 `git diff --check` 通过。失败文案改为“无法……，请重试”。

## 2026-07-23：R3 画像会话并发 Tool SQLite 写竞争修复

- 真实 Execution 一次并发发起 5 个只读 Tool；每个 Tool 的审计起止和产品状态事件仍需写同一 Runtime SQLite，产生 writer contention。事件写失败后，Execution 失败收口又撞到未释放的并发写锁，导致运行记录残留为 `running`。
- 同一 Execution 的画像 Tool 生命周期现按序执行；模型仍可一次提出多个 Tool，但审计、查询和事件写入不会并发争抢 SQLite。产品事件写入遇到短暂 locked/busy 时会先回滚，再进行有限重试。
- 新增并发 5 Tool 串行化和产品事件瞬时锁恢复测试；目标套件 `10 passed`，`git diff --check` 通过。旧残留 Execution 会在后端完成热重载后的启动恢复中转为 `interrupted`。

## 2026-07-23：R3 画像会话终态与停止按钮收口

- 真实 Execution `53441ea6-006d-48f0-aafc-76c657c98d9c` 已由后端恢复为 `interrupted`，停止接口也持续返回 200；页面仍转圈的根因是旧 SSE `running` 状态覆盖了最新持久化终态。
- 画像工作区现以持久化的 `interrupted/completed/failed/cancelled` 为最终事实；停止请求期间按钮防重复点击，完成后恢复输入。Tool 状态只展示当前 Execution，并按 `toolCallId` 合并；缺少结束事件的旧 Tool 在 Execution 终止后显示“已停止…”，不再无限旋转。
- 定向前端 `5 passed`，TypeScript 与 `git diff --check` 通过。

## 2026-07-23：R3 Profile API 假 404 修复

- 确认目标 MaterialVersion 数据存在；404 是共享 SQLite connection 被多个 FastAPI worker thread 并发使用后产生的错误读，不是业务层 Not Found。
- Workspace Runtime 改为线程本地连接代理：Repository/Service 无需重写，每个 worker thread 独占连接，Runtime 关闭时统一回收。
- 新增连接所有权回归，定向 Profile API/Tool/时间线共 `49 passed`；Python compileall 与 `git diff --check` 通过。
- 卡住热重载的旧 SSE worker 已精确重启；新 worker 健康检查 200，目标 MaterialVersion 接口 10 并发、累计 40 次请求均为 200。
- 当前 R3 产品任务仍为 Task 15 真实页面验收。

## 2026-07-23：Claim 证据原文入口修正

- “点击查看原文位置”原为不可点击提示，真正可点击的证据行缺少动作文案，造成明显的伪入口。
- 每条证据现提供明确的“查看原文位置”动作和完整可访问名称；Markdown/TXT 定位转为“第 11–13 行”等中文格式，不再直接展示 `lineStart/lineEnd`。
- 证据详情页同步显示页码、段落或行号定位；ClaimReview、ProfilePage、ResumeVersions 定向 `6 passed`，TypeScript 与 `git diff --check` 通过。

## 2026-07-23：简历永久删除入口归位

- 永久删除原本只出现在“画像与经历”，用户在“简历版本”只能归档，难以发现整份测试材料的清理入口。
- “永久删除材料”现移到简历版本的独立危险操作区，与可恢复归档分开；仍先执行 Evidence/Claim/Publication 影响预检和文本确认。
- 画像审核页不再承担材料生命周期操作。ResumeVersions、ClaimReview、ProfilePage、DeletionImpactDialog 定向 `8 passed`，TypeScript 与 `git diff --check` 通过。

## 2026-07-23：画像 Agent 历史会话清理

- 画像 Agent 会话列表原本只能新建和切换，删除测试简历后仍保留上一份简历的独立对话上下文。
- 会话行新增明确的永久删除入口，复用通用 Agent Session 删除能力；删除当前会话后清空对应查询缓存并进入下一会话或空状态。
- 删除范围只包含该会话、Execution、事件和历史消息，不删除简历材料、画像项或已确认数据；运行中的当前会话必须先停止。
- ProfileAgentWorkspace 定向 `3 passed`，TypeScript 与 `git diff --check` 通过。

## 2026-07-23：画像建议分类与处理过程可解释性

- 用户侧“Claim 提取”改为“生成画像建议”，处理中展示已准备的 Evidence 数量、五类识别范围、证据核对与保存步骤，并明确只生成待确认建议、失败后保留文本和证据。
- `profile-extraction` Prompt 1.1 明确定义技能、项目、工作、教育、链接五类边界、分类固定字段、多标签 Evidence 和去重规则；提取契约同步提供字段语义。
- 持久化前增加确定性字段别名归一化和完全重复候选合并，不做模糊语义合并；超过 50 条 Evidence 时页面明确说明当前覆盖边界，分批恢复另行实施。
- 后端 Profile Agent/Ingest/Material API 定向 `18 passed`；前端 ResumeVersions/ProfilePage/ClaimReview 定向 `7 passed`，TypeScript、compileall 与 `git diff --check` 通过。
## 2026-07-23：R3 个人资料界面用户化改造

- 用户实页反馈确认，原页面把 Material、Evidence、Claim、画像和 Agent Runtime 等内部领域模型直接作为主界面语言，用户难以理解页面用途。
- 四个入口调整为“概览、简历与版本、确认简历要点、简历助手”；一级导航同步改为“我的简历”。
- 概览改为当前简历、下一步、用途和隐私边界；过滤 Markdown frontmatter、联系方式脱敏占位和无意义标题，不再把原始元数据铺在首屏。
- 简历版本处理过程在完成后默认折叠；文件类型、原文位置、失败恢复和删除影响使用用户语言，去除 MIME、字符 offset 和 Markdown 标记。
- 新建简历要点使用自然语言卡片，不再展示空白“修改前”列；Schema 字段映射为中文，分类同时读取新建议类型，来源统一表述为“来自简历”。
- 简历助手以任务提示开始，对话记录替代整理会话；Tool 阶段翻译为用户动作，Runtime 信息收进默认折叠的“运行详情”。
- 验证：相关 7 个前端测试文件 15 项通过，`tsc --noEmit` 与 `git diff --check` 通过；5174 真实页面完成 1280px 四入口复核，无横向溢出，未触发模型调用或数据写入。

## 2026-07-24：R3 画像对话 Tool 超限修复

- 真实 Execution 一次提出 8 个单条 Evidence 读取，画像预算为 6；官方 ToolCallLimit 的 `error` 策略在 Tool 执行前直接终止了整轮。
- 新增一次最多 12 条的批量 Evidence 读取 Tool；Prompt 要求多条证据使用批量调用。画像专用超限策略改为阻止额外调用并继续回答，其他 Agent 的硬失败策略不变。
- 仍保留每轮 6 次调用、重复调用和结果体积边界；批量读取支持部分缺失，不因单条失效丢弃已有证据。
- 定向回归 `41 passed`，关联 Agent/Policy `12 passed`，compileall 与 `git diff --check` 通过。8000 后端已精确重启并健康检查 200；未自动重放真实模型请求。

## 2026-07-24：R3-R6 产品路线调整

- 通过产品追问确认个人资料功能的最终角色：它是岗位分析与训练的可信数据底座，不是独立的“画像管理”终点，也不应以知识发布作为核心用户任务。
- 新增 Accepted ADR `2026-07-24-job-target-centered-interview-preparation.md`，固定求职目标聚合根、逐条岗位要求、项目深挖、项目讲解卡、四类缺口、资料补充确认边界和岗位准备事实。
- 更新总路线：R3 收窄为可信资料与 `ConfirmedProfileContext`；R4 改为求职目标与项目深挖；R5 按四类缺口组织练习；R6 在求职目标上下文中执行模拟面试。
- 更新 R3 规格与实施计划：取消当前里程碑的知识发布范围页面、选择/发布/撤销任务，Task 16 改为受控下游查询，Task 17 改为现有四页面跨层验收，Task 18 改为 13 个最终场景与文档门禁。
- 本次只调整产品与架构文档，未修改或验证运行代码；R3 产品状态仍是 Task 15 实现完成待实页验收、Task 16-18 待执行。

## 2026-07-24：R3 产品边界与受控查询落地

- 简历助手已收窄为资料维护：Prompt、空状态、快捷问题和评估卡聚焦资料完整性、一致性、原文定位与表达整理，不再承担岗位差距、项目深挖或模拟面试。
- 当前 Agent 不再注册知识检索、发布状态 Tool，也不能生成新的 `set_publication_selection` Action Plan；旧 schema、Repository 和历史计划展示保持兼容，未执行破坏性迁移。
- 概览移除“发布功能即将开放”，改为说明创建求职目标后按岗位与资料范围使用；永久删除不再展示活动发布/发布选择术语，真实旧依赖存在时使用通俗阻断提示。
- 新增 `POST /api/workspaces/{workspaceId}/profile/confirmed-context`：用途白名单、分类/Claim ID 过滤、Workspace 校验、当前 confirmed 版本、敏感字段/Evidence 排除、50 项上限和稳定空结果均已接通。
- 定向后端 Profile Context/Agent/API/Tool/Action Plan/Middleware `54 passed`；定向前端 Profile 工作区、版本、方案、Tool、删除和页面 `14 passed`，TypeScript 与 Python compileall 通过。Task 16 完成，Task 15/17 的真实页面和跨层验收仍待执行。

## 2026-07-24：R3 核心跨层验收完成

- 产品状态：四页面核心路径已真实跑通；Action Plan 运行中隐藏结构化模型原始分析，合法方案可确认并产生 Receipt，无效方案安全拒绝。
- 浏览器证据：合成 MaterialVersion `213e11308564424fa8189ce8d2116722` 完成 11 个原文片段和 9 条候选；问答 Execution `55f7af46-2c8c-4a3d-badc-396f56cba4a6`、计划 Execution `31de9b82-daf0-4189-8bb8-35b854d0debc` 完成；计划单项 Receipt `b8e6e716eeb84db7a2823e36c814ac5b`。
- 文档状态：验证指南已重塑为最终用户指南，`integration` 风险档案的七文件学习包已生成。
- 成熟度边界：核心 happy path、真实 Provider 问答/计划、停止恢复、confirmed-profile 隔离和 390 px 已覆盖；DOCX、新版本、冲突、Assessment、局部重试等扩展组合场景尚未完成最终浏览器复跑。
- 所有权状态：产品自动与核心人工证据已具备；用户练习为 pending practice，不阻塞提交；阶段关闭仍受最终回归与完整浏览器清单约束。
- 下一产品任务：先完成最终回归和文档门禁，再补齐扩展浏览器清单；之后进入 R4 求职目标与项目深挖。
- 非阻塞练习：Trace 一次上传到 confirmed-profile，再口述为什么 Planner 没有写 Tool。
- 最终自动门禁：后端 `744 passed`；前端 `198 passed`；TypeScript 与 production build 通过；`git diff --check` 与阶段文档门禁通过。现仅保留验证指南列明的扩展浏览器组合场景，不再重复完整回归。
## 2026-07-24：R3 统一个人画像纠偏完成

- 完成 Task 1–9：多来源/关系/展示 schema、统一画像投影、手动卡片、简历增量合并、画像 API、四入口页面、confirmed-only 助手和对话待确认建议。
- 完整回归：后端 766 passed；前端 43 个文件、202 passed；TypeScript 与 production build 通过。
- 浏览器复核：桌面、390、768、1024 无页面级横向溢出；空状态、手动新增、立即展示、具体缺口、删除恢复为空均通过。
- 数据清理：目标 Workspace `c896b511-670d-4d44-9ed0-78d5cffccdeb` 的旧 Profile 测试数据已清除；题库整理数据、Workspace 设置和模型绑定保留。
- 文档：统一画像规格、ADR、实施计划、验证指南和七份 R3 学习资料已同步。
- 产品状态：R3 统一个人画像基线完成；下一任务为 R4 求职目标、岗位要求确认与画像映射。

## 2026-07-24：简历工作台可用性补强完成

- 新增共享有界工作台，重排“简历与来源”和“待确认”，桌面由内部区域承担滚动，移动端保持自然文档流。
- 简历处理增加真实阶段、耗时、停止/继续和跨页常驻状态；待确认增加选择、批量决策与安全一键确认。
- 新增 Workspace 隔离的完整简历阅读/下载接口与阅读器，支持原文、脱敏版、目录定位和来源跳转。
- 定向验证：相关前端 13 项、TypeScript、后端文档 API 与真实页面四档宽度通过；未执行真实建议确认或其他画像数据写入。
- 当前成熟度边界：阅读器基于抽取正文，不提供 PDF 原生分页或视觉版式还原。

## 2026-07-24：画像助手会话工作台统一

- 新增 Accepted Agent 会话工作台准则与实施计划，固定会话记录→选中会话两级结构、中央消息区+右侧依据栏、状态所有权、归档回收站、标题中间件和响应式门禁。
- 通用 Runtime 新增 Workspace 隔离的会话重命名、用户标题所有权、deleted-only 列表和最近消息摘要；画像新会话不再强行写死标题。
- 画像助手迁移到共享 Shell、Markdown 消息、过程卡和带模型/思考强度的输入区；快捷问题只填入，右侧栏按参考范围、隐私边界、待处理结果、运行状态和技术详情排列。
- 会话记录支持标题/最近消息搜索、运行/需要处理筛选、归档、回收站恢复和永久删除；运行会话保留后端归档保护。
- 定向验证：后端 4 个关键 API 场景、前端 4 个关键交互、TypeScript、Python compileall 与 `git diff --check` 通过。
- 浏览器验收边界：当前用户启动的 8000 进程端口可连接但所有健康/API 请求均超时，5174 因此停在“正在连接本地服务”；未停止用户进程，也未调用模型或修改画像数据。服务恢复后仍需补 390/768/1024/1200/1440 五档实页测量。

## 2026-07-24：画像页面高度与会话摘要修正

- 用户授权后精确终止无响应的 8000 进程并重启后端；`/api/health`、画像、材料版本和画像会话接口恢复 200。
- 1280×720 实测“我的画像”原本把 document 撑到约 2589px；修正后 Shell 与 document 均为 720px，2448px 内容由 `.profile-page-content` 单一内部滚动区承担。
- 核对实际会话 API 后确认标题字段为“简历助手对话”，超长内容来自 `lastMessagePreview`。会话卡现在先清理 Markdown/空白并截为 88 字，再以两行摘要展示；卡片实测稳定为 104px。
- 选中会话标题增加独立收缩容器，长标题显示省略号且保留完整 title 提示。定向 Profile 页面/Agent 测试 8 项、TypeScript 与 `git diff --check` 通过；未调用模型或修改画像数据。

## 2026-07-25：画像概览与画像助手列表收敛

- “我的画像”改为职业名片、分类导航、画像概览和代表经历的摘要优先结构；工作、项目、教育、证书与成果按需切换，默认内容高度从约 2448px 收敛到 1126px。
- 画像助手会话页修复条件任务条造成的 Grid 空行：1200×702 下主内容和列表均占满剩余 560.7px，会话卡以 896px 单列展示，新建按钮文字恢复白色。
- 会话摘要只取第一段有效自然语言，真实卡片从 Markdown 长回复收敛为“已对简历全文进行了逐段核查，以下是完整性检查结果：”；右栏零建议改为中性“暂无待确认建议”。
- 真实页面无水平或整页滚动，document 保持 1200×702；画像分类切换只渲染目标区域。定向 Profile 页面/Agent 测试 8 项、TypeScript 与 `git diff --check` 通过；未触发模型调用和资料写入。
- 经 `grill-me` 逐项确认后，画像主页取消永久右栏：求职方向、核心技能和待完善仅出现在概览首行，工作、项目、教育和成果内容使用全部 896px 主内容宽度。
- 职业名片从大面积渐变卡收敛为约 117px 的中性信息条；空状态显示“尚未设置职业定位”，并提供独立的“设置职业定位”和“补充其他资料”动作。
- 子页签在唯一内容滚动区内吸顶，实测滚动 505px 后仍与一级页签底边对齐；默认内容高度进一步从 1153px 收敛到 1066px。
- 项目编辑器从 720×670px、操作栏需滚动后可见，改为 900×562px、固定头尾和中间表单滚动；390×844 下为全屏单列，document scrollWidth 等于 390px。
- 最终实页控制台无错误；定向 Profile 页面/Agent 测试 8 项、TypeScript 与 `git diff --check` 通过，未调用模型或写入用户资料。

## 2026-07-25：画像助手 Token 与上下文状态

- 画像助手“技术详情”补齐当前模型、思考强度、累计调用、累计 Token、当前上下文与自动整理阈值，并显示是否已经执行上下文整理。
- 统计直接复用通用 Session Runtime 的 `usage`、`contextUsage` 和 `contextCompacted`；运行状态区只保留连接与本次状态，符合 Agent 页面准则。
- 定向测试 5 项、TypeScript 与 `git diff --check` 通过；1280×720 真实会话显示 80k Token、21k / 90k 上下文（23%），document 宽度 1280/1280，无模型调用或资料写入。
- 修复共享 Agent 输入框的中文输入法确认回车误发送：组合态、`isComposing`、事件码 `229` 和 composition 刚结束窗口均会阻止发送；普通 Enter 与 Shift+Enter 语义保持不变。相关 7 项定向测试和 TypeScript 通过。
- 修复 Agent 消息和会话列表对 SQLite UTC 时间的错误解析，统一通过共享工具显示北京时间；画像助手右栏新增实时本次耗时，终态按持久化完成时间冻结。
- 5174 真实会话从错误的 `08:42` 修正为北京时间 `16:42`，最近消息显示当前北京时间 `00:39/00:40`，右栏显示本次耗时 `18 秒`；未调用模型或写入资料。相关 9 项定向测试、TypeScript 与格式检查通过。
# 2026-07-25：求职目标与项目深挖设计启动

- 完成逐项需求追问并取得最终确认，冻结首版范围与非目标。
- 确认领域所有权、Agent 职责、最小 Tool、最小 `state_schema`、上下文 Offload、项目题入库训练、运行恢复和隐私展示规则。
- 当前进入文档阶段：先写正式规格，再写架构决策，最后形成可执行实施计划；本阶段不修改业务代码。
- 已复核路线图、R3 统一个人画像规格和 2026-07-24 求职目标 ADR；新规格将明确记录收窄项，避免与旧文档产生双重解释。
- 已定位现有 Runtime、Profile confirmed-context、题库 schema 和前端路由扩展点；后续计划将复用这些边界，不新建第二套 Runtime 或个人资料存储。
- 已新增正式产品规格 `2026-07-25-job-target-and-project-deep-dive-design.md`，覆盖领域对象、核心流程、页面、恢复、安全和验收。
- 已新增 ADR `2026-07-25-job-target-project-training-runtime-boundaries.md`，记录状态所有权、三类执行单元、最小 State/Tool、Message→Execution 重试和 SQLite 恢复边界。
- 当前开始编写纵向实施计划；计划会控制任务数量，以每个任务可独立验收为边界，不为拆测试而拆无意义 Task。
- 已新增实施计划 `2026-07-25-job-target-and-project-deep-dive.md`，拆成 9 个纵向 Task；每个 Task 只运行受影响测试，全量回归和浏览器验收集中在跨层收口。
- 已完成规格覆盖表、类型/接口复核、占位符扫描和空白检查；无遗漏需求或未定义占位项。
- 本轮仅修改正式设计文档和本地规划状态，未修改业务代码、数据库或用户保留的两个未跟踪文件。

## 2026-07-25：求职目标与项目深挖实施

- 用户选择内联执行 Task 1–9，不创建子 Agent。
- 已确认当前位于隔离 worktree `r2-complete-review-agent`、分支 `feature/review-agent-workspace`，不是 submodule。
- 前端基线 `ModelBindings + App` 共 14 项通过。
- 后端首次基线命令使用的主仓库 `.venv/bin/python` 已不存在（1 次失败）；停止重复该路径，改为定位当前 worktree 或系统可用的锁定环境。
- Task 1–3 完成：新增目标训练迁移、`job_analysis`/`project_deep_dive` 模型用途、Message→Execution 多尝试关系、目标/JD/要求领域 API、持久工作单元和最小只读 Tool。
- Task 4–6 完成：新增求职目标工作台、要求安全批量确认、核心/补充项目选择，以及复用统一 Agent Shell 的项目教练；暂停、刷新、恢复、终止和原消息重试不复制用户 Message。
- Task 7–8 完成：讲解章节逐段确认进入统一画像，四类差距保留明确去向；确认后的项目题进入现有题库“项目经历”分类并复用 Review Runtime，评分冲突保持待处理。
- 浏览器隔离工作区完成创建目标、自动分析 JD、确认三条要求、选择核心项目、七维深挖、暂停刷新恢复、确认候选题并在复习页看到题库增量；390/768/1024/1200/1440 五档无水平溢出。
- 验收中修复无 JD 引导、保存 JD 未自动分析、批量确认残留勾选、完成态仍显示终止、项目教练文案与状态中文化等具体问题。
- 最终后端全量 `778 passed`（1 条既有 Starlette 弃用 warning）；前端全量 47 个文件 `211 passed`；最终受影响组件 6 项与 production build 通过，仅保留既有 chunk 大小提示。
- 当前成熟度边界：隔离环境未配置外部 Provider，真实模型项目题评分与完整扩展浏览器组合需由用户环境补验；结构化契约、冲突 pending 和题库投影已有自动测试。

## 2026-07-25：求职目标实页纠偏 Task 10

- 新建目标改为 JD 优先：先保存原文，再由一次结构化岗位分析同时识别公司、岗位、
  经验范围和原子要求；无 JD 的手动创建保留为次入口。
- 生产 Workspace Runtime 已注入 `job_analysis` 与 `project_deep_dive` Agent；
  项目深挖每轮使用已确认目标、项目、岗位要求和有效消息生成结构化评价与追问。
- 项目深挖已区分会话暂停/继续/结束和当前模型执行停止；停止、失败后的原用户消息
  标为未完成，重试复用原消息创建新 Execution。
- Message/Execution API 已统一前端字段，消息显示北京时间和模型耗时；右侧栏展示调用、
  Token、上下文与压缩状态，输入区复用 R2 已验收的组合式布局和中文输入法保护。
- 准备总览的下一步、统计和三个阶段均可导航；运行状态提供已保存数量、耗时、暂停、
  继续和终止，不再只显示转圈。
- 当前定向证据：后端目标 API/Service `4 passed`，前端目标组件 `3 passed`，
  Python compileall、TypeScript、production build 和 `git diff --check` 通过。
- 5174/8000 实页关键路径通过：JD 创建默认入口、总览步骤导航、岗位要求工作台、
  项目教练右栏与统一输入区均正常；1280×720 document 无横向或纵向溢出。
- 对既有暂停会话执行“继续→暂停”，两次 API 均为 200，输入区随状态正确切换，
  无活跃 Execution 时不出现停止；浏览器控制台无错误。未发送模型请求，未修改画像、
  岗位要求或题库。

## 2026-07-25：求职目标确认与项目深挖收尾交互

- 岗位要求页把“推荐确认”和“人工确认”显式分开：有可定位原文、且非系统推断的待确认项可一键确认；其余项目保留逐项选择、确认或忽略。
- 已结束或终止的项目深挖不再成为死路：保留原会话作为历史记录，同时提供“重新开始本项目”和“选择其他项目”入口；重新开始会创建新的会话尝试，不覆盖旧记录。
- 右侧“待处理建议”成为可执行入口：知识缺口生成项目题、表达缺口整理讲解建议、经历风险标记为已知风险；个人资料缺口引导至个人画像页补充。
- 定向验证：后端目标 API/Service `4 passed`，前端目标组件 `4 passed`，Python compileall、TypeScript、production build 与 `git diff --check` 通过；浏览器只读确认岗位要求页顶部的一键确认入口与推荐标签可见，未改写用户测试数据或触发模型调用。

## 2026-07-25：岗位要求重新分析与单条确认纠正

- 同一 JD 的重新分析改为“建议快照替换”：服务端以规范化文本而非模型临时 key 对齐同一条要求，保留既有确认/忽略决定，并删除本轮不再出现的 pending 建议，避免每次分析累加。
- 只对标点、空白和“或/或者”等书写差异自动视为同一条；语义相近但不等价的要求不会静默继承确认，仍留给用户人工核对。
- 每条待确认要求旁边和详情区顶部都提供“确认/忽略”，底部仅保留批量操作，不再是单条操作唯一入口。
- 定向验证：目标 Service `4 passed`（含重新分析去重/保留确认状态），前端组件 `4 passed`、TypeScript 与 `git diff --check` 通过；8000 后端已重启加载修复。

## 2026-07-25：岗位要求操作栏可见性修正

- 岗位要求工作台的底部批量“忽略所选 / 确认所选”操作栏固定在工作区底边，并提高层级；要求列表和详情继续各自滚动，不再把操作栏推到可视区域外。
- TypeScript 与 `git diff --check` 通过。

## 2026-07-25：项目教练暂停恢复与交互反馈修正

- 根因：暂停/停止正在运行的 Execution 会把原用户消息标为 `unresolved`，但原界面只在 `failed` Execution 时展示恢复动作；`cancelled` 后输入框被正确禁用却没有出口。现在“继续会话”会复用原 Message 创建新的 Execution；无论暂停、停止还是失败，仍保留三种人工恢复动作作为兜底。
- 项目教练结构化契约新增 `coach_reply`。模型回答资料查询时先返回可读的项目事实与缺口，应用层再附加下一步追问，避免用户的提问只被后台评价、却不出现在聊天记录中。
- 统一 Agent 消息复制增加成功/失败可见反馈；个人资料缺口跳转携带目标与项目上下文，画像页提供一键返回项目深挖。
- 定向验证：后端 `2 passed`、前端 `7 passed`、production build 和 `git diff --check` 通过；8000 已重启并确认 `/docs` 返回 200。隔离浏览器不包含用户 5174 工作区，未自动调用真实模型或改写现有资料。

## 2026-07-25：岗位背景分类与岗位要求工作台重构

- 产品语义收敛：团队/部门介绍、业务范围、产品清单、技术宣传和章节标题是“岗位背景”，只用于理解 JD；职责、技能、经验、项目偏好和加分项才进入可确认的岗位要求。
- 模型提示、确定性兜底、历史记录展示和下游准备度/项目深挖消费均使用同一分类规则，背景不会再污染确认、排序、风险或准备状态。
- 岗位要求页改成状态队列；点击内容只打开详情，复选框才影响批量选择。背景以可展开的“了解岗位背景”呈现，详情只强调原文、确认建议和准备情况。
- 修复详情长文本导致的横向溢出与父级错误滚动：详情允许换行，原文独立限高滚动，列表/详情各自滚动，固定的工作区头部不再因点击详情被挤出视野。
- 定向验证：后端 `7 passed`、前端 `6 passed`、production build 与 `git diff --check` 通过；未触发外部模型。

## 2026-07-25：岗位要求可逆确认与动作样式统一

- 已确认要求可“撤回确认”，已忽略要求可“恢复待确认”；两者回到待确认队列后才能重新做确认或忽略，准备度不会继续使用已撤回内容。
- 后端 Decision API 允许受版本保护地写回 `pending`，并明确回传 `pending_ids`；不会创建新要求或丢失原文依据。
- 岗位要求列表的确认/忽略从裸按钮迁移到共享 Button，消除局部 CSS 覆盖造成的颜色和文字不一致。
- 定向验证：后端 `6 passed`、前端 `7 passed`、production build 与 `git diff --check` 通过。

## 2026-07-25：岗位要求批量撤回与详情按钮修正

- 已确认和已忽略页签的复选框改为可用：已确认支持“撤回所选确认”，已忽略支持“恢复所选待确认”；切换页签时清空选择，避免跨状态批量提交。
- 修复详情区蓝色主按钮无文字：标题 `span` 选择器曾误伤 Button 内部标签，现仅命中标题元信息，按钮继承共享组件的白色主按钮文字。
- 定向验证：前端 `8 passed`、production build 与 `git diff --check` 通过。

- 批量撤回/恢复不再只依赖可能被长列表遮住的底部栏：已确认/已忽略页签的顶部主操作区分别提供“批量撤回确认 / 批量恢复待确认”，随勾选启用。

## 2026-07-25：UX 审计 P0 修复

- 项目深挖增加消息意图门禁；提问、修正和指令不再推进阶段或写入讲解。
- 通用 Execution 持久关联输入 Message，并提供失败重试、编辑后重试和放弃 API。
- 画像助手增加失败恢复卡；标题投影改读产品层首条用户消息，并兼容隐藏历史内部状态标题。
- 自动证据：受影响后端文件 `26 passed`、画像组件 `7 passed`、前端 production build、Python compileall 通过。
- 浏览器只读证据：现有失败会话显示短标题、33 秒耗时及三种恢复入口；未发送模型请求或修改现有数据。8000 后端已启动供人工复核。

## 2026-07-25：UX 审计 P1——岗位要求状态与分类

- 分析结束后主动失效目标列表缓存，避免页面已经拿到 `review_pending`，标题仍因旧目标摘要而显示“正在识别”。
- 当 JD 本身没有足够明确的岗位名称或经验范围时，页面改为“岗位信息待补充”，保留已经完成的岗位要求分析结果，不再制造无限处理中假象。
- 团队/部门名称、团队职责说明、背景章节和公司/部门标注统一划入“岗位背景”；带有“需要”等候选人要求语义的文本不会被误滤。
- 定向验证：后端 `8 passed`、前端岗位目标组件 `9 passed`、production build 与 `git diff --check` 通过。浏览器控制连接当前没有打开的 5174 标签，未对用户工作区数据执行写操作。

## 2026-07-25：UX 审计 P1——运行事实与跨页刷新

- 简历处理耗时不再直接 `new Date()` 解析 SQLite 无时区 UTC；统一复用共享时间解析后再与浏览器当前时钟相减，避免首次显示数百分钟。
- 画像批量确认会同时刷新待确认快照、画像摘要、简历版本详情和材料列表；题目发布/更新/删除会同步失效题库概览与复习可用题，跨页返回无需整页刷新。
- Runtime 诊断事件改经共享 `Asia/Shanghai` formatter 渲染，避免同一产品内出现 UTC 与北京时间混杂。
- 定向验证：前端相关 `30 passed`、production build 与 `git diff --check` 通过。仅保留既有 bundle 体积提示。

## 2026-07-25：UX 审计 P1——移动端求职目标导航

- 390px 下不再复用桌面侧栏：目标选择收敛为顶部的原生选择器，保留“新建求职目标”入口，正文获得完整可用宽度。
- 四个功能页签保持完整名称和 44px 触控高度；导航自身可横向浏览，页面主体没有横向溢出，也不再把标签拆成单字。
- 本次延续既有视觉 token，不引入新的配色或卡片体系；组件定向验证 `10 passed`、production build 与 `git diff --check` 通过。

## 2026-07-25：UX 审计 P2——项目经历题可追溯审阅

- 原候选题是深挖完成后硬编码的六道通用模板，既不说明题目如何关联 JD，也无法让用户判断项目事实来自哪里；现改为按项目标题、已确认岗位要求、对应深挖阶段的用户回答和开放缺口构建候选题，并把这些依据随候选题资源返回。
- 旧候选题不需要迁移：读取时使用相同规则补齐“为什么生成 / 本次参考的岗位重点 / 可用项目事实 / 仍需补充”，避免历史会话成为不可解释的黑盒。
- 审阅页改为内容优先的候选题卡片：待确认题可勾选、批量确认或忽略、逐题编辑；确认后投影进既有项目经历题库，资料本身不被改写。服务端同时补上目标所有权校验，阻止跨目标操作候选题。
- 定向验证：后端项目训练工作流 `8 passed`，前端求职目标组件 `11 passed`，Python compileall、TypeScript、production build 和 `git diff --check` 通过；只保留既有 bundle 体积提示。

## 2026-07-25：UX 审计 P2——信息口径与筛选收敛

- 简历提取从“完全相同才去重”改为使用既有 Claim 身份规则合并同一实体的互补字段与来源；冲突字段仍以置信度更高的一方为准，不做模糊拼接。避免同一项目的职责、成果被拆成多张待确认卡。
- 学习资料页不再向用户暴露 Vault、存储路径或索引实现：资料和草稿分别呈现为“导入资料”和“整理结果”，加入资料库后使用用户可理解的状态与恢复动作。
- 题库主题与状态、难度、来源统一为顶栏筛选，桌面布局从重复的三栏目录收敛为题目列表和详情；窄屏不再为主题目录额外占用一行。
- 设置页模型用途统计由过期的 6 项修正为实际 8 项，岗位分析和项目深挖模型缺失时不再被误标为配置完成。
- 定向验证：简历提取 `10 passed`；学习资料页 `15 passed`；题库页面 `6 passed`；设置页 `3 passed`；Python compileall、TypeScript、production build 与 `git diff --check` 通过。生产构建仅保留既有 bundle 体积提示。

## 2026-07-25：UX 审计 P2——历史重复建议与项目题真实生成

- 待确认画像新增显式“整理重复信息”预检：只识别同一分类、同一稳定身份的未确认新增建议；用户确认后合并互补字段与原文依据，保留一个待确认项，并把其余项标为 superseded 以保留审计记录。已确认内容、更新建议和缺少稳定身份的信息不参与。
- 整理提交会在单个 `BEGIN IMMEDIATE` 事务中重新核对完整分组；预检后有任一建议被处理或新增重复组时返回冲突，不按旧快照误合并。页面不会在读取时偷偷修改数据。
- 项目深挖完成后的候选题从六道服务端模板切换为一次有界批量模型调用，复用 `project_deep_dive` 模型绑定但使用独立结构化输出和隔离线程。最多六题、同维度至多一题；服务端补齐已确认岗位重点、项目事实、深挖回答和开放差距依据。
- 无模型测试环境仍使用确定性候选题以保持离线回归；真实 Agent 调用失败时不会静默降级为模板题，本轮 Execution 保持可重试语义。
- 定向验证：画像后端 `21 passed`、画像前端 `6 passed`、岗位训练相关 `15 passed`，Python compileall、TypeScript 与 `git diff --check` 通过。

## 2026-07-25：P2 实页回归补丁

- 5174 隔离 Workspace 验证重复待确认建议从 2 条安全整理为 1 条，互补职责与技术栈完整保留，成功提示、审计状态和 1280px 无横向溢出均通过；临时测试记录随后清理。
- 实页发现左侧目标仍显示“岗位信息识别中”，与详情的“岗位信息待补充”冲突；现统一为后者。
- 历史 JD 的 `公司｜团队｜岗位` 元信息曾作为独立已确认要求进入项目题依据；团队职责过滤补齐显式主语规则，纯竖线元信息转为岗位背景，混合旧记录只去掉元信息与背景段，真实候选人职责继续保留。
- 复验后岗位要求为 21 条、岗位背景为 3 条；候选题依据不再出现公司/团队元信息。岗位训练/目标 `18 passed`、前端组件 `11 passed`、TypeScript 与 `git diff --check` 通过。

## 2026-07-25：P2 最终回归

- 后端全量回归 `796 passed`，仅保留既有 Starlette/httpx 弃用提示。
- 前端全量首次为 `222 passed / 1 failed`；唯一失败是题库主题筛选已经改为下拉框，旧测试仍查找已移除的主题按钮。测试改为操作真实的“主题筛选”控件后，该文件 `21 passed`。
- 前端 production build 通过；仅保留既有 bundle 体积提示。未因测试维护改动产品交互，也未再次运行整套前端回归。

## 2026-07-25：全流程 UX 复查后的可信度与响应式修复

- 画像助手与项目深挖在 1199px 以下默认收起依据侧栏；1024px 与 390px 均由会话区内部滚动，历史消息不会再把输入框推到首屏之外。手机端完整简历同样使用固定阅读区，并提供可收起、去正文和去重后的目录抽屉。
- 题目整理遇到纯标题工作单元时不再调用模型或因“无题目”自然语言响应而整批失败；失败态、执行状态和候选质量提示改为用户可理解的中文，不展示内部状态码。
- JD 分析先识别公司、岗位和经验元信息，再区分团队背景与候选人要求；来源真实但语义含糊的口号不再进入“一键确认推荐项”。
- 画像助手默认参考范围补齐教育、证书和成果，提示词禁止输出工具授权与内部重试过程；新会话标题改为短意图标题，既有长标题仍可手动重命名。
- 知识库隐藏非设置页的工作区路径和 MIME/Vault 术语，只保留软删除，并为未整理资料提供明确“去整理题目”入口。
- 定向验证：题目整理与岗位相关后端 `62 passed`；App、知识库、个人画像前端 `22 passed`；production build 与 `git diff --check` 通过。浏览器实页验证覆盖 1280 / 1024 / 390，未触发模型调用。

## 2026-07-26：工作区管理与模型设置重构

- 已通过 grill-me 与用户确认：删除采用回收站；永久删除保留本机 Vault 文件夹；切换不终止原工作区任务；运行中任务阻止删除；切换器位于左侧栏底部；工作区支持默认目录名和手动重命名。
- 已确认模型设置结构：Provider 全局复用、单项展开管理；任务模型按业务分组并按 Workspace 保存；有未保存修改时显示固定操作栏并在离开前提醒；技术信息默认折叠。
- 已完成应用数据库迁移、显式当前工作区、Runtime 卸载/忙碌检查、回收/恢复/永久删除 API；永久删除只清理 `.cyber-interview-agent` 与 `artifacts`，保留 `knowledge-vault`。
- 左侧栏工作区切换器显示名称、可用性和运行任务数；设置页支持创建、重命名、切换、回收、恢复及带影响统计的永久删除确认。
- 模型设置改为全局服务单项展开、工作区任务模型分组和固定保存栏；未保存时拦截设置分组、工作区及主导航切换，并注册浏览器离开提醒。
- 定向验证：后端 `9 passed`、前端设置组件 `8 passed`、Python compileall、TypeScript、production build 与 `git diff --check` 通过。浏览器实页验证覆盖 1280px 桌面切换菜单和约 688px 响应式页面，均满足 `scrollWidth == clientWidth`。
- 启动级 `test_health.py` 在当前系统 Python 因缺少 `langchain_anthropic` 无法收集；运行中的 8000 服务已热更新并通过 5174 实页读取新的工作区 API，未为该环境问题安装依赖或扩大测试范围。

## 2026-07-26：本地复习与开发环境隔离

- 本地主工作区固定使用 `8000/5173` 和默认历史数据；开发 worktree 固定使用 `8001/5174`、独立 `CYBER_INTERVIEW_AGENT_DATA_DIR` 与测试 Workspace。
- 完整启动命令和防串库检查记录在主工作区本地文件 `/Users/miracle778/Project/cyber-interview-agent-new/docs/verification/local-dual-environment-runbook.md`；后续启动服务前先读取该文件。

## 2026-07-26：题目整理输出截断与旧批次恢复

- 根因确认：新 planner 只按 6,000 字符打包，漏掉既有“最多 6 个 section”限制；当前失败单元分别含 47/42 个短 section。模型在 Anthropic-compatible 别名下实际返回 GLM-5.2，2,048 输出 Token 全被默认 Thinking 消耗，`stop_reason=max_tokens` 且没有结构化结果。
- discovery 同时限制 section 数和字符数；旧批次不重新规划 unit index，而是按已持久化 Work Item 的 source refs 原地拆成最多 6 段的子调用。结构化输出被截断时只递归拆小当前子调用，父 Work Item 继续作为持久恢复边界，completed Work Item 不重放。
- Provider 测试会自动保存实际模型 ID、推理控制能力和探测时间；页面没有新增用户能力字段。真实轻量探测确认配置别名 `claude-opus-4-8` 实际为 `glm-5.2`，观察到默认 Thinking，并使 Anthropic-compatible 标准整理显式关闭推理。
- 进度显示不再用已发现 seed 的下一阶段状态覆盖 discovery Work Item：真实失败会话显示 77/80 已完成识别、80 个已发现题目、2 个可继续处理、1 个等待处理，旧进度和原 Batch 均保留。
- 自动证据：后端定向 169 项通过，两个新增 API 字段断言修正后失败项 2/2 通过；前端 `CurationRuntimePanel` 16 项与 TypeScript 通过；compileall、`git diff --check` 通过。5174 实页显示真实进度且 console warning/error 为 0。
- 开发 app/runtime SQLite 已备份到 `/private/tmp/cyber-interview-agent-dev-*-before-adaptive-curation-20260726.sqlite`。真实恢复会发送剩余材料片段，因缺少独立 payload 授权未由 Codex 自动触发；用户可在页面点击“继续整理”完成最终 Provider 验收。

### 2026-07-26 第二次真实恢复失败

- 恢复已完成全部 80 个 discovery Work Item，并进入 166 道 Seed 的 enrichment；95 道已经持久化为候选，旧完成项未重放。
- 失败不再是 Thinking 或 `max_tokens`。GLM 返回了一次畸形 tool payload，LangChain 将其包装为 `StructuredOutputValidationError`；原 Seed 级容错只捕获 Pydantic `ValidationError/ValueError`，包装异常越过边界并使整波 Execution 失败。
- enrichment 现把该包装异常按 `invalid_provider_response` 进入既有两次 Seed 级重试/跳过机制，不再击穿整批。进度阶段同时改为：全部 discovery 完成且 Seed 已建立后，以 Seed 状态显示 enrichment，不再退回“80/80 已识别”。
- TDD RED 精确复现整波失败和阶段误报；GREEN 后两个回归通过。受影响 Graph/API 文件完整 `95 passed in 6.75s`，`git diff --check` 通过。
- 8001 卡死的 reload 父子进程已停止并按隔离数据目录重启。真实会话现为 enrichment `95/166`、4 可继续、67 等待；尚未由 Codex 再次触发外部模型调用。

### 后续诊断体验待办

- 已在 `task_plan.md` 记录“Agent 模型调用记录查看器”：从运行详情按 Session/Execution/Invocation 查看本地 JSONL 中的模型输入、输出、错误和 Tool 调用。
- 该入口仅在开发/诊断模式开放，默认折叠敏感正文，保持 Workspace 隔离、secret 过滤和 Trace 读取 fail-open；不纳入当前故障修复。

## 2026-07-26：复习 Checklist、批量确认与发布进度

- 复习题改为领域 Checklist：必答点累计覆盖，全部通过或显式跳过后才进入下一题；辅助意图不会关闭当前输入。提示、查看答案、跳过分别保留结果类型和援助痕迹，失败重试不重复写入回答。
- 对话区新增冻结题目卡，展示题目原文、必答点覆盖数量、缺失方向，并提供查看来源、逐级提示、查看答案和跳过入口。
- 整理、复习、深入讨论及共享 Composer 统一使用 IME 安全键盘 Hook；组合输入、组合结束同一事件与 `keyCode 229` 均不会误发送。
- 候选题“确认内容”和“发布入库”拆为两个状态。题库支持当前筛选结果全选、推荐项选择、批量确认预检和逐项回执；确认不会创建发布任务。
- 一键发布复用既有持久 Operation/Item，新增按整理会话查询最近批次；页面展示处理数、已入库数、失败数、当前题、耗时和逐题明细，可停止并只重试未完成项，刷新或重进会话后继续显示。
- 自动证据：后端领域/仓储/图/API/Schema `75 passed`，迁移与批量发布 `30 passed`；前端核心交互 `41 passed`，补充题库批量预检 `22 passed`；TypeScript、production build、compileall 与 `git diff --check` 通过。构建仅保留既有大 chunk 提示。
- 5174 最小验收：题目库 1280px 下页面与 340px 结果栏均无横向溢出，批量控件在栏内完整显示，浏览器 warning/error 为 0。当前开发数据为 164 道已发布、0 道待确认且无复习轮次，因此未触发真实批量确认、外部模型评价或发布写入。

## 2026-07-27：题库选择与统计口径回归修复

- 批量确认改造曾把题目复选框错误限制为仅未确认候选，导致已入库题无法全选或批量移入回收站；现恢复所有当前结果可选，批量确认只消费所选项中的可确认子集，批量删除继续消费完整选择。
- 题目结果头部的宽泛 `span` 规则曾覆盖按钮标签颜色；现限定为直接子元素。纯已入库选择不再显示无意义的禁用“批量确认”，删除按钮恢复白字红底；5174 实页读取得到 `rgb(255,255,255)` / `rgb(180,35,24)` 且操作栏无横向溢出。
- 整理首页明确区分工作区题库与单次会话：顶部展示去重后的“题库题目/已入库题目”，会话卡展示“本次候选/本次已入库/本次待确认”，不再把全局 163 道与单次 100 个候选表现成同一口径。
- 新增 runtime migration 033：历史 `published` 候选确定性回填为已确认，保留题目、发布和复习数据；后续发布路径同步确认状态，重复激活不重复增加确认版本。
- 会话统计的真实根因是 `curation_resource` 先受仓储默认 `limit=100` 截断、再按 Batch 过滤；现改为先限定当前会话/Batch 并读取完整候选，超过 100 道时会话和 Batch 详情不再少报。当前 8001 真实接口已返回 `candidateCount=164 / publishedCount=164`。
- 定向验证：已入库题全选并批量删除、待确认题批量确认、会话统计跳转共 4 项通过；合并前最终回归为后端 `826 passed`、前端 `234 passed`，production build、compileall 与 `git diff --check` 通过。构建仅保留既有大 chunk 提示。

## 2026-07-27：发布期间读取锁冲突

- 批量发布仍按逐题幂等 receipt 串行提交，以适配 SQLite 单写者和停止后只重试未完成项；本次 57 题真实记录中 32 题在 0 秒级完成，25 题异常耗时 4–11 秒，说明瓶颈不是单题发布本身。
- 根因是 `connect_runtime_database()` 在 Schema 已完整时仍执行 `CREATE TABLE / INSERT OR IGNORE / COMMIT`。整理会话 GET 在构造来源服务时因此变成隐式写请求，与发布事务竞争 5 秒 busy timeout，既拖慢发布，也让页面读取和其中一题发布报 `database is locked`。
- Runtime migration 初始化现在先纯读已应用版本；只有缺少迁移时才进入写路径。保留 WAL 和逐题短事务，不通过并行 SQLite 写入放大锁竞争。
- TDD 回归证明另一个连接持有 `BEGIN IMMEDIATE` 时，完整 Schema 仍可正常打开读取；全新数据库、增量升级和并发读取 3 项通过。重启 8001 后真实整理会话接口返回 `200`，耗时 `0.084s`；只重试原批次唯一失败项时，同一接口仍返回 `200 / 0.047s`，失败项成功入库，批次从 `partial_failure` 收口为 `completed`。

## 2026-07-27：候选生成与发布失败项可诊断

- 候选生成预览新增“只看待重试”快捷筛选；未生成项直接展示经过安全映射的失败原因，并保留单题重试入口，不再让一条异常淹没在长列表中。
- 一键发布进度新增“只看失败”、失败原因和打开对应题目的入口；后端把 SQLite 锁冲突、候选状态冲突归一化为稳定错误码，未知异常不泄露内部信息。
- 定向验证：前端相关组件 `19 passed`，后端错误码与 migration `34 passed`，production build 和 `git diff --check` 通过；5174 只读确认服务与整理入口正常，当前真实失败项已经重试成功，因此没有伪造失败数据做浏览器验收。

## 2026-07-27：题库批量操作栏窄栏修复

- 题库结果栏的选择信息与批量动作改为两层布局；批量确认、批量删除在窄结果栏内按可用宽度排列，不再依赖横向滚动或裁切按钮。
- 定向验证：题库前端 `23 passed`、production build 通过；5174 实页 340px 结果栏满足 `scrollWidth == clientWidth`，批量删除按钮完整位于结果栏边界内。

## 2026-07-27：整理消息运行耗时实时刷新

- 运行中的整理过程消息不再以最后一条阶段事件时间作为结束时间；消息旁耗时按秒刷新，完成、失败或停止后使用执行结束时间冻结。
- 定向验证覆盖运行中 `3 → 5 秒` 实时增长和完成后冻结为 `4 秒`；`CurationConversation` 6 项与 production build 通过。

## 2026-07-27：批量入库期间题目库读取风暴修复

- 实际 40 题批次在用户打开题目库时，前端曾为每个 `publication.changed` 事件重复失效两份全量候选缓存；每份缓存又按 50 条串行读取多页，造成大量重复 GET，并与发布执行争用后端时间。
- 整理工作台和题目库现共享同一份候选缓存；批量发布期间不再逐题触发全量刷新，改为每 3 秒合并刷新一次并在批次结束后最终刷新。
- 候选 API 支持最大 500 条的可控页大小；当前 261 条题库由 6 次串行请求降为 1 次。实页从整理首页切换题目库约 `525ms`，结果完整显示 261 道逻辑题目。
- 定向验证：前端 API/题库 `32 passed`、后端路由 `1 passed`、production build 与 `git diff --check` 通过；未创建新的发布批次或修改现有题目数据。

## 2026-07-27：全应用北京时间显示收口

- 根因不是缺少 `Asia/Shanghai` 参数，而是题库等普通业务页仍直接解析 SQLite 无时区 UTC 字符串，浏览器先把它误认为本地时间，随后再指定北京时间也无法补回 8 小时。
- `frontend/src/shared/time.ts` 现统一提供北京时间、北京时间日期和日期时间格式；题库、题目退回详情、知识库、画像概览、简历版本、删除预检、复习历史、回收站和发布/讨论耗时均已迁移。
- 《应用工作台页面设计准则》新增全局时间与耗时规则，Agent 会话准则改为引用该规则；禁止业务组件自行解析或格式化 API 时间，并明确日期、时间戳、耗时和诊断 Trace 的不同语义。
- 定向自动验证覆盖 8 个测试文件、49 个用例并全部通过，production build 通过；静态排查确认 API 时间的解析与展示只存在于共享时间工具，剩余 `new Date()` 均用于生成当前 ISO 时刻或本地秒表。
- 5174 真实题库页面已将原始 UTC `7/27 10:13` 正确显示为北京时间 `7/27 18:13`；知识库上传时间也通过同一共享入口显示。

## 2026-07-27：题库来源筛选修复

- 候选题保存的是 `source-id#section-*` 证据引用，来源下拉框提交的是纯 `source-id`；前后端原先都使用完全相等比较，导致选择任何真实来源后结果归零。
- 前端来源匹配和后端 `sourceId` 查询现统一解析证据引用中的资料 ID；题目详情的“来源：N 份资料”同时改为按唯一资料计数，证据片段列表仍完整保留。
- 定向验证：题库/详情前端 30 项、后端来源筛选 1 项通过；5174 真实页面选择来源 `a2cb…` 后从 261 道正确筛出 57 道。

## 2026-07-27：开始复习 500 与 Topic 过量展开修复

- 真实请求确认轮次已成功落库，随后 `round_resource()` 因数据库缺少 `review_question_assistance` 表返回 500。新增 runtime migration 034，以 `IF NOT EXISTS` 补齐复习辅助状态与辅助轮次回执表，保留已有轮次和题库数据。
- 迁移应用后，轮次列表接口从 500 恢复为 200；5174 已显示原轮次“等待回答”，并可进入首题对话。复现过程中创建的额外测试轮次已按精确 Session 清理，只保留用户原轮次。
- 创建复习页的 532 个主题改为默认显示 18 个；新增主题搜索、已选数量、清空、展开/收起和专题模式必选校验。
- 定向验证：migration 新建/缺表修复 2 项通过，`ReviewPage` 7 项通过；真实浏览器确认历史页 1 个进行中轮次、首题可打开、Topic 区域默认只有 18 项。

## 2026-07-27：只读数据库结构检查脚本

- 新增 `scripts/check_database_schema.py`，默认检查应用数据库和全部活动 Workspace，也支持用 `--app-data-dir`、`--workspace-root` 指向隔离环境。
- 期望结构直接由当前 migration 在内存数据库中生成；检查覆盖迁移版本、缺表、缺字段、runtime generation 和外键异常，发现问题返回非零退出码且不改动数据库。
- 当前真实应用数据库检查成功；现有 Workspace 因未执行本分支新增 migration 034 被正确报告。临时数据库副本验证可同时报告缺表、缺字段和缺迁移版本；脚本编译与 `git diff --check` 通过。

## 2026-07-27：复习辅助操作事件白名单修复

- 用户截图中的“错误：请求失败”发生在“查看答案”之后。数据库证明消息和答案已经保存，但 `review.turn.responded` 事件缺失；根因是新事件未加入 `ProductEventStream` 白名单，事件发布抛错后把成功操作错误地返回为 500。
- 后端事件允许集合和前端 SSE 订阅列表已同时补齐 `review.turn.responded`。回归覆盖事件可发布、可持久化并被前端收集：后端 4 项、前端 10 项通过。
- 卡在 SSE 长连接上的旧 reload Worker 已停止；8001 使用原 `cyber-interview-agent-dev` 数据目录稳定重启。健康接口和原轮次均返回 200，已保存的“查看答案”及回复未丢失。

## 2026-07-27：复习题目焦点与本地答案说明

- 修正复习会话三块内容却只声明两行 Grid 的布局错误；当前题目、滚动对话和输入框不再互相覆盖。
- 查看提示/答案明确标注为题库本地读取、0 Token；右侧说明提交回答后才会调用评价模型并更新 Token/上下文。
- 定向前端 7 项通过；5174 实页边界测量确认三行按 `279.9px / 87px / 137px` 顺序衔接，整体对话区高度 520px、无重叠或页面溢出。

## 2026-07-27：紧凑题目焦点与历史题回看

- 当前题目卡不再重复展开右侧已有的关键点明细，只显示覆盖计数和待补充数量；5174 当前真实题目卡高度收为约 198px。
- 顶部已完成、已跳过题目改为可点击回看；回看页展示冻结题目、本人回答、评价、关键点覆盖和折叠参考答案，并明确不会改变当前进度。
- 当前题提供“返回当前第 N 题”入口，未来题仍为不可交互状态。真实轮次已完成“回看第 1 题 → 查看跳过记录 → 返回第 2 题”浏览器路径。
- 定向 `CurrentQuestionCard` 与 `ReviewPage` 共 11 项通过，`git diff --check` 通过。

## 2026-07-27：待补充关键点不再被裁切

- 复现并确认右栏标题计数和数据均为 4，缺失来自父级 52px Grid 行与 `overflow: hidden` 的组合裁切。
- 统一由 `.review-insight-content` 承担纵向滚动，关键点模块和列表按内容自然增高，移除内部嵌套裁切；4 条真实数据均进入连续滚动内容流。
- 定向复习前端 12 项通过；真实页面测得右栏 `clientHeight=458 / scrollHeight=730 / overflow-y=auto`，关键点容器 `clientHeight=scrollHeight=324`，4 条内容完整存在且可滚动访问。

## 2026-07-27：复习评价阶段与实时耗时

- 评价节点新增两类安全阶段事件，前端结合持久化的评价开始时间展示四步进度；聊天消息旁和右侧运行详情均按秒更新“处理中 / 本次耗时”。
- 结构化评价完成前不展示未校验的局部 JSON；最终卡片原子出现，阶段 SSE 负责运行反馈，自由文本讨论仍沿用 `assistant.delta`。
- 定向前端 27 项、后端事件与 Graph 12 项通过，production build 与 `git diff --check` 通过；构建仅保留既有大 chunk 提示。

## 2026-07-27：复习题来源文档可读化

- “查看来源”不再把题目草稿 ID 当成资料来源；轮次接口按题目来源关系返回原始文件名、证据片段编号和可用状态。
- 前端按文档合并证据并压缩连续编号，例如 `694–710`；无来源、已删除或缺失资料均使用用户可理解的状态，不暴露 UUID。
- 定向前端 19 项、后端相关 6 项和来源资源 API 1 项通过，production build 通过；5174 实页确认当前题显示 `Mybatis拦截器.md · 原文片段 694–710`。

## 2026-07-27：折叠题目可展开回看

- 顶部题目步进器的省略号从静态装饰改为可访问按钮，明确标注被折叠的题号范围。
- 点击后在步进器下方展开题目选择区；已完成和已跳过题可直接回看，未来题显示待开始且不可点击，选择后自动收起。
- `ReviewPage` 9 项与 TypeScript 检查通过；5174 真实轮次验证第 2–6 题可展开并进入第 4 题回看，选择区随后收起，页面宽度保持 `1280 == 1280`。

## 2026-07-27：答后对照无需等待模型评价

- 首次正式回答落库时同步写入冻结参考答案，页面可在异步评价期间立即展示；消息明确标注“答后对照 · 不影响本次掌握度”。
- 自动展示不写辅助状态，回答前主动查看答案仍保留原有 `answer_revealed` 语义；已回答题的重复入口改为不可点击的“参考答案已展示”。
- 后端原子性/幂等测试 1 项、前端组件 12 项和 TypeScript 检查通过。

## 2026-07-27：评价中可停止或跳过

- 评价过程卡新增“停止评价”；停止会取消当前模型任务、保留已提交回答，并展示“继续评价”与既有“跳过此题”入口。
- 评估中的“跳过此题”不再依赖已经解决的 input request；服务端取消模型任务、持久化 skipped attempt，再从原 checkpoint 单路径推进，防止迟到评价覆盖或重复前进。
- 新增轮次控制幂等表和 `interrupt-evaluation` API；旧的回答前/追问等待态跳过协议保持兼容。
- 自动证据：后端评估中停止/继续与评估中跳过 2 项、既有跳过/Graph/迁移 4 项通过；前端 API、过程卡、页面与类型检查共 34 项通过。

## 2026-07-27：复习报告确认入口恢复

- `report_pending` 结果页改为“复习结果 + 报告确认”双栏，右侧直接展示当前待确认报告正文、确认前编辑、退回修改和确认动作。
- 左侧每份待确认报告可展开，说明确认后的影响，并提供“打开确认区”；底部明确剩余确认数量和处理顺序。
- 报告确认使用业务文案：复习报告为“确认并保存报告”，掌握度草稿为“确认并更新掌握度”，不再展示 `knowledge.publish`、`draftId` 或 `reportKind`。

## 2026-07-27：按资料复习

- 创建复习页新增“按资料复习”，读取正式的题目—来源关系，只列出确实拥有已入库题目的原始资料，并显示当前难度下的可复习题数。
- 选择资料后不再叠加主题筛选；后端再次按 `source_id` 过滤，防止只改前端导致跨资料混题。资料题量不足填写数量时按实际题数创建，不从其他资料补足。
- 历史轮次保留来源模式和来源 ID 快照，旧轮次缺少该字段时仍可正常读取。
- 定向证据：后端 selector/API `15 passed`，前端按资料交互 `1 passed`，`npx tsc --noEmit` 与 `git diff --check` 通过。

## 2026-07-27：复习结果与报告确认工作区重构

- 结果页改为固定高度双栏：右侧报告确认区扩大并与左侧等高，报告正文独立滚动，确认前编辑与底部操作不会被长内容推离视口。
- 左侧题目从连续展开改为“题目索引 + 单题详情”；题量增加只扩展内部列表，不再拉长整页。会话回放、报告和深入讨论分别进入独立页签。
- 新增“深入讨论”统一管理页，展示全部题目以及“尚未开始/已有讨论记录”状态，复用既有会话恢复逻辑。
- 自动证据：`ReviewResults` 与 `ReviewPage` 共 `14 passed`，`npx tsc --noEmit` 通过。5174 真实 10 题待确认轮次完成 1280px 视觉检查，左右等高、列表内滚动、报告正文和讨论入口均可达。

## 2026-07-27：双报告确认与可收起工作区

- 三项复习统计固定为单行标签，避免“掌握良好”在窄栏换行后与两侧指标失去基线。
- 结果栏与确认栏均新增收起/展开控制；展开报告确认时正文占满内容区，展开复习结果时题目回顾占满内容区，窄屏仍保持上下完整呈现。
- 两份报告按真实状态展示“当前待确认 / 等待上一份”；左侧报告按钮和右侧顺序导航共享所选报告，点击尚未轮到的报告会明确说明确认顺序，完成第一份后自动切换下一份。
- 自动证据：`ReviewResults`、`ReviewPage`、`ActionCenter` 定向测试共 `24 passed`，TypeScript 检查通过。5174 真实待确认轮次验证两份报告切换、锁定提示和左右收起恢复均可用。

## 2026-07-27：报告确认后稳定回看

- 报告标题区改为图标、标题和说明同组靠左，去除标题被推到右侧形成的大块无效留白。
- 确认完成后保留当前报告选择；Graph 短暂进入准备下一份的运行态时，报告工作台不再卸载或伪装成页面跳转。
- 轮次资源补充报告 Markdown；已确认和已退回报告均保留“查看报告”，两份报告可分别重新打开，确认状态与正文同步展示。
- 自动证据：TypeScript 检查通过，`ReviewResults` 与 `ReviewPage` 共 `15 passed`，后端轮次资源定向用例 `1 passed`。5175 实页验证两份已确认报告可分别回看、收起后回到报告列表，未执行新的确认或退回操作。

## 2026-07-28：简历单版本安全删除

- 新增版本级删除预检与执行接口，复用删除计划、影响重算、乐观锁、幂等回执和存储引用计数；只清理目标版本及其 Evidence，正常列表隐藏删除墓碑。
- 版本删除采用 Workspace 待确认总锁：任一待确认信息存在时，所有版本入口禁用，服务端预检与执行再次校验；当前版本必须选择剩余版本接替，历史版本无需替换，唯一版本只能删除整份简历。
- 修正预检后的竞态：若随后新增待确认信息，执行返回稳定的 `profile_material_version_has_pending_proposals`，而不是通用影响冲突，且不会清理目标版本。
- 本次门禁修正定向验证覆盖同材料其他版本、其他材料的预检后竞态、稳定 API 409、前端全局禁用文案和总数未加载保护。
- 前端将“删除当前版本 vN”和“永久删除整份简历（含 N 个版本）”拆成独立入口与确认弹窗，成功后留在“简历与来源”并选中可用版本。
- 原跨层自动证据：后端相关 `60 passed`，前端相关 `17 passed`，production build 与 `git diff --check` 通过；当时 5174 尚无 Workspace，因此未执行浏览器写入。
- 删除预检现返回受影响 Claim 的结构化内容快照；版本弹窗用可读标题代替重复的类型名，并可展开查看具体字段、目标版本依据数和其他版本依据数。
- 版本弹窗补齐逐项勾选、全选、已选数量和“仅处理所选”的批量下拉；批量删除自动跳过服务端标记为不可删除的受保护 Claim，未选项保持原处理方式。
- 增量验证：后端版本删除 service/API `7 passed`；版本/整份删除与版本菜单前端 `12 passed`；TypeScript 通过。5174 真实数据只读验收中，12 条受影响要点全选后批量控件启用，成果详情可展开显示正文和依据数量；未输入删除确认词、未提交删除。

## 2026-07-28：求职目标侧栏收起与 JD 分析过程可见

- 桌面端求职目标列表支持收起为 72px 图标栏和再次展开；收起后仍可切换目标，并通过可访问名称和悬停标题识别岗位。平板、移动端维持原有下拉选择。
- 运行中或暂停的 JD 分析默认展示五步业务进度；页面同步显示当前阶段、任务完成数、本次/累计耗时、最近北京时间更新和活动任务数，已完成过程仍可展开回看。
- 页面只展示业务处理步骤，不暴露模型内部推理；岗位要求和项目匹配继续按处理进度逐步保存。
- 自动证据：目标组件 `12 passed`，production build 通过；构建仅保留既有大 chunk 提示。隔离浏览器无 Workspace，未创建测试数据或触发真实模型调用。

补充：项目教练运行栏的上下文占用与阈值统一使用 `k` 单位，例如 `885 / 89600` 显示为 `0.9k / 89.6k`。目标组件 `12 passed`，TypeScript 与差异检查通过。

## 2026-07-28：简历版本删除后的画像变化可见

- 统一画像资源新增 `supportStatus`；保留但失去全部原文依据的卡片持续展示“依据不足”，原来源改为“原来源已删除，本人保留”。
- 画像职业名片汇总缺少来源依据的数量，核心技能和各类画像卡片均能定位具体受影响内容。
- 删除完成后保留变化摘要，分别列出画像已移除、保留但缺少来源、仍有其他来源支持的条目，并可直接切换到“我的画像”核对。
- 自动证据：后端版本删除与画像投影 `6 passed`，前端版本删除、画像总览和版本菜单 `9 passed`，`npx tsc --noEmit` 与 `git diff --check` 通过。
- 5174 真实数据只读验证：画像显示 `12 条内容缺少来源依据`；受影响成果卡显示“依据不足”和“原来源已删除，本人保留”。未执行新的删除操作。
- 修正核心技能摘要的 CSS 作用范围：普通技能和依据不足技能恢复为尺寸一致的胶囊标签，仅通过蓝/黄语义色区分；5174 实页视觉检查通过。

## 2026-07-28：求职目标补充入口与项目重点保存反馈

- “待补充”状态现在会明确列出缺少的岗位字段，并可打开补充弹窗保存公司、岗位名称和经验/职级范围。
- 项目重点保存原本已成功写库但没有回显；Readiness 现返回已保存的核心/补充项目，页面恢复真实选择，并显示保存中、已保存或失败原因。
- 定向验证：前端目标组件 `14 passed`、production build 通过；后端工作流 `1 passed`；差异检查通过。
## 2026-07-28：Claim 多来源支持与删除后重算

- 新增多来源回归：删除 v1 时，v2 Source 仍有有效 Evidence，预检保留剩余依据，执行后
  Claim 继续为 supported，目标 Source 变为 source_deleted。
- 统一画像新增 related/manual 派生状态和可读 Evidence 摘要；不自动把相似描述合并为
  直接事实。
- 开发数据库执行修复：13 条历史失效 Source 被纠正；投影结果为 supported 16、
  related 3、unsupported 4。
- 定向后端 80 tests、前端 10 tests、TypeScript 和 compileall 通过。
- 5174 真实页面确认：职业名片显示 3 条“相关内容待核对”和 4 条“缺少直接依据”；
  “依赖降级与故障演练”详情展示剩余简历原文及“项目经历 · 第 39–46 行”，
  不再暴露来源定位 JSON。未执行全量回归。

## 2026-07-28：来源核对工作区与画像会话筛选

- 新增“来源核对”一级子页签，集中展示相关内容待核对与缺少直接依据的画像；职业名片两类数量可直接进入对应筛选，列表可查看可读来源片段并打开画像编辑器。
- 画像会话资源补充最新 Execution 状态和待处理 Action 数量；“正在运行/需要处理”不再错误依赖会话生命周期。
- 自动验证：后端画像会话 API `3 passed`，前端入口、来源核对和会话筛选 `7 passed`，TypeScript 通过。
- 5174 当前未启动，未执行本轮浏览器检查；未触发模型调用或数据写入。

增量布局修复：来源核对页改用共享 `TaskWorkspace/TaskWorkspacePane`，桌面端固定标题与筛选、仅卡片列表滚动，移动端恢复自然滚动；父容器改为识别通用工作台标记，不再依赖新页面类名名单。`ProfilePage` 4 项、TypeScript、production build 和差异检查通过；5174 未启动，未补浏览器证据。

## 2026-08-02：个人资产—求职目标—专项复习第一批串联

- 个人画像首页改为“职业资产”叙事，突出已确认资料、代表项目和技能，并提供求职目标、自主复习两个下一步；来源问题保留在可展开的资料质量区。
- 求职目标准备总览新增四类准备摘要和四步路径；岗位基本信息不完整时优先补全，只有已确认项目题时才启用岗位专项复习。
- ReviewRound settings 新增向后兼容的 `question_scope/source_job_target_id/project_claim_id/scope_label`；选择器先按岗位或项目来源隔离，再应用难度和主题策略。
- 岗位与项目入口均打开同一个复习工作台；专项设置显示来源、匹配数和安全空状态，历史/活动轮次显示自主、岗位专项或项目专项，返回按钮回到原业务页面。
- 自动证据：后端定向 `30 passed`，前端定向 `43 passed`，TypeScript、Python compileall 通过。
- 5174 只读证据：自主复习历史显示正常；个人画像 CTA 和求职目标准备总览可见；当前目标没有已确认项目题，岗位专项设置显示 0 题并正确禁用，未扩大到普通题库；1280 宽度无横向溢出。未创建轮次、未调用模型、未改现有数据。
- 增量布局修复：总览下方四张稀疏等高卡收敛为紧凑“准备路径”，明确已完成、当前建议、待完成和未解锁状态；专项复习入口不再嵌套大尺寸按钮。目标组件 `16 passed`，TypeScript 与差异检查通过；隔离浏览器无 Workspace，未构造测试数据。
- 个人画像概览增量修复：求职方向与核心技能改为主次双栏且等高；没有待完善项时不再显示黄色空提醒，有真实缺口时才跨栏展示。材料版本详情查询只接受当前 Workspace 且仍在版本列表中的选择，并在 Workspace 切换时清空文档/证据选择，避免旧版本 ID 产生瞬时 404。画像定向 `8 passed`、TypeScript 与差异检查通过；5174 实页复核双栏为 `414 / 736px`、同高 `164px`，控制台无错误或警告。
- 证书与成果页改为内容自适应：两类都有内容时双栏，仅一类有内容时单栏铺满；两类均为空时默认引导补充成果，证书保留为可选轻入口。画像组件 `3 passed`、TypeScript 与差异检查通过；5174 实页确认成果区宽 `1166px`、无横向溢出，控制台无错误或警告。

## 2026-07-29：题目识别单块失败兜底

- 识别工作项首次失败后在 Graph 内自动重试一次；第二次仍失败才跳过该单元，其他单元继续并保留成果。
- 模型明确用自然语言表示无可识别题目时安全归一化为零题；不明确的非结构化正文继续报错，避免静默漏题。
- 单块失败只在测试层通过 `PartialFailureAgents` 确定性注入；产品 Agent、用户材料和运行环境均不包含故障标记或开发开关。
- 自动验证：题目整理 Graph `50 passed`、运行面板 `18 passed`、TypeScript 与差异检查通过。

## 2026-08-01：Evaluation v2 Phase 1 业务结果评估闭环

- 新增 `question-curation.v2`：题目整理新评估不再读取完整 Trace，而是从领域表生成不可变业务结果投影和任务级最小 Judge View。
- 代码预判明显的“不适用”和“证据不足”；混合答案尚未拆字段时不会伪造原文忠实度结论，只有适用维度才产生质量等级。
- Judge 工厂同时提供 v1 百分制和 v2 等级制结构化输出；v1 历史结果和数据保持不变。
- API 已保存业务结果 hash、Judge 数据类别和明确排除项；前端区分“初版质检 / 业务结果质检”，展示符合要求、基本可用、建议复核、严重问题、证据不足和不适用，不生成 v2 总分。
- 定向证据：后端 19 项通过；前端评估组件 13 项和 TypeScript 通过；`git diff --check` 通过。

## 2026-08-01：Evaluation v2 Phase 2 确定性规则与校准

- migration 042 为维度结果增加业务 `evidenceRefs`，领域行、结果 hash、计数和来源引用不再伪装成 Trace event hash。
- 公共只读规则检查 Workspace/Execution 身份、稳定 ID、计数守恒和来源引用；迟到结果、Tool/写入边界、Receipt/Event 一致性在证据未投影时明确返回证据不足。
- v1 页面改称“评估证据完整性检查”；v2 页面显示“确定性业务规则”，二者均不暴露或启用阻断能力。
- 新增可重复的正向、负向、模糊校准用例与 FP/FN 报告；当前合成样例为 0/0，但正式文档明确不能据此升级发布门禁。
- 定向证据：后端 55 项、前端 13 项和 TypeScript 通过。

## 2026-08-01：Evaluation v2 Phase 3–5 任务评估与隔离回归

- 12 个任务级 v2 Pack 已接通 Outcome Adapter、最小 Judge View 和任务业务规则；题目原文答案与 AI 补充独立持久化、展示和评价。
- 新增显式“记录可回归输入”本机设置；Graph 启动前冻结 runtime DB、checkpoint 和材料。历史运行没有执行前快照时只保存为不可运行的历史结果案例。
- 来源模型配置和当前模型配置分别通过产品 Workspace Runtime 在两个临时沙箱重跑；确定性规则先执行，匿名 A/B Judge 后执行，网络、限流、锁和 Judge Provider 失败单独记录。
- 题目整理和 review discussion 两条 Runtime 集成用例证明业务结果被重新生成、正式 Workspace 不变、沙箱清理和版本清单存在。
- v2 趋势按 Pack、契约版本和 run kind 分组；新增需复核/严重、Judge-人工一致、用户修改/拒绝和基础设施失败指标。
- 自动门禁模块默认关闭、批准规则集合为空，只允许未来经真实案例校准和 ADR 批准的确定性规则阻断；Judge 结论不进入门禁。
- 新鲜定向证据：回归/设置/迁移/Judge 后端 22 项，质量门禁与 Runtime 集成 7 项；前端类型检查及设置/评估页面 7 项通过。完整回归、真实 Provider 浏览器案例和文档门禁待最终收口统一执行。

## 2026-08-02：面试复盘 Task 7 候选沉淀与安全发布

- 候选生成接入分析 finalizer，只读取 confirmed/formal 结果；Review 相似题、项目画像匹配均只形成建议，不自动合并。
- 题库新建/补充进入 Review 自有待确认草稿，画像与项目讲解进入 Profile 待确认 Proposal；所有用户决定均使用乐观锁和复盘 Receipt。
- 行动项按 gap 生成并支持完成/忽略；立即练习只接受 active Review Question，并返回稳定复盘来源链接。
- 新增 `interview_retrospective` Knowledge 文档类型和 migration 046；发布稿按用户选择投影，不接收原始转写、pending 推断、Prompt、Provider 响应或聊天消息。
- 新增候选、批量决定、行动项和发布草稿 API；批量部分失败保留成功结果和失败候选，重复请求不产生重复跨域资源。
- 自动证据：候选/发布/API 聚焦测试 14 项通过；复盘、Review、Profile 与 Knowledge 受影响回归 134 项通过；Ruff、compileall 与差异检查通过。

## 2026-08-02：面试复盘 Task 8 候选审核、行动与发布界面

- 复盘详情新增“逐题复盘 / 准备资产 / 行动与发布”三个常驻入口；准备资产内部保留复习题、项目与画像、复盘总结三个常驻分组及服务端计数。
- 候选支持已有题匹配、新建题、画像/项目 Proposal、拒绝、显式勾选批量处理和失败原因；正式题关联后提供稳定“立即练习”链接。
- 行动项采用紧凑清单；发布区只允许选择安全章节，明确排除原始转写、待确认推断、聊天、Prompt 和模型原始响应，完成后可返回 Knowledge。
- 前端真实接入 Task 7 candidate/action/publication API；批量部分失败保留失败项。后端补齐空 action payload 下的合法项目建议默认值，并在更新时合并当前确认版本。
- 自动证据：Task 8 前端组件/页面聚焦 `12 passed`，后端候选聚焦 `6 passed`，TypeScript、Ruff、production build 与差异检查通过。
- 隔离浏览器验收：桌面端完成题库关联、行动完成、Knowledge 草稿生成；390px 下无页面横向溢出、行动/发布单列展示，浏览器控制台 error 为 0。验收使用虚构 API 数据，未调用真实 Provider。
- 下一步：Task 9 受限对话、纠正建议确认与局部重算。

## 2026-08-02：面试复盘 Task 9 受限讨论与纠正重算

- 新增七个精确只读复盘 Tool，统一限制当前 Workspace/复盘、最多 20 项和单段 2,000 字；Tool schema 不接受 Workspace、复盘 ID 或任意文件路径。
- 对话输出严格区分普通解释与四类纠正建议。解释只追加用户/助手消息；纠正建议保存来源 Cleanup/Analysis、目标问题、服务端实际 before、模型建议 after 和 expected version，确认前不修改业务数据。
- 问题文字、片段归属和分析重判确认后创建局部 AnalysisRun，只重算目标问题与三个 finalizer，并复制其他题的正式分析；说话人纠正创建新 CleanupVersion 后全量重算。拒绝不创建版本。
- 新增次级“讨论与纠正”抽屉，不替换当前报告/问题选择；复用共享 AgentComposer 的 IME 键盘、停止和失败重试体验，纠正卡以可读 before/after 提供明确确认与拒绝动作，390px 使用全屏单列。
- 自动证据：复盘后端全组 `63 passed`；Task 9 核心后端 `9 passed`；前端讨论/工作台 `4 passed`，TypeScript、Ruff、production build 与差异检查通过。整套前端并发回归中新增用例全部通过，两个既有设置页因并发超时，随后单独复验 `5 passed`。
- 产品成熟度：受限追问、显式纠正和局部重算链路可用；求职目标聚合、原文清除/删除影响、完整真实页面验收和最终用户指南留给 Task 10。
- 下一步：Task 10 聚合、生命周期收口、完整浏览器验收与阶段文档门禁。

## 2026-08-02：面试复盘 Task 10 与首版阶段收口

- 求职目标总览新增面试反馈聚合：复盘场次、最近轮次/结果、未完成行动项和 gap 类型数量，支持目标深链返回复盘工作台。
- 复盘工作台补齐原文清除、归档、回收、恢复、删除影响和永久删除；原文清除后保留结构化结论/外部资产并阻止重新分析，永久删除要求精确确认文字。
- 浏览器验收覆盖隔离工作区创建、模型未配置的部分成功、目标聚合、归档/恢复、回收站、删除影响、原文清除和 390px 布局。验收发现并修复“已保存却留在创建弹窗”及 `/cleanup-runs/null` 两个真实缺陷。
- 自动证据：完整后端 `1081 passed`；复盘后端全组 `65 passed`；Task 10 后端聚焦 `6 passed`，API 增量 `1 passed`；前端聚焦最终 `27 passed`，TypeScript 与 production build 通过，Ruff 与差异检查通过。
- 产品成熟度：首版跨层功能和确定性状态边界已完成；真实 Provider 的提取/分析内容质量、极长转写和不同模型波动仍需用户样本校准。
- 所有权状态：`stateful` 七件套与最终人工验证指南已生成；用户学习与练习均为非阻塞理解债务。
- 下一产品任务：用户按验证指南做一次真实 Provider 手工验收，再决定进入模拟面试 Agent 或继续校准复盘体验。

## 2026-08-02：岗位专项复习串联合入面试复盘分支

- 将 `feature/review-agent-workspace` 本地合入 `codex/interview-retrospective-agent-v2`，保留岗位/项目范围选题、画像到求职目标的返回链路和专项复习入口。
- 求职目标总览同时保留新版四步准备路径与面试反馈聚合，不以其中一条用户旅程覆盖另一条；导航同时支持项目题确认、岗位专项复习和岗位复盘。
- 合并冲突集中在总览组件、页面接线、样式与增量记录；后端范围契约和复盘领域保持各自边界，没有修改已有复盘状态机。
- 合并验证：前端 TypeScript 通过，交界面组件测试 `42 passed`；后端岗位范围选题、复习 API 与复盘聚合测试 `101 passed`；首次前端合并回归暴露 1 个仅由新增步骤编号引起的测试选择器歧义，收紧到“面试反馈”区域后通过。

## 2026-08-02：面试复盘整理运行可见性与失败反馈

- 复盘整理/分析统一使用规范 Agent graph ID，运行中心和质量评估继续兼容历史 `.analysis` / `.chat` 运行；业务复盘即使使用内部 Session，也不再被“系统 Agent”筛选隐藏。
- Cleanup API 新增窗口完成进度、当前工作项、稳定错误码和已完成窗口的只读部分结果；页面在运行和失败状态下显示真实进度、友好错误、保留结果及明确重试入口。
- 单窗口上限改为 6,000 字并保留 500 字上下文重叠。没有任何完成成果的历史失败任务重试时自动重排，已有部分成果则原样保留并只重试未完成窗口。
- 定向验证：后端运行中心、Cleanup 与复盘 API `20 passed`；前端工作台/页面 `11 passed`；Ruff、TypeScript 和差异检查通过。

## 2026-08-02：面试复盘长文本 Cleanup 调度

- 初始窗口改为自然边界优先、最多 4,000 字和 400 字重叠；重叠区通过 `emitFrom` 仅提供上下文，不允许重复输出。
- 首个成功窗口生成最多 8 个说话人提示，后续窗口并发上限为 2；窗口输出逐项持久化，最终正式片段仍按绝对 offset 单线程归并。
- Cleanup 使用 8,192 输出 Token、120 秒单次超时和 0 次 SDK 隐式重试；每个工作项最多应用层尝试 2 次，超时且大于 2,500 字的窗口自动原子拆分。
- 单窗耗尽重试后不再阻塞后续窗口；页面展示活动窗口、已保存数量、待重试窗口和部分结果。
- 收口验证：受影响后端回归 `104 passed`，前端复盘工作台/页面 `11 passed`，TypeScript、production build、Ruff 和差异检查均通过；构建只有既有大 chunk 警告。真实 Provider 合成长文本验收会产生外部模型调用，保留为经用户明确同意后执行的人工验证项。
- 浏览器最小验收尝试使用 `/tmp` 隔离数据启动 8003/5176 服务，服务本身启动成功，但浏览器控制的 localhost URL 安全策略拒绝页面 reload；未绕过策略，临时服务已停止，阶段文档门禁因此保持未关闭。

## 2026-08-02：面试复盘长文本问题提取

- migration 048 为源版本增加录音覆盖范围；创建页可声明双方对话、主要只有本人或混合不确定，事后回忆固定为混合不确定。
- 确认段落按最多 12,000 字与 4 段重叠规划 `question_extraction:<first>:<last>`，两个窗口并发执行，每窗显式 120 秒边界与两次应用尝试。
- 超时多段窗口原子替换为持久化子窗口；已完成输出可停止、刷新和恢复。`question_reduce` 在所有 Map 完成前保持 blocked，不产生部分正式题目。
- `anchorSegmentId` 区分原话问题与根据回答推断的问题；同锚点合并证据，不同锚点保留重复出现，跨窗承接只接受结构化 `continues_previous`。
- 前端显示分段识别窗口进度、合并阶段以及“原始问题 / 推断题”标签。前端组件 `34 passed`、production build 和 Ruff 通过；后端完整回归 `1113 passed, 1 warning`，差异检查通过。
- 隔离浏览器验收覆盖三种录音范围、“事后回忆”隐藏录音范围、分段进度 `1 / 2`、刷新保持、完成态“原始问题 / 推断题”以及 390px 无横向溢出；验收数据为本地合成持久化数据，未调用真实 Provider。

## 2026-08-02：面试复盘转写修订与运行反馈

- migration 049 新增 Cleanup CorrectionRecord；Agent 同窗输出段落与修订，Reducer 按绝对 offset 校验原文、去重并把冲突升级为高风险。
- Cleanup 页面支持低风险已修订提示、高风险接受/保留/手动处理、确认门禁、真实窗口进度、持续时间、最近保存和长任务说明；刷新后继续使用服务端时间。
- 分析与导出链路读取确认后的 SegmentRecord.body；分析工作区新增“已修订 N 处”原文对照。整段手工正文优先于同批旧修订决定，模型记录保留为 superseded 审计历史。
- 运行中心结构化模型响应改为中性正文表面；对象数组使用普通矩形字段块，基础值数组保留紧凑标签，修复绿色背景叠加巨大白色圆形。
- 新鲜验证：复盘后端 `90 passed`；复盘前端与运行详情 `45 passed`；Ruff 和 production build 通过，构建仅有既有大 chunk 警告。隔离浏览器无 Workspace，未制造数据或调用 Provider；真实长录音与修订视觉仍待功能工作区人工验收。
- 实页发现 103 KB 模型响应的 64 KB 分页被呈现为“半截 JSON + 整行蓝色加载条”。现改为 200 KB 以内自动取完所有分页再解析；超大正文的手动入口收敛为带加载字节进度的次级按钮。

## 2026-08-02：Cleanup 稳定原文单元与有界输出修复

- 根据真实 Provider Trace 增补 ADR：4,000 字窗口的完整段落 + 修订审计输出会逼近 8,192 Token，且模型 offset 在完整响应中仍不可靠，因此不采用“只加 Token”作为正确性方案。
- 后端把每窗原文切成最多 800 字的稳定 Source Unit；模型只返回 emit 单元的 ID、说话人和修订稿，程序用不可变原文 Diff 生成精确 CorrectionRecord。
- 数字、否定、时间和无法唯一确认的修改由程序保守标为高风险；只有格式变化和完全命中当前术语提示的识别修订自动采用。
- Cleanup 的 `ToolStrategy` 关闭内部错误回灌；`max_tokens`、缺失结构、错误单元 ID 分别归类为稳定错误，超时/截断/Schema 错误只拆分当前窗口。
- 新鲜证据：复盘及可观测受影响后端 `109 passed`；完整后端 `1136 passed, 1 warning`；全量 Ruff 与 `git diff --check` 通过。真实 Provider 中长样本尚未复跑，保留为用户环境人工验收边界。

## 2026-08-02：高级运行详情实时刷新

- 高级运行详情在执行状态为 `queued` / `running` 时每秒刷新执行摘要、Operation 与事件索引；进入终态后补一次收尾刷新并停止轮询。
- 模型结构化响应仍保持完整返回后原子展示，不把流式残片当成可读 JSON；运行中的总耗时按开始时间持续更新。
- 定向验证：`ExecutionTracePage.test.tsx` 13 项通过，新增用例覆盖响应自动出现；TypeScript 类型检查通过。

## 2026-08-02：转写修订待办规模收敛

- Cleanup Prompt 禁止润色、语序调整和口语替换；无法唯一确认时要求逐字保留原文。
- 程序不再把所有字符差异默认升级为高风险：格式和允许术语继续安全采用，数字/否定/时间等关键变化继续阻塞，普通改写直接保留原文且不生成审核项。
- 历史运行新增“全部保留原文并保存”批量兜底，更新命令的决定上限从 1,000 调整为 5,000，可处理当前 1,006 项数据。
- 新鲜验证：Cleanup/Agent/API 后端 `59 passed`；Cleanup 工作台与复盘页面前端 `14 passed`；Ruff、TypeScript 和 production build 通过，构建仅有既有大 chunk 警告。

## 2026-08-02：面试复盘对话轮次还原

- Cleanup 模型输出由“每个 Source Unit 一个说话人”升级为 `unitId + turns`，同一原文单元内可以按语义恢复面试官与候选人的连续轮次。
- 多轮次必须返回逐字 `sourceText`，程序验证顺序拼接与不可变原文完全一致并计算轮次 offset；遗漏、改写或换序会拒绝当前窗口。
- 单轮次省略 `sourceText` 并默认覆盖完整 Source Unit，避免每个窗口重复原文而重新触发输出 Token 截断。
- Cleanup Prompt 允许断句、口头赘词、紧邻重复和高置信 ASR/术语修正，同时保护数字、否定、组织名称和职责等级；不确定术语保留原文并说明原因。
- 候选人单边录音的缺失问题仍在问题提取阶段生成带回答证据的 `origin=inferred` 问题，不污染 CleanupVersion 原话证据。
- TDD 新增混合轮次恢复与原文覆盖拒绝用例；复盘后端回归 `105 passed`，Ruff 与差异检查通过。

## 2026-08-02：高级运行详情实时耗时时区修复

- 运行态总耗时不再直接用 `Date.parse` 解析 SQLite 无时区 UTC 字符串，统一改用共享 `parseApiTimestamp`。
- 新增北京时间环境回归用例：开始时间 `2026-08-02 09:00:00`、当前时间 `09:00:23Z` 必须显示 `23 秒`，不能显示 `480:23`。
- 新鲜验证：`ExecutionTracePage.test.tsx` 14 项、TypeScript 与差异检查通过。
## 2026-08-02：复盘整理重复模型请求修复

- 核对真实 Execution `3b05eaed-318d-4c5a-a9eb-8a577df1b75d`：原实现共发出 18 次 Cleanup 请求并最终 `schema_validation_error`；确认存在父窗拆子窗的大范围重复和同窗原样重试。
- 模型契约允许程序确定性补齐 `displayName` 与按序缺失的 `unitId`；缺少可验证多轮边界时保留整个 Source Unit 为待确认单段，继续保护不可变原文范围。
- 调度器只对 `provider_timeout/output_truncated` 做自适应拆分；`schema_validation_error/structured_output_missing` 不再自动重试，首窗失败时快速终止。
- 显式继续会重置 retryable 窗口的尝试预算并保留 completed 窗口，现有失败运行可在新代码下继续未完成部分。
- 新鲜验证：完整复盘后端定向回归 `107 passed`；全量后端 Ruff 与差异检查通过。

## 2026-08-02：复盘整理核对页面收敛

- 顶部以“还需处理 N 项”建立唯一主任务，并拆分说话人、关键文字和自动整理数量。
- 段落队列显示具体待办类型；详情一次只展示一项关键修改，接受/保留后自动推进，手工修改保持显式保存。
- 低风险自动整理、更多段落设置、批量处理和复盘生命周期动作均收进次级入口；桌面段落队列收敛为 300–340px。
- 自动验证：复盘前端 `40 passed`，TypeScript、production build 与差异检查通过；构建仅有既有大 chunk 警告。

## 2026-08-02：复盘模型整理稿与审核门禁一致性修复

- 用真实 Provider 响应复现：逐 opcode 白名单会把模型已清理正文几乎全部静默恢复为原文，且 `corrections=[]`；现改为先做整轮有界检查，再自动采用普通 ASR 错字、口头语和断句修正。
- 数字、否定、时间和职责等级优先于普通识别修正，继续阻止确认；低相似度、异常长度和明显内容搬移显示模型稿并升级为整段高风险待确认。
- 多轮响应仅遗漏第一轮 `sourceText`、其余证据为不可变原文精确后缀时，可唯一恢复首段边界；其他缺失、错序和改写仍拒绝。
- 真实 Execution `2943dfa5-3b85-48d6-8796-a9699a5bfb25` 暴露 Provider 会同时省略首轮证据并格式化后续证据标点。现将模型 `sourceText` 降为轮次起点锚点，唯一定位后由程序从不可变原文重建正文和 offset；同一响应离线重放成功生成 8 段。
- 重试 Execution `24842e8a-f4d8-4348-8c3a-469b26c742ce` 进一步证明 Provider 会把后续 `sourceText` 整段写成清理稿。程序现只校验后续轮次起始内容锚点唯一性，正文安全继续由不可变原文切片和 `correctedText` 有界门禁承担；第二次真实响应也已离线重放为 8 段。
- 前端字段改称“模型整理稿”，直接对应 Provider `correctedText`；原文和人工决定留在下方核对区。
- 新鲜验证：复盘后端 Cleanup/Service/API `53 passed`、复盘前端 `40 passed`、Ruff、production build 与差异检查通过；构建仅有既有大 chunk 警告。

## 2026-08-02：复盘整理 Schema 漂移容错

- Source Unit 数量/ID 映射不再在 Agent 层直接终止任务；物化层按程序持有的 emit 单元确定性映射，缺失或未知项使用原文待确认兜底。
- 单轮输出忽略 Provider 自报的 `sourceText` 并覆盖完整不可变单元；多轮边界无法证明时合并为完整单段，保留角色不确定性而不是伪造 offset。
- 新增缺失单元、错误 ID、单轮错误证据和多轮不可覆盖的回归测试。
- 使用本次失败 Execution 的三组真实 Provider 响应完成离线回放，全部物化成功；后端复盘定向套件 `118 passed`，相关 Ruff 检查通过。
# 2026-08-02：复盘段落直接展示模型整理稿

- 审核段落正文直接保存并展示模型 `correctedText`；数字、否定、职责和大改写仍保留高风险确认门禁。
- pending 修订初始 adopted text 与模型稿一致；接受不改正文，保留原文或手工决定后再替换。
- 移除“查看模型响应”入口及 Trace 临时映射，页面只保留一份主正文。
- 自动验证：后端复盘定向回归 `119 passed`，前端复盘功能 `40 passed`，TypeScript 与 production build 通过。

## 2026-08-02：复盘准确转写文档设计重构

- 根据真实长转写验收结果，停止沿用“模型 turn 直接成为 Segment、每个 Diff 进入人工核对”的旧方案；现有自动测试只证明状态与兼容逻辑，不能证明产品质量达标。
- 重写 `docs/superpowers/specs/2026-08-02-interview-retrospective-transcript-correction-design.md`，新增旧方案局限、根因、成熟项目参考、单一文档 Artifact、稀疏 ReviewIssue、确认后 Anchor 和真实基线盲测要求。
- 参考来源明确限定为架构模式：DeerFlow 的 Artifact/受控上下文、LangGraph Map-Reduce、GraphRAG Document/Text Unit 分层、Haystack 文档预处理流水线；没有声称这些项目直接实现中文 ASR 纠错。
- 产品实现尚未按新设计修改。下一步先重写实施计划和受影响 ADR，再调整后端数据边界、Cleanup 合同、单文档页面与题目提取输入。

## 2026-08-02：准确转写单文档 Workflow 首轮实现

- 新增 `document_body/document_sha256` 与稀疏 `interview_transcript_review_issues`，新 Cleanup 不再在窗口完成时生成用户段落和逐字符 Correction。
- Cleanup 模型协议改为非重叠 `targetText` + 只读前后上下文，只返回 `correctedTarget` 与少量 `uncertainItems`；程序按目标范围顺序拼成一次且仅一次的完整文档。
- 增加整篇文档 PUT API。用户可直接编辑完整文字，并记录接受建议、保留当前文字或手工处理的决定；文档哈希与乐观锁由后端维护。
- 确认动作校验完整文档、摘要和 pending issue，并在同一事务内生成后续问题提取所需的自然段/有界长度证据锚点；旧 Cleanup 仍走历史 Segment 门禁。
- Cleanup 页面在新数据上只展示一份连续全文和右侧稀疏问题列表，不再展示窗口、Source Unit、Diff 或上千段卡片；旧数据路径保持兼容。
- 清除原文会同步清除准确转写全文、摘要和 ReviewIssue，并继续清除旧段落、Correction 与分析摘录。
- 新鲜自动验证：后端准确转写/分析相关 `148 passed`，隐私/删除/Trace 保留相关 `14 passed`；前端复盘 `41 passed`，TypeScript 与 production build 通过。真实 Provider 盲测和浏览器验收仍待完成。

## 2026-08-02：准确转写单文档最小浏览器验收

- 使用隔离临时工作区和非隐私短样本进入新 Cleanup 页面，页面只展示一份连续全文与 1 个稀疏术语问题，没有窗口、Source Unit、逐字符 Diff 或段落卡片队列。
- 点击“采用建议”后正文由“数字签明”更新为“数字签名”，“保存整理稿”由禁用变为可用；保存后待确认数从 1 变为 0，刷新后的服务端文档保持更新结果。
- 点击“确认并进入题目提取”后阶段切换为“整理结果已确认”，页面只显示下一步“开始分析”，证明文档保存、ReviewIssue 决定、确认门禁和锚点生成已贯通。
- 本次仅证明隔离数据下的最小 UI/API 闭环，不代替真实一小时转写的 Provider 质量盲测，也不覆盖停止、恢复、单窗口失败和 Trace 正文清除联动。

## 2026-08-03：准确转写核对栏比例修复

- 修复 1024 附近视口中通用 Cleanup 断点规则覆盖单文档布局的问题，完整正文恢复为主栏，待确认区收敛为约 36% 的辅助栏。
- 768–899px 改为上下布局；待确认项中的长原文预览限制为 240px 高并在内部滚动，避免大段文字抢占页面主体。
- 新鲜验证：Cleanup 与页面测试 `17 passed`，TypeScript 和 production build 通过；仅保留既有大 chunk 警告。
- 待确认区补充“待确认列表（N）”明确入口，列表固定保留 160–280px 可见高度；当前项详情改为剩余区域独立滚动，不再把 47 项列表压成空白边框。对应可访问标签与列表按钮测试已补充，同一组 `17 passed` 和 production build 再次通过。

## 2026-08-03：复盘核对页整体层级收敛

- 首轮只把单条“复盘记录”列表由 29% 收敛到 22%，在 5175 实页上仍保留了原有三栏的等权观感；复核后改为真正的窄导航：桌面 190–230px、1024px 附近 176–200px，并在所有桌面宽度移除重复记录图标、压缩单条高度。
- 页面标题、生命周期页签、记录标题、核对标题与底部动作区统一降低垂直密度；正文继续占主宽度，待确认区保持稳定辅助宽度，避免三块区域等权竞争。
- 5175 实页复核后确认 300–360px 的待确认栏不足以承担高频核对；改为桌面 420–520px、1024px 附近 330–380px，并把列表可见区从右栏高度的 42% 提高到 54%，详情继续使用剩余空间独立滚动。
- 新鲜验证：5175 进程工作目录确认是当前功能工作区；Cleanup 与页面测试 `17 passed`，TypeScript / production build 和差异检查通过，构建仅保留既有大 chunk 警告。隔离浏览器没有用户工作区数据，因此没有伪造带真实记录的浏览器截图。

## 2026-08-03：准确转写专注核对模式

- 使用 `ui-ux-pro-max` 按内容优先、渐进披露、避免嵌套同级导航和长文档可读宽度复审页面；确认问题根因是全局侧栏之外又常驻“复盘记录”主栏，而不是待确认栏少几十像素。
- 进入新式准确转写核对态后，页面切为专注模式：隐藏生命周期筛选和常驻复盘记录栏，顶部只保留当前复盘上下文、返回列表和次级管理入口。
- 主体重构为完整文字 + 待确认工作区两栏；待确认区约占 44%，其列表优先获得 58% 高度，899px 以下继续切为上下布局。
- 5175 Safari 实页确认专注模式已生效：常驻记录栏和生命周期筛选消失，顶部返回入口、当前复盘、管理菜单均可达；正文与待确认列表在首屏并列，右栏可同时浏览多条待办。
- 新鲜验证：页面与 Cleanup 测试 `18 passed`，TypeScript / production build 和差异检查通过；构建仅保留既有大 chunk 警告。

## 2026-08-03：准确转写单项校对台重构

- 再次使用 `ui-ux-pro-max` 复审后确认，长文、完整问题队列和单项详情同时常驻会造成认知过载；页面从“三块信息并排”重构为“正文 + 当前一项”的单任务校对台。
- 完整文字改为居中的文档纸张表面并限制可读行长；右侧只显示当前问题的类型、当前文字、模型建议、原因和决定动作，处理后按原顺序自动推进。
- 48 项完整队列收进“全部问题”渐进入口；新增处理进度、上一个/下一个和“在全文定位”，移动端队列使用覆盖层而不是继续压缩正文。
- 5175 Safari 真实开发工作区已复验专注态：常驻记录栏消失，正文和当前第 1/48 项在首屏并列，所有主动作可达。
- 新鲜验证：Cleanup 与页面测试 `18 passed`，production build、差异检查通过；构建仅保留既有大 chunk 警告。

## 2026-08-03：模型候选词与可执行建议语义修复

- 定位到后端在不确定项无法唯一匹配时，会把整个文本窗口作为 `excerpt`，却继续保留短 `suggestion`；前端因此可能把整段文字替换成一个候选词。
- 新生成的歧义项现在只保存核对上下文，并把候选词写进原因说明，不再产生可自动采用的建议。
- 前端兼容已有数据：歧义旧记录改称“模型标记的候选词”，明确提示无法自动定位，并隐藏采用按钮；唯一定位的修改则统一显示“原词 → 建议词”。
- 新鲜验证：后端 Cleanup `38 passed`，复盘前端 `19 passed`，production build 与差异检查通过；5175 实页确认旧记录候选线索可见且不存在采用按钮。

## 2026-08-03：普通候选词误报过滤与历史门禁迁移

- 将 Provider 的低置信度诊断与用户待办彻底分离：术语项必须同时满足“原词在整理稿中唯一定位、建议词与原词不同、存在具体替代词”才会生成 ReviewIssue；普通技术词、同值建议和无法定位的候选不再阻塞用户。
- 说话人或关键语义确实不确定且能精确定位时仍保留人工核对，避免为了减少数量而吞掉真正影响复盘事实的问题；完整原始模型响应继续保存在 Agent 运行中心供诊断。
- Prompt 将不确定项上限收敛为每窗口 8 项，并明确禁止输出普通词表；运行时迁移 051 把已有歧义候选、无替代词和同值替代的 pending 记录标记为 `kept`，保留审计记录但解除确认门禁。
- 新鲜验证：Cleanup、Agent Prompt 与运行时迁移定向回归 `108 passed`，Ruff 通过；5175 真实开发数据刷新后由“待确认 48”变为“整篇文字已可确认 / 已处理 48/48”。

## 2026-08-03：运行中心暂停/取消快捷筛选

- 将已有但隐藏在高级筛选中的 `interrupted + cancelled` 组合状态提升到任务列表顶部，新增“已暂停/取消”快捷标签与实时数量。
- 点击标签只展示暂停或取消的 Execution，其他状态标签保持可见，筛选仍通过既有 `stopped` URL 状态复用统一逻辑。
- 新鲜验证：`AgentRunCenterPage` 15 项测试和 TypeScript 检查通过；5175 真实开发数据显示“已暂停/取消 3”，点击后准确列出 1 条暂停和 2 条取消任务。

## 2026-08-03：复盘问题提取最小上下文与有界 Schema 修复

- 问题提取请求删除共享 `contextSnapshot`，只发送当前转写窗口、录音覆盖范围和 `transcript_only` 声明；逐题分析仍保留其独立冻结上下文。
- 新增模型侧 `QuestionExtractionModelOutput`，Provider 不再负责 `ordinal` 和 `anchorSegmentId`；程序按返回顺序与首个问题/回答证据确定性物化完整领域合同。
- 关闭问题提取 ToolStrategy 的隐式错误回灌；首次 Schema 错误只发送无效候选、800 字内校验摘要及最多 12 个已引用证据片段进行一次修复，修复再次失败后不再重发完整窗口。
- 应用层将 Schema 缺失标为不可自动重试错误；窗口保持 retryable 供用户显式恢复，其他已完成窗口不丢失。
- 新鲜定向验证：Agent 合同、窗口 Reduce、分析状态机和 API 共 `58 passed`；受影响文件 Ruff 通过。

## 2026-08-03：复盘逐题分析超时隔离与恢复

- 为 `interview_retrospective_question_analysis` 增加显式调用策略：`max_output_tokens=4096`、`request_timeout_seconds=120`、`max_retries=0`。
- `render_question_analysis_input` 不再透传完整冻结上下文；岗位仅保留 ID、公司、职位、职级，画像通过当前题目与证据段检索，最多 6 条、单条 2,400 字符、总计 8,000 字符。
- 分析调度器将瞬时错误限制在当前问题工作项内：每题最多自动尝试 2 次；失败项延后，其他题优先推进；恢复同一运行时只执行 retryable/pending 项及后续汇总。
- 前端“重试失败步骤”由创建新重试运行改为调用 `resumeAnalysis`，保留原运行的提取结果与已完成逐题分析。
- RED 证据：上下文测试曾发现完整岗位文档和无关画像仍被发送；隔离测试曾只调用失败题一次；页面测试曾调用 `retryAnalysis`。
- GREEN 证据：后端复盘 Agent/Analysis/API `56 passed`；前端 `InterviewRetrospectivePage` `9 passed`；受影响 Ruff 与 `git diff --check` 通过。
- 新增独立 Tradeoff ADR：`docs/superpowers/architecture-decisions/2026-08-03-retrospective-question-analysis-context-and-retry-boundary.md`，记录真实故障、备选方案、采用边界、代价、重新评估条件和面试讲述口径。

## 2026-08-03：复盘分析页专注阅读布局

- 从复盘列表选择记录后统一进入专注阅读态：隐藏外层复盘记录栏，顶部提供明确的“复盘列表”返回入口，避免同一条记录在内外两层重复出现。
- 完成状态收敛为单行摘要，移除已经完成后的满宽进度条；问题列表合并重复状态标签，原始题不再额外展示“原始问题”，仅保留有辨识价值的“推断题”。
- 桌面问题列表固定在约 300–340px，详情区使用剩余宽度；1024px 仍保持双栏，899px 以下才切换上下布局。内部推断依据转换为用户语言，不再直接显示 `recordingCoverage` 等协议字段。
- 新鲜验证：相关复盘前端测试 `18 passed`，production build 通过；5175 真实开发数据在 1280×720 与 1024×768 完成浏览器复验，专注态、首屏内容密度和返回列表路径均符合预期。

## 2026-08-03：逐题复盘信息层级重构

- 修正前一轮只压缩外层布局、没有解决逐题详情“调试报告式堆叠”的偏差：回答原文、全部分析、遗漏、差距和参考表达不再同时占据默认首屏。
- 默认阅读路径改为“题目与推断确认 → 值得保留 / 优先改进 → 推荐回答结构”；完整分析、回答原文和参考表达分别通过原生 `details` 渐进展开，键盘焦点和完整内容仍保留。
- 问题列表将“推断题”和分析结论合并为单行状态；焦点态移除重复的内层复盘标题，把“讨论与纠正”并入页签导航，减少一整行无效页面框架。
- 新鲜验证：逐题详情、问题列表、工作区和页面测试 `15 passed`，production build 与差异检查通过；5175 真实数据在 1280×720 和 1024×768 复验，1024 下结论卡切为单列，折叠原文可正常展开。
