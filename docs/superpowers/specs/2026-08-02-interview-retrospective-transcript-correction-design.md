# 面试复盘准确转写文档与题目提取前置流程设计

日期：2026-08-02

状态：Accepted（2026-08-02 修订，取代“模型分段即业务段落、逐条 Diff 核对”的旧方案）

关联设计：

- `docs/superpowers/specs/2026-08-01-interview-retrospective-agent-design.md`
- `docs/superpowers/plans/2026-08-02-interview-retrospective-segmented-question-extraction.md`
- `docs/superpowers/architecture-decisions/2026-08-01-interview-retrospective-versioned-evidence-and-cross-domain-boundaries.md`
- `docs/superpowers/architecture-decisions/2026-08-02-interview-retrospective-corrected-transcript-evidence-boundary.md`
- `docs/superpowers/architecture-decisions/2026-08-02-retrospective-cleanup-grounded-unit-output.md`

## 1. 用户目标与问题背景

用户提交的是一份手机录音转写或事后回忆。首要目标不是立即恢复题目、分析表现或构造完整问答，而是先得到一份内容准确、连续可读、可以人工编辑和确认的转写文档。只有这份文档确认后，系统才可以基于它提取面试题并进入后续复盘分析。

目标流程必须保持为：

```text
原始录音转写
  ↓
准确性整理
  ↓
一份连续的整理稿
  ↓ 用户编辑与确认
已确认转写文档
  ↓
题目提取与后续复盘
```

手机录音转写常包含同音字、错别字、错误断句、技术名词误识别、口头禅、紧邻重复和不完整语句。如果未经整理便提取问题，这些错误会继续传播到问题还原、回答评价、题库候选、画像与项目经验候选。

同时，录音可能只包含候选人自己的声音。Cleanup 不能为了拼成完整对话而伪造面试官原话；缺失问题只能在已确认文档之上由后续题目提取流程保守推断并明确标记。

## 2. 现有方案及其局限

### 2.1 现有执行方式

旧方案采用以下链路：

```text
SourceVersion 原文
  ↓ 约 4,000 字窗口，约 400 字重叠
Source Unit（按标点继续切分，最多约 800 字）
  ↓ 模型为每个 Unit 返回一个或多个 turn
SegmentRecord
  ↓ 程序对原文与 correctedText 做字符 Diff
CorrectionRecord
  ↓
逐段、逐修订人工核对
```

这个方案最初试图同时解决五件事：

1. 长文本不超过模型上下文和输出上限；
2. 恢复说话人和对话轮次；
3. 修正 ASR 错字与口语问题；
4. 为每个修改保留原文 offset 和审计记录；
5. 让用户确认高风险变化后再分析。

这些目标本身合理，但旧方案错误地把模型调用单元、说话人轮次、审计 Diff 和用户核对单元绑定为同一个业务对象。

### 2.2 真实样本暴露的问题

一小时级真实转写暴露了以下问题：

- 约 4,000 字窗口的结构化结果会接近或触及 Provider 的 8,192 输出 Token 上限；
- 模型生成的字符 offset 不稳定，不能作为不可变原文证据；
- 为了修复 offset，程序引入 Source Unit 和逐字边界校验，Prompt 与输出协议迅速复杂化；
- 一个 Source Unit 可以被模型拆成多个 turn，所有 turn 又被持久化为用户可见段落；
- `SequenceMatcher` 的普通文字差异被放大为大量 CorrectionRecord；
- 一小时转写出现过 1,000 项以上“待处理”，但其中绝大多数只是标点、口头禅或普通措辞变化，并非 1,000 个关键事实风险；
- 用户看到的是内部处理颗粒，而不是一份可直接使用的文档；
- 同一段内容同时存在 Provider `correctedText`、程序重建正文和用户采用稿，导致页面与运行中心难以核对；
- 为修复 Schema 漂移、边界缺失和重复请求增加的兼容逻辑，使主要目标从“提高文档准确性”偏移为“维护复杂结构契约”。

### 2.3 根因

根因不是简单的 Prompt 不够好，也不是模型能力不足，而是抽象层次错误：

- **内部窗口泄漏为产品段落。** 窗口和 Source Unit 应只服务于模型容量、重试和恢复，不应直接成为用户工作量。
- **Diff 被误当成待办生成器。** Diff 适合定位和诊断，不代表每个字符变化都需要人工决策。
- **Cleanup 同时承担过多职责。** 文本准确性、说话人恢复、问题反推和证据锚点被塞进同一模型合同，增加了输出长度与失败面。
- **优化顺序倒置。** 先追求逐字审计和可观测性，再追求最终文档质量，导致诊断结构压过用户结果。
- **缺少最终 Artifact。** 系统保存了大量中间记录，却没有把“一份完整准确的转写文档”确立为 Cleanup 的唯一产品产物。

### 2.4 旧方案仍然保留的能力

以下能力仍有价值，应继续保留在内部运行层：

- 原始 `SourceVersion` 不可变；
- 长文本窗口可停止、恢复、局部重试和自适应拆分；
- Provider 请求、响应和失败原因进入运行中心；
- 程序而不是模型拥有原文范围与稳定 ID；
- 数字、否定、时间、主体、组织和职责等级不能被静默改写；
- 已确认版本不可变，后续修改产生新版本。

需要取消的是“模型每个 turn 直接成为用户段落”和“每个 Diff 直接成为人工待办”。

## 3. 成熟项目参考与采用边界

本设计没有找到可以直接复制的开源“中文面试录音转写纠错”实现。参考的是成熟 Agent 与文档处理项目经过验证的架构模式，而不是声称这些项目已经解决了本产品的领域问题。

| 项目 | 成熟设计模式 | 本方案采用 | 明确不照搬 |
|---|---|---|---|
| [DeerFlow Core Concepts](https://deerflow.tech/en/docs/introduction/core-concepts) / [Tools](https://deerflow.tech/en/docs/harness/tools) | 使用受控工作集、文件系统外部工作记忆和 Artifact；子任务在隔离上下文中完成，最终通过 `present_files` 呈现报告或文件 | 内部窗口、模型响应和诊断属于运行过程；用户核对的是一个 `CleanTranscriptVersion` Artifact | Cleanup 是固定领域工作流，不改造成可自由决策的 ReAct Agent，也不为每个窗口创建通用子 Agent |
| [LangGraph Send / Map-Reduce](https://langchain-ai.github.io/langgraph/how-tos/state-reducers/) | 用不同局部 State 并行 Map，再由 Reducer 聚合到主状态 | 每个文本目标窗口独立运行、持久化、重试；只有所有核心窗口完成后才生成完整整理稿 | Map 输出不直接成为正式文档段落，不允许并发 Worker 竞争写最终正文 |
| [Microsoft GraphRAG Inputs](https://microsoft.github.io/graphrag/index/inputs/) / [Outputs](https://microsoft.github.io/graphrag/index/outputs/) | 长文档切成带 overlap 的内部 Text Unit；Document 保留完整正文，Text Unit 保留来源关系，后续再聚合成实体、关系和报告 | 区分完整文档和内部处理单元；确认后生成稳定 Anchor，供题目证据引用 | 不引入知识图谱、实体社区或 GraphRAG 查询；Text Unit 不成为用户逐项核对对象 |
| [Haystack DocumentPreprocessor](https://docs.haystack.deepset.ai/docs/documentpreprocessor) / [DocumentSplitter](https://docs.haystack.deepset.ai/docs/documentsplitter) | Converter、Cleaner、Splitter、Writer 是清晰分离的组件；切片保留 `source_id` 与来源元数据 | 将机械规范化、LLM 纠错、合并、文档保存和下游提取拆成明确阶段；保留来源映射 | Haystack 的规则 Cleaner 不能解决中文 ASR 语义纠错，因此只借鉴流水线边界，不直接使用其清理规则代替 LLM |

由这些项目得到的共同原则是：

1. 长文本切片是容量与执行策略，不是最终产品形态；
2. 局部 Worker 只看到完成任务所需的最小上下文；
3. Reducer 或 Writer 负责产生单一、稳定、可复用的 Artifact；
4. 来源关系和中间结果可以保留，但默认不转化为用户操作负担；
5. 下游任务消费确认后的 Artifact，而不是消费某次模型调用的临时输出。

## 4. 产品目标与非目标

### 4.1 目标

- 在问题提取前生成一份连续、准确、可编辑的转写文档；
- 用户只需要阅读文档和处理少量真正不确定的关键内容；
- 内部窗口数量、Source Unit、模型重试和字符 Diff 不进入主业务页面；
- 高置信度的断句、标点、口头禅、重复词和 ASR 错字可以直接体现在整理稿；
- 不确定的技术术语、数字、主体和职责不被模型静默猜测；
- 一小时以上文本仍支持渐进保存、停止、刷新、恢复和局部重试；
- 已确认整理稿成为题目提取、逐题分析、引用和导出的唯一文本输入；
- 问题证据可以追溯到确认稿，并在原文仍保留时继续追溯到 SourceVersion；
- 使用真实长样本与“直接交给同一模型整理”的基线做盲测，不能只以接口成功和测试通过宣称质量达标。

### 4.2 非目标

- Cleanup 不提取题目、不评价答案、不总结表现；
- Cleanup 不补写录音中缺失的面试官问题；
- 不做联网事实核验，不以题库答案、画像结论或历史复盘补写当前文本；
- 不构建通用文档校对平台、通用 Agent Harness 或知识图谱；
- 不要求用户逐条确认普通格式变化和所有字符 Diff；
- 不把模型置信度百分比当作准确性事实或用户决策依据；
- 不保证仅凭单边录音准确恢复双方说话人。

## 5. 权威数据模型

```text
SourceVersion
  原始转写，不可变
       │
       ▼
CleanupRun
  执行状态、窗口进度、重试与诊断
       │
       ├── CleanupWindowResult（内部）
       │     target range / corrected target / uncertain candidates
       │
       ▼
CleanTranscriptVersion
  一份完整连续正文，draft → confirmed
       │
       ├── TranscriptReviewIssue（稀疏）
       │     只表示真实歧义或关键风险
       │
       └── TranscriptAnchor（确认后生成）
             下游引用锚点，不是人工审核段落
       │
       ▼
QuestionExtractionRun
  只读取 confirmed CleanTranscriptVersion
```

### 5.1 SourceVersion

- 保存用户提交的原始文字；
- 在用户执行“清除原文”前不可修改；
- Cleanup 重试始终从同一个 SourceVersion 派生，不从某次模型输出继续滚动改写。

### 5.2 CleanupRun 与 CleanupWindowResult

- `CleanupRun` 是长任务运行聚合，记录窗口、尝试、活动时间、错误码和模型调用；
- `CleanupWindowResult` 只属于内部运行状态，不作为正式业务段落暴露；
- 每个结果包含目标原文范围、整理后的目标正文、少量不确定候选和校验元数据；
- 已完成窗口可以独立保存并在刷新、停止、进程重启后复用。

### 5.3 CleanTranscriptVersion

- `body` 是 Cleanup 唯一的用户产物；
- `draft` 允许用户直接编辑，使用 expected version 做乐观锁；
- `confirmed` 后不可变；再次整理或编辑创建新版本；
- 正文按自然段展示，但自然段不是独立审核任务，也不要求一一对应模型窗口；
- 分析、导出和题目提取只能读取 `confirmed` 版本。

### 5.4 TranscriptReviewIssue

ReviewIssue 只用于无法安全自动决定的内容，例如：

- 技术术语存在多个合理候选；
- 数字、时间、版本或比例疑似识别错误；
- 公司、组织、项目或主体无法唯一判断；
- 了解、参与、负责、设计、主导等职责等级可能被改变；
- 文本存在缺失、截断或语义无法恢复。

普通标点、空格、口头禅删除、紧邻重复和高置信错字不生成 ReviewIssue。字符 Diff 可以进入运行诊断，但不能自动制造用户待办。

未处理 ReviewIssue 默认保留安全文本：关键字段不确定时保留原词，而不是先写入猜测结果再阻塞用户。只要所有窗口完整，用户可以带着未解决提示确认当前文档；未解决提示随版本保留并提供给题目提取，但不能被下游当作确定事实。

### 5.5 TranscriptAnchor

- 只在完整整理稿生成后，按自然段和稳定字符范围确定性创建；
- Anchor 用于题目证据、逐题分析引用和原文对照；
- Anchor 不是模型调用窗口，也不是用户必须逐项确认的业务段落；
- 用户修改 draft 后重新生成 Anchor；confirmed 后 Anchor 冻结。

## 6. 固定工作流

该流程是确定性的领域 Workflow，不是需要自由规划的 ReAct Agent。

```text
normalize_source
  → plan_cleanup_windows
  → clean_target_windows (Map)
  → assemble_clean_document (Reduce)
  → verify_document_consistency
  → review_document
  → confirm_document
  → build_anchors
  → extract_questions
```

### 6.1 normalize_source

程序只做不会改变语义的机械处理：

- 统一换行与不可见字符；
- 规范明显重复空格；
- 保留数字、大小写、技术符号和原始标点信息；
- 不删除口头词，不修正术语，不调整语序。

### 6.2 plan_cleanup_windows

- 优先在自然段、句号、问号和明显停顿处规划目标窗口；
- 每个 Work Item 明确区分 `context_before`、`target_text` 和 `context_after`；
- 上下文只帮助理解，模型只能返回 `target_text` 的整理结果；
- 目标窗口初始建议为约 2,500～4,000 中文字符，两侧上下文各约 300～800 字符；
- 超时或输出截断只拆分当前目标窗口；已完成窗口不重跑；
- 首版最多并发 2，避免 Provider 限流和执行状态竞争。

这里不再创建模型可见的 800 字 Source Unit，也不要求模型为每个标点单元返回 turn。

### 6.3 clean_target_windows

每个 Map 调用只完成一件事：把 `target_text` 整理成准确可读的 `corrected_target`。

允许：

- 修复断句和标点；
- 删除不承载语义的口头禅与紧邻重复；
- 修正上下文能够唯一确认的 ASR 错字和技术术语；
- 保持原始事实、顺序、立场和职责等级。

禁止：

- 总结、扩写、重排话题；
- 补写面试官问题；
- 把“参与”提升为“负责/主导”；
- 猜测数字、组织、项目名和技术结论；
- 返回字符 offset、完整 Diff、Segment 列表或说话人 turn 列表。

最小输出合同：

```python
class CleanupWindowOutput(BaseModel):
    corrected_target: str
    uncertain_items: list[UncertainItem]
```

`UncertainItem` 只描述原词、候选值、原因和风险类别；绝对位置由程序在当前 `target_text` 中定位。无法唯一定位时保留为窗口级诊断，不让整个任务因辅助审计失败。

### 6.4 assemble_clean_document

- 由于每个窗口只输出不重叠的 target 区域，Reducer 按目标原文顺序拼接 `corrected_target`，不合并重叠模型正文；
- 上下文重叠不参与输出，因此不会产生父窗、子窗和重叠区重复正文；
- Reducer 检查窗口是否完整、顺序是否连续、是否存在缺口或重复 target；
- 不完整窗口阻止生成可确认文档；其他窗口结果继续保存并可局部重试；
- 最终只创建一个 `CleanTranscriptVersion.body`。

### 6.5 verify_document_consistency

该阶段不重新生成全文，只检查和定向修复跨窗口问题：

- 相邻窗口接缝是否出现重复、断句破裂或明显内容缺口；
- 同一技术名词是否存在多种拼写；
- 数字、否定、组织、职责等级是否发生高风险变化；
- 文档长度、事实关键词和内容覆盖是否异常下降；
- 是否出现原文不存在的大段内容。

程序先做覆盖率、关键 Token 和接缝检查；需要模型判断时只提交有限接缝或术语表，不要求模型再次输出整份文档。任何不确定结果生成 ReviewIssue 或保留原文，不进行无界全文重写。

### 6.6 review_document 与 confirm_document

页面主区域展示一份连续文档：

- 用户可以像编辑普通文档一样阅读和修改；
- 右侧只展示稀疏 ReviewIssue，可定位到对应文本；
- 用户可以接受候选、保留原文或手动修改；
- 普通自动整理只显示汇总，不铺开上千条 Diff；
- 确认操作冻结文档正文、ReviewIssue 状态和 Anchor 输入。

确认门禁只检查：

- 所有目标窗口已经完成；
- 文档不是空文本；
- 没有结构性缺口或拼接失败；
- 用户保存的 draft 版本未发生并发冲突。

未解决的术语提示不会强迫用户逐条点击；系统保留原词并明确提示其不确定性。

### 6.7 build_anchors 与 extract_questions

- 系统基于 confirmed 文档确定性生成自然段 Anchor；
- 问题提取按 Anchor/语义区间进行内部 Map，Reduce 合并重复候选；
- 原文明确出现的问题标记为 `original`；
- 单边录音中根据回答恢复的问题标记为 `inferred`，必须保存回答 Anchor 和推断依据；
- 题目提取不读取 CleanupWindowResult、模型 turn 或未确认 draft；
- 同一个项目的信息可以跨多个 Anchor 聚合，但不得为了形成完整故事增加文档中不存在的事实。

问题提取的模型合同只包含语义字段：问题文字、来源类型、问题/回答证据 Anchor、推断依据、
边界关系、可选分类和置信度。`ordinal`、`anchorSegmentId`、全局排序和跨窗口合并属于程序的
确定性职责，不得要求模型生成。原话问题的 Anchor 取首个问题证据，推断问题的 Anchor 取首个
回答证据。

## 7. 上下文与模型调用策略

Cleanup 模型只能读取：

- 当前 target 及有界前后文；
- 当前求职目标的公司、岗位和明确技术词；
- 用户登记的项目名和技术栈词；
- 源版本冻结的录音覆盖范围；
- 已冻结的本次术语候选表。

不能读取：

- 题库答案、掌握度和画像评价；
- 历史复盘结论或改进答案；
- Knowledge 总结和外部网页；
- 后续问题提取或分析结果。

调用原则：

- temperature 使用 Provider 能支持的低随机配置；
- 关闭 SDK 隐式重试，由持久工作项控制有限重试；
- 输出 Token 根据 target 长度设定上限，超时和 `max_tokens` 明确分类；
- Schema 格式错误不通过反复缩小窗口掩盖，应快速失败并记录 Provider 兼容性；
- 运行中心保留完整请求、响应和错误，业务页面只展示进度与最终文档。

问题提取采用独立的 `transcript_only` 上下文边界：

- 每次 Map 调用只读取当前 Anchor 窗口、少量相邻重叠和 `recordingCoverage`；
- 不发送画像、简历 Claim、岗位文档正文、历史复盘、题库或 Knowledge；
- 结构化输出校验关闭框架内部隐式回灌，避免原请求、错误响应和校验文本在同一线程膨胀；
- 首次结构错误只允许一次紧凑修复，修复请求仅携带错误候选、校验摘要及候选已引用的证据 Anchor；
- 修复仍失败或引用窗口外证据时停止当前窗口，不自动重发完整窗口；已完成窗口继续持久化；
- Provider 超时仍可按现有策略拆分当前窗口，其他窗口不重跑。

## 8. 页面与交互设计

### 8.1 处理中

展示真实运行状态：

- `已完成 N / M 个文本窗口`；
- 当前阶段：整理、合并或一致性检查；
- 活动窗口数量、持续时间和最近保存时间；
- 已完成比例和活动动画，不伪造模型内部百分比；
- 超时、拆分、停止、恢复和失败使用明确文案；
- 可以离开页面，刷新后读取持久化进度。

处理中不展示尚未合并的模型段落列表，避免用户把局部输出误认成最终文档。诊断需要通过运行中心查看。

### 8.2 整理完成

主页面只保留：

- 文档标题和状态；
- 一份连续可编辑的整理稿；
- ReviewIssue 数量与定位列表；
- 原始转写对照入口；
- 保存、重新整理和确认文档操作。

不再显示：

- 上千条模型 Segment 队列；
- 每个字符 Diff 的接受/拒绝按钮；
- Source Unit、窗口 ID、模型置信度和内部 offset；
- “当前采用稿”和“模型响应”两套主正文。

模型原始响应、结构化事件和内部窗口继续在 Agent 运行中心作为高级诊断能力存在。

### 8.3 确认后

- 展示只读确认稿和“重新整理/创建新版本”；
- 提供“开始提取题目”或自动进入题目提取阶段；
- 题目引用点击后定位到确认稿 Anchor；
- 原文仍存在时可以继续查看原始转写对照。

## 9. 失败、恢复与旧数据

- 每个窗口独立持久化，停止、刷新和进程重启不丢失已完成结果；
- 超时或输出截断只重试/拆分当前窗口；
- Provider Schema 整体不兼容时快速失败，不继续消耗所有窗口；
- 任一 target 最终失败时不生成可确认 CleanTranscriptVersion，但可显示已保存窗口数量并允许继续；
- 用户编辑使用 expected version，冲突时保留本地文本并提示刷新；
- 清除原文时删除 SourceVersion 正文、窗口正文、可重读 Trace 正文及原文对照内容，保留哈希、状态、结构化结论和已发布外部资产。

旧方案产生的测试 CleanupVersion、SegmentRecord 和 CorrectionRecord 不要求用户逐项处理。功能尚未正式交付前，使用原始 SourceVersion 创建新的 CleanupRun 和 CleanTranscriptVersion；旧结果只作为诊断证据保留或在开发数据重置时清理。

## 10. 质量验收

### 10.1 自动测试

- 窗口 target 完整、不重叠且覆盖全文；
- context 不进入 corrected output；
- 拼接后不存在重复或缺口；
- 超时与截断只拆分当前窗口；
- 已完成窗口不会被重复调用；
- 高置信格式/口语/错字能进入整理稿；
- 数字、否定、组织、职责变化保留原文并生成稀疏 Issue；
- 模型无法定位 Issue 时不破坏完整文档；
- 用户编辑、乐观锁和确认后不可变；
- confirmed 文档生成稳定 Anchor；
- 题目提取只读取 confirmed 文档；
- 清除原文同步清除可重读中间正文。

### 10.2 真实样本验收

至少准备：

- 一份双方都有录音的中长转写；
- 一份主要只有候选人声音的一小时级转写；
- 一份包含数字、否定、公司名、技术术语和职责表述的合成边界样本。

对同一 Provider、同一模型建立“直接把完整可容纳文本交给模型整理”的基线。新 Workflow 必须进行盲测，不以实现复杂度为理由接受更差结果。

核心指标：

- 重要事实保留率；
- 数字、否定、主体和职责的误改数；
- 技术术语修正准确率；
- 口头禅与重复清理效果；
- 人工阅读流畅度；
- 用户需要处理的真实歧义数量；
- 一小时文本是否得到一份完整文档，而不是上千个操作项；
- 同样输入多次执行时文档结构和关键事实是否稳定。

验收要求：

- 新 Workflow 在事实保真上不得弱于直接整理基线；
- 可读性明显优于原始 ASR，且不依赖用户逐段重写；
- 正常格式与口头清理不制造人工待办；
- 单边录音不会伪造面试官原话；
- 用户确认一份文档后才能进入题目提取；
- 题目可追溯到确认文档 Anchor。

## 11. Tradeoff 与成熟度边界

逐题分析阶段的上下文预算、Provider 重试所有权与失败隔离不属于 Cleanup 文档拼接协议，独立记录在：

- `../architecture-decisions/2026-08-03-retrospective-question-analysis-context-and-retry-boundary.md`

本方案放弃“每个模型 turn 都有精确原文 offset 并可逐条核对”的表面精细度，换取：

- 更简单、稳定的模型合同；
- 更小的结构化输出；
- 一份真正可用的最终文档；
- 与内部窗口数量无关的用户工作量；
- 清晰的“先准确转写、后提取题目”产品阶段。

代价是：

- 自动修订不能为每个普通字符变化提供完整业务级审计卡；
- corrected 文本到 raw 原文的字符级映射不再天然一一对应；
- 问题引用以确认稿 Anchor 为第一证据，原文对照通过版本和近邻范围实现；
- 需要补充新的 CleanTranscriptVersion/ReviewIssue/Anchor 数据模型，并迁移现有分析输入边界。

这符合当前产品优先级：先保证用户得到准确文档和可用题目，再把运行中心作为高级诊断层保留，而不是让诊断模型主导日常交互。

## 12. 后续实施边界

实施前必须先更新现有实施计划与关联 ADR，旧计划中以下结论已经失效：

- `SegmentRecord.body` 是 Cleanup 唯一主文档；
- 模型 `turn` 直接成为正式 Segment；
- 每个 CorrectionRecord 都可能成为人工核对项；
- 问题提取直接消费用户确认的模型段落队列。

后续实现按以下顺序进行：

1. 引入 CleanTranscriptVersion、ReviewIssue 和 confirmed Anchor 契约；
2. 把 Cleanup 输出改为 `corrected_target + uncertain_items`；
3. 实现非重叠 target 规划、拼接与接缝/术语一致性检查；
4. 将页面改为单文档编辑器与稀疏问题侧栏；
5. 将题目提取输入切换为 confirmed 文档 Anchor；
6. 对开发期旧 Cleanup 数据提供重新生成路径；
7. 完成自动回归、真实 Provider 基线对比和完整浏览器验收。

在真实长样本未达到上述质量标准前，不再把“自动测试通过”或“可以显示模型响应”表述为转写整理已经可交付。
