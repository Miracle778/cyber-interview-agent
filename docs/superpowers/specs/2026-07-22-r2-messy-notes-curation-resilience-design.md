# R2 随手记题目整理韧性设计

- 状态：已确认
- 日期：2026-07-22
- 适用范围：R2 题目整理；R3 及后续材料型 Agent 可复用同一 Provider/领域边界
- 关联设计：`2026-07-22-r2-curation-long-task-control-and-performance-design.md`
- 关联实现：`backend/app/review/curation_planner.py`、`backend/app/graphs/question_curation.py`

## 1. 背景

用户用于整理题目的资料大量来自随手记，而不是结构完整的题库文档。常见输入只有关键词、项目符号、TODO、代码、日志、半句结论或未完成的问题，不能要求材料天然满足“题干、答案、分类、难度、关键点、引用”完整结构。

真实 GLM 运行连续暴露了严格 Provider 契约的脆弱性：

1. discovery 单个 seed 缺少 `source_ref` 并含 null 引用；
2. discovery 返回 21 项，超过 20 项上限；
3. discovery 主引用没有排在 `source_refs` 首位；
4. enrichment 候选缺少 `title/topics`；
5. enrichment 候选少回一个合法种子引用。

局部 normalizer 已能处理这些已观察偏差，但当前恢复单位仍是每三个种子一个 enrichment Work Item，核心字段缺失时可能静默丢弃候选，单条内容异常仍会让 Batch 进入 failed。该行为不适合非规范、信息不完整的真实笔记。

本设计把容错从“修几个缺字段”提升为完整边界：原文覆盖、Provider 宽松解析、单种子状态、确定性归一化、一次单题降级重试、质量与答案来源标记、严格发布门禁。

## 2. 目标

- 关键词、碎片、问题、答案、代码和日志混排的资料都进入可解释处理路径；
- 一个候选异常不丢弃同组其他候选，也不让整个 Batch 失败；
- 以单个题目种子作为内容恢复边界，同时保持每次最多三个种子的批量模型调用；
- 材料不完整时允许 AI 补全，但明确展示答案来源、材料支持度和复核要求；
- 内容质量问题可降级完成，基础设施、安全和持久化问题才进入 Batch failed；
- 现有 Batch、completed Work Item、候选和 Trace 全部保留，不从零重跑；
- 整理契约可以宽松，确认入库和发布契约必须严格。

## 3. 非目标

- 不引入自由 ReAct、自主循环或模型决定重试次数；
- 不引入分布式队列、通用工作流引擎或 Time Travel；
- 不把 OCR、图片理解、浏览器抓取或任意 URL 摄入纳入本增量；
- 不保证模型补充答案绝对正确，产品通过来源标记、复核和发布门禁管理不确定性；
- 不允许模型新增、替换或扩大应用拥有的 Evidence 引用；
- 不自动发布任何正常、降级或 AI 补全候选。

## 4. 设计原则

1. **原文覆盖优先**：每个可提取片段必须进入 deterministic range、model discovery window 或来源级警告。
2. **Provider 输出不是领域事实**：Provider contract 只负责接住常见形状偏差；normalizer 后的领域对象才可持久化为候选事实。
3. **证据由应用拥有**：模型只返回关联线索，最终 `source_refs` 始终从已持久化种子复制。
4. **内容问题局部化**：缺字段、少候选和无法关联只影响对应 seed task。
5. **不伪造核心内容**：程序可以补展示元数据，不能编造答案、关键点或证据。
6. **有界重试**：首次批量调用后，每个异常 seed 最多自动进行一次单题降级重试。
7. **宽进严出**：整理草稿允许待补充；发布必须通过严格完整性、Evidence 和 HITL 校验。

## 5. 状态所有权

| 对象 | 所有权 |
|---|---|
| Source Section | 稳定原文片段、摘要和来源引用 |
| Discovery Work Item | 一次 deterministic/model discovery 输入与不可变输出 |
| Seed Task | 单题 enrichment 状态、尝试次数、质量、候选或跳过原因 |
| Provider Invocation | 一次最多三个 Seed Task 的模型调用；不拥有领域终态 |
| Question Batch | 整体暂停、恢复、终止、基础设施失败和最终审核阶段 |
| Question Candidate | 可编辑整理草稿；可包含降级与 AI 补全标记 |
| Publication/HITL | 严格入库与发布门禁 |
| 前端 | 展示、筛选和用户显式重试，不拥有正式状态 |

## 6. 非规范材料摄入

### 6.1 来源提取结果

每份来源先得到一种安全结果：

- `usable`：提取到非空文本；
- `low_signal`：只有极少非空字符或重复噪声；
- `no_extractable_text`：PDF 无文本层或提取为空；
- `unsupported_encoding`：文本无法按支持的编码读取；
- `parse_failed`：解析器失败且只暴露安全错误码。

只要至少一个来源 usable，Batch 继续处理，其余来源写入 warning。全部来源不可用时 Batch 正常完成并显示逐来源原因，不显示 Agent 执行失败。

### 6.2 Section 与 discovery

现有稳定 section、2,000 字符硬上限、约 6,000 字符 model window 和 exactly-once coverage 继续保留。确定性规则只识别强题目边界：明确问号、问题型标题和可靠编号问题。

以下内容不强行解释为完整题目，而是进入 model discovery：

- 关键词和项目符号；
- 只有答案或结论的段落；
- 普通主题标题；
- TODO、待研究项和半句疑问；
- 混合代码、日志与说明；
- 无换行长文本的稳定硬分片。

代码围栏中的问题型注释可以成为候选，但必须保留围栏和相邻解释的 source refs。答案列表、步骤编号和声明性编号继续避免误判为独立题目。

### 6.3 低信息量发现

Discovery 允许从主题或结论生成“值得复习的问题种子”，但不能生成答案。模型返回空 seed 是合法结果；应用记录覆盖完成而不是把空结果当异常。

## 7. 稳定 Seed 身份与关联

每个 discovery 输出在持久化后生成稳定 `seed_key`：

```text
sha256(batch_id + discovery_work_item_id + seed_ordinal + primary_source_ref)
```

同一 Batch 恢复时 seed_key 不变。Enrichment prompt 同时提供 seed_key、题干和权威 source refs，并要求 Provider 回显 seed_key。

候选关联按以下顺序执行：

1. 精确合法的 seed_key；
2. 唯一匹配的种子主引用；
3. 唯一匹配的规范化题干；
4. 无法唯一关联则进入 retryable，不使用数组位置猜测。

Provider 返回的引用只用于校验关联。最终候选引用由应用从 Seed Task 复制。Provider 混入未知引用、其他 seed 引用或跨来源引用时，该候选 hard reject 并进入单题降级重试；不得把错误引用带入领域对象。

## 8. Provider Contract 与领域 Contract

### 8.1 宽松 Provider Observation

Discovery 和 enrichment 的 Provider model 允许：

- 可选字段、null 和额外字段；
- `string | list[string]` 的 topics、key_points、follow_ups、source_refs；
- 中文、英文或缺失 difficulty；
- 超过响应上限的数组，由应用稳定截断；
- 缺失 seed_key，但仍可通过合法主引用或唯一题干关联。

Provider model 不直接作为 checkpoint、candidate 或 publication contract。

### 8.2 可编辑候选草稿

整理阶段候选允许以下内容为空：

- topics；
- key_points；
- follow_ups；
- reference_answer（仅待补充状态）。

草稿必须始终有 seed_key、question_text、权威 source_refs、质量状态和 review 标记。缺失核心内容的草稿不能确认发布。

### 8.3 严格发布候选

确认入库前必须满足：

- 非空 title、question_text、reference_answer、topics 和 key_points；
- difficulty 为 easy/medium/hard；
- source refs 属于同一合法 seed/source 边界；
- AI 主要补全内容已经用户确认；
- 当前 draft version/hash 与审批输入一致。

## 9. 确定性归一化矩阵

| Provider 偏差 | 处理 | 质量影响 |
|---|---|---|
| question_text 缺失 | 使用 Seed Task 题干 | degraded |
| title 缺失 | 使用 question_text | degraded |
| topics 缺失 | 使用“未分类” | degraded |
| difficulty 中文/别名 | 映射到三档 | 记录 issue |
| difficulty 缺失/未知 | 默认 medium | degraded、需复核 |
| 字符串代替数组 | 转为单项数组 | 记录 issue |
| null、空白、重复列表项 | 删除和稳定去重 | 记录 issue |
| follow_ups 缺失 | 使用空列表 | 不阻断 |
| correction_note 缺失 | 使用中性说明 | 记录 issue |
| source refs 缺失但 seed_key 合法 | 从 Seed Task 恢复 | 记录 issue |
| source refs 少项或顺序错误 | 从 Seed Task 恢复 | 记录 issue |
| 候选超过三个 | 稳定保留前三个已关联候选 | warning |
| 同一 seed 返回多个候选 | 稳定保留第一个完整候选 | degraded、记录重复 |
| 本次少返回某个 seed | 只把缺失 seed 标记 retryable | 不影响同组成功项 |
| 返回不属于本次请求的 seed | hard reject 多余候选 | warning |
| answer/key_points 缺失 | 不伪造，进入单题降级重试 | retryable |
| 未知/跨 seed 引用 | hard reject 当前候选 | retryable |
| 无法唯一关联 seed | 不使用位置猜测 | retryable |

## 10. 答案来源与材料支持度

Enrichment Provider observation 将答案拆分为：

- `source_answer`：模型判断可由当前材料直接支持的部分；
- `supplemental_answer`：模型使用通用知识补充的部分。

应用组合为 reference answer，并持久化：

- `answer_basis = source | mixed | model | unknown`；
- `material_support = sufficient | partial | minimal | unknown`；
- `needs_review`；
- `normalization_issues[]`。

规则：

- 只有 source_answer：source；
- source_answer 与 supplemental_answer 均有：mixed；
- 只有 supplemental_answer：model；
- 旧候选或 Provider 未声明：unknown，并强制 needs_review；
- mixed、model、unknown 均不得未经用户显式确认进入发布。

这些字段表示生成过程与复核要求，不宣称程序已经对答案语义正确性完成事实验证。

## 11. 单 Seed Task 状态机

```text
pending
  └─ batch enrichment call → running
       ├─ strict candidate ready → completed
       ├─ safe normalization used → degraded
       ├─ unresolved/critical missing → retryable
       └─ transport interruption → interrupted

retryable
  └─ one-seed fallback call → running
       ├─ strict candidate ready → completed
       ├─ safe normalization used → degraded
       └─ still unusable → skipped

interrupted → pending on explicit Batch resume
skipped → pending only on explicit user retry
```

completed、degraded 和 skipped 是自动运行终态。每个 Seed Task 最多两次自动模型调用。用户显式重试 skipped 时创建新的单次尝试 receipt，不启动自主循环。

## 12. 调度与部分成功

初次 enrichment 选择最多九个 pending Seed Task，组成最多三个 Provider 调用，每个调用最多三个 seed；活动 Provider 请求仍不超过 Batch concurrency limit。

一次调用返回后逐 seed 提交结果：

- 正常/降级候选立即持久化；
- 缺失候选只影响对应 seed；
- 同组其他成功 seed 不回滚；
- retryable seed 在后续波次按单题调用；
- completed/degraded 永不自动重放。

顶层结构错误、截断 JSON 或空响应无法拆出逐题结果时，只把本次调用包含的 seed 标记 retryable；其他并发调用已经提交的结果继续保留。单题降级调用仍无法解析时对应 seed 进入 skipped，不把内容格式问题升级为 Batch failed。

传输错误仍使用现有一次 client retry；429/过载降低后续并发到 1。进程中断把 running Seed Task 归为 interrupted，Batch 显式恢复后继续。

## 13. Batch 终态和错误边界

内容质量问题不再把 Batch 置为 failed：

- 至少一个 completed/degraded 候选：Batch 进入 review_pending，并携带质量汇总；
- 全部 seed skipped 或没有 seed：Batch 正常 completed，并携带逐来源/逐 seed 原因；
- skipped 不阻止用户查看、编辑和确认其他候选。

以下情况才允许 Batch failed：

- Provider 整体不可连接且传输重试耗尽；
- 数据库或文件读取事务失败；
- 应用拥有的持久 Evidence/Seed 数据损坏；
- 路径越权、workspace 越界或其他安全错误；
- 状态机不变量冲突且无法安全对账。

Provider 自己生成未知引用属于单候选不可信输出：hard reject 该候选并降级重试；只有应用已持久化的权威引用本身损坏才升级为 Batch 安全失败。

## 14. 持久化与旧数据升级

新增 additive `review_curation_seed_tasks`，至少保存：

- id、batch_id、seed_key、seed_ordinal；
- question_text、primary_source_ref、source_refs_json、input_digest；
- status、automatic_attempt_count、manual_attempt_count；
- candidate_json、answer_basis、material_support、needs_review；
- normalization_issues_json、last_error_code；
- optimistic version、created_at、updated_at。

唯一约束为 `(batch_id, seed_key)`，完成输出不可变；显式用户修订通过现有 Candidate/Draft 版本链完成，不覆盖 Seed Task 审计输出。

旧 Batch 恢复时执行幂等 reconciliation：

1. 从 completed discovery Work Item 生成 Seed Task；
2. 按候选主引用把 completed enrichment 输出回填到对应 Seed Task；
3. 旧候选标记 answer_basis/material_support unknown、needs_review true；
4. 旧 failed/pending enrichment 单元只产生尚未完成的 pending Seed Task；
5. 旧 Work Item、输出和 JSONL 不删除、不重写；
6. reducer 优先读取 Seed Task，升级前 completed 输出不得重复计入。

当前 Batch `907129b5-0a8c-47cb-b8a0-be42b73459a9` 的 80/80 discovery 与 22 个 completed enrichment 输出必须通过该 reconciliation 保留，不得重新调用对应模型。

## 15. Revision 与发布

`question.revise` 复用同一宽松 Provider observation、确定性 normalizer、答案来源和质量字段。Revision 只处理一个已知 candidate/seed，Evidence 由原候选和来源关系决定，模型不能新增引用。

整理页面可以保存待补充草稿。确认入库、更新入库版和知识发布统一调用严格 validator；validator 返回逐字段错误和 AI 补全确认要求，不把宽松 Provider 模型暴露到发布边界。

## 16. API 与页面投影

`CurationSessionResource` 增加 seed 质量进度：

```text
seedProgress.total/completed/degraded/retrying/skipped/pending
qualitySummary.source/mixed/model/unknown/needsReview
sourceWarnings[]
```

候选资源增加 answerBasis、materialSupport、needsReview 和 normalizationIssues。安全 SSE 只传 ID、状态、计数和错误码，不传原文、答案或 Provider 响应。

显式单题重试接口：

```http
POST /api/review/curation-sessions/{sessionId}/seed-tasks/{seedTaskId}/retry
Idempotency-Key: <required>

{"expectedVersion": 3}
```

接口只接受 skipped/retryable，创建一次新的 Execution attempt 并返回 `202` receipt；重复 key 返回原 receipt，不允许客户端指定题干、引用或模型输出。`curation.seed.changed` Event 只包含 sessionId、batchId、seedTaskId、status、attemptCount、quality flags 和 errorCode。

页面语义：

- 正常完成使用主色/成功色；
- AI 补全、待复核、待补充使用黄色 warning；
- 正在单题重试显示独立阶段；
- skipped 可查看原因、编辑或显式单题重试；
- 红色只用于真实 Batch/Execution failure；
- 支持筛选“主要由 AI 补全”“材料支持不足”“待补充”。

## 17. 方案比较

### 方案 A：单 Seed Task + 批量调用（采用）

恢复和质量边界精确，保留最多三题一调用的性能，能对随手记做部分成功与可解释降级。代价是新增持久化、迁移和 UI 质量投影。

### 方案 B：继续以三候选 Chunk 为恢复单位

改动小，但一题错误仍可能影响同组，无法精确重试，也会静默漏掉核心字段不完整的 seed，不采用。

### 方案 C：增加模型 JSON 修复 Agent

实现直观，但增加成本、延迟和不可预测循环，用模型修模型不能替代确定性边界，不采用。单题降级调用只用于补充内容，不是自由修 JSON Agent。

## 18. 测试矩阵

### 18.1 材料

- 关键词/项目符号；
- 有问题无答案、有答案无问题；
- 标题、编号、TODO、代码块、日志混排；
- 多主题同段、超长无换行；
- 空白、低信号、PDF 无文本；
- 多来源重复或冲突。

### 18.2 Provider

- 缺字段、null、空字符串、额外字段；
- 字符串代替数组；
- 中文/未知 difficulty；
- 超量、少候选、乱序；
- 缺 seed_key、缺主引用、引用顺序错误；
- 未知/跨 seed 引用；
- 一坏两好、顶层结构错误、截断/空响应；
- 429、5xx、超时、进程中断。

### 18.3 状态与安全

- 一题异常不失败 Batch；
- 正常候选立即提交，只重试异常 seed；
- 每 seed 最多两次自动调用；
- 暂停/刷新/重启不重放 completed/degraded；
- 旧 22 个 enrichment 结果升级保留；
- 全 skipped 正常结束并展示原因；
- Provider 未知引用不能进入领域候选；
- AI 补全未确认不能发布；
- 宽松整理契约不能绕过严格 publication validator。

### 18.4 浏览器与真实 Provider

使用一份脱敏混合随手记完成桌面和 390px 验收：部分成功、单题降级重试、暂停/刷新/恢复、质量筛选、待补充编辑和严格发布提示。真实 Provider 只在用户对具体材料明确触发时运行，证据记录模型/Execution/Work Item/Seed Task ID、计数、耗时和安全错误码，不复制原文或答案。

## 19. 成熟度边界

本设计交付的是单进程 bounded scheduler、SQLite Seed Task 恢复和可解释质量门禁，不是分布式队列或事实验证系统。AI 补全答案仍需用户审核；后续如需自动事实核验，应新增独立 evidence verification 阶段，而不能把 Provider 自报 confidence 当作已验证事实。
