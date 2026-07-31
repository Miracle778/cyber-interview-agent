# 架构案例：题目整理从连续失败到 125/125 成功

- 日期：2026-07-21 至 2026-07-22
- 类型：故障复盘与架构演进案例
- 适用范围：R2 题目整理 Agent
- 关联设计：`../specs/2026-07-21-r2-progressive-question-curation-design.md`
- 关联设计：`../specs/2026-07-22-r2-curation-long-task-control-and-performance-design.md`
- 关联设计：`../specs/2026-07-22-r2-messy-notes-curation-resilience-design.md`
- 关联 ADR：`2026-07-21-progressive-question-curation-pipeline.md`
- 关联 ADR：`2026-07-21-local-agent-jsonl-diagnostic-traces.md`
- 关联 ADR：`2026-07-22-resumable-agent-task-boundary.md`

## 面试时的 90 秒讲法

项目的题目整理 Agent 在处理一份约 4 万字符的 MyBatis 随手记时连续失败。最初的报错是“模型未生成结构化题目候选”。我先排除了 Provider 参数问题：GLM 默认开启隐藏推理，消耗完 8,192 个输出 token 后还没有生成 Tool Call；同时通用输出上限只有 2,048。显式关闭 Thinking、调整预算和超时后，小样本成功，但大文档仍不稳定。

继续定位发现，真正的根因不是 token 太小，而是任务边界错误：一次模型调用同时承担“发现所有题目”和“生成所有完整答案”，只限制输入字符并不能限制输出题目数。我把流程重构为“确定性切段 → 轻量 Discovery → 小批量 Enrichment → 确定性归并”，并把每个工作单元持久化。之后又补上最多 3 并发、实时耗时、渐进预览、暂停、恢复和终止，失败时只继续未完成单元。

真实随手记随后继续暴露模型输出偏差：重复引用、缺少引用、超量返回、引用顺序错误、缺少标题和分类。最终把 Provider 的宽松 Observation 与严格领域 Contract 分开，并把恢复粒度从三个题一组的 Work Item 下沉到单题 Seed Task。单题内容问题可以确定性修复、降级或跳过，不能拖垮整个 Batch；未知或越权证据仍然硬失败。

整理成功后，一键发布又在第 36 题遇到 SQLite 锁。检查持久状态发现知识文件和 publication receipt 已成功，失败的是候选状态投影，属于“部分成功”。我没有重放整个发布，而是在同一 action、receipt 和幂等键上对 SQLite busy/locked 做有界重试，并将遗留 running item 恢复为 pending。最终原 Operation 从 35 completed、1 running、89 pending 恢复到 125/125 completed，125 道候选全部发布成功。

这个案例的核心是：大模型应用不能靠提示词、调大 token 和整批重试保证可靠性；必须同时设计有界任务、持久恢复单元、确定性校验、幂等副作用和可观测证据。

## 1. 最初的故障

用户上传的 MyBatis 笔记约 39,570 字符、2,564 行，内容以标题、关键词、编号、代码和半句结论为主，并不是规范题库。旧流程对每个字符块执行一次完整生成：

```text
原文分块
  → 识别块内所有题目
  → 为每题生成答案、分类、难度、关键点和追问
  → 一次性返回完整 QuestionCandidateBatch
```

页面多次显示整理失败，后端核心错误为：

```text
ValueError: 模型未生成结构化题目候选
```

这不是单一代码错误，而是 Provider 参数、任务建模、恢复粒度和真实材料质量共同叠加的结果。

## 2. 第一轮：先排除 Provider 参数问题

### 2.1 输出被截断

最初调用使用通用 `max_tokens=2048`，模型在生成完整结构化结果前已用完预算。提高题目生成预算后，明显的 2,048 token 截断消失，但大文档仍会失败。

### 2.2 GLM 默认隐藏推理

真实 Trace 显示 GLM-5.2 在未显式关闭 Thinking 时会默认推理。一次失败调用消耗约 2,670 input tokens 和完整 8,192 output tokens，却没有形成结构化 Tool Call。

修复为：

- `reasoning_effort=none` 对 GLM 显式映射为 `thinking.type=disabled`；
- 未知 OpenAI-compatible 模型不发送 GLM 专属参数；
- Discovery 使用 2,048、Enrichment/Revision 使用 4,096 的独立输出预算；
- 超时按任务设置，SDK 自动重试设为 0，由产品 Runtime 管理重试事实。

最小真实调用成功，证明 Provider 参数已正确，但没有证明大文档流程可靠。这一步解决的是放大器，不是根因。

## 3. 第二轮：发现字符分块仍然解决不了问题

曾尝试按编号、段落和字符数拆分原文，并为每块使用稳定 thread。它限制了输入，却仍然无法回答一个关键问题：一个字符块中会识别出多少题？

高密度笔记可能在很短的文本里包含大量标题。完整候选 JSON 的大小由“题目密度 × 每题答案长度”决定，而不是只由输入字符数决定：

```text
有界输入 != 有界输出
```

因此继续调大 token、缩小字符块或更换模型，只会推迟同一种失败。真正需要改变的是模型任务边界。

## 4. 第三轮：把一次大调用改成渐进式流水线

流程重构为：

```text
Source
  → 稳定语义 Section
  → Discovery：只识别轻量 Question Seed
  → 持久化 Work Item
  → Enrichment：每次补全少量完整 Candidate
  → 确定性校验、去重和归并
```

主要边界为：

| 边界 | 上限或规则 |
|---|---|
| 单个 Section | 不超过 2,000 字符 |
| 普通文本 Discovery 窗口 | 约 6,000 字符 |
| 单次 Discovery 输出 | 有界 Seed 数 |
| 单次 Enrichment | 最多 3 个 Seed |
| 活动 Provider 请求 | 最多 3 并发 |
| 单个 Batch | 最多 200 个候选 |

结构明确的问句、编号题和标题优先由确定性代码发现；普通段落才进入模型 Discovery。每个 Work Item 保存输入摘要、状态、尝试次数和不可变完成结果。同一个 Batch 重试时跳过 completed，只处理 failed、interrupted 或 pending。

这次改造解决了三个问题：

- 单次模型输入和输出都有上限；
- 后段失败不会从第一题重新开始；
- 页面可以展示真实完成数，而不是只显示一个不透明的“处理中”。

## 5. 第四轮：补上长任务控制和可观测性

渐进式流程虽然可靠，但真实材料仍需要较长时间。最初约 4 万字符被切成 797 个 Section、133 个 Discovery 单元，调用过细且接近串行；页面也没有实时耗时，用户无法暂停或恢复。

随后完成四项改造：

1. 结构感知规划：明确题目边界直接生成 Seed，普通文本才进入较大语义窗口；
2. 有界并发：Discovery 和 Enrichment 各最多 3 个活动请求；
3. 长任务状态：Batch 持有 `generating / paused / interrupted / failed / terminated / review_pending / completed`，Execution 只代表一次运行尝试；
4. 产品控制：实时耗时、渐进候选预览、暂停、恢复、终止和刷新后对账。

暂停、失败或进程重启后，恢复会创建新 Execution，但继续使用原 Batch；completed Work Item 不重放。`terminated` 是不可恢复终态，重复恢复固定返回 409。

同时新增按 Execution 保存的本地 JSONL Trace，记录模型和 Tool 的 request、response、error，并过滤凭据。Trace v2 保留 UTC 权威时间，同时增加北京时间字段，便于人工排查。产品 Event、Checkpoint 和诊断 Trace 分别承担 UI、恢复和诊断职责，不混在一起。

## 6. 第五轮：真实模型输出连续偏离严格 Schema

流水线投入真实恢复后，原来的“没有结构化候选”已经越过，但模型连续暴露了新的边界问题：

| 真实恢复 | 暴露的问题 | 已保存进度 |
|---|---|---|
| 第一次 | 同一合法 `source_ref` 返回多个 Seed | 前 4 个 Discovery 已完成 |
| 第二次 | Seed 缺少 `source_ref`，并包含 null 引用 | 原 Batch 继续复用 |
| 第三次 | 返回 21 个 Seed，超过上限；主引用顺序错误 | 78/80 Discovery 已保存 |
| 第四次 | Candidate 缺少 `title/topics`；两个合法引用被缩成一个 | 80 Discovery、22 Enrichment 已保存 |

这些响应整体上是合法 JSON/Tool Call，但局部字段不符合严格领域模型。把 Provider 响应直接绑定领域 Contract，会因为一个字段错误丢弃整组其他有效结果。

最终改为两层契约：

```text
Provider 宽松 Observation
  → 确定性 Normalizer
  → 严格领域 Contract
```

可以安全修复的偏差包括：

- null、空白和重复列表项；
- 合法重复引用稳定保留第一项；
- 引用顺序错误时按权威 Seed 恢复；
- 缺少 title 时使用题干；
- 缺少 topics 时使用“未分类”；
- 难度别名映射或回退到 medium。

不能安全修复的内容继续失败或进入单题重试：

- 缺少答案或关键点；
- 未知、越权或跨 Seed 引用；
- 无法唯一关联到原 Seed。

原则是：提示词不是安全边界；证据引用由应用拥有，模型只能提出关联线索。

## 7. 第六轮：从 Work Item 恢复下沉到单题 Seed Task

真实随手记不完整，一个三题 Enrichment Work Item 中可能只有一题格式异常。如果仍以整组为恢复单位，一道坏题会让同组两道成功题一起回滚。

因此新增持久 Seed Task，单题成为内容恢复边界：

```text
pending
  → completed：严格候选完成
  → degraded：经过安全归一化，需人工复核
  → retryable：需要一次单题降级调用
  → skipped：两次自动尝试后仍不可用
  → interrupted：等待显式恢复
```

每次 Provider 调用仍可处理最多 3 个 Seed、最多 3 路并发，但结果按 Seed 独立提交。每个 Seed 最多两次自动模型调用：一次批量调用，必要时一次单题兜底。内容质量问题只影响单题；只有 Provider 整体不可用、数据库/文件失败、权威证据损坏或安全越界才允许 Batch failed。

旧 Batch 没有推倒重来。系统从已有 80 个 completed Discovery 和 22 个 completed Enrichment 中幂等恢复出 66 个唯一 Seed，重复 reconciliation 不增加计数，也不触发 Provider。

## 8. 第七轮：把工程状态翻译成用户语言

后端可靠后，页面仍暴露了几个交互问题：

- “正在识别题目”与“Agent 执行失败”都使用红色；
- `0/125` 不能实时变化，且指标布局出现空块；
- “降级保留”属于工程术语，用户不知道需要做什么；
- 整理未完成时仍能点击一键发布，后端 409 但页面缺少解释。

对应修正为：

- 运行中使用主色，只有执行失败使用红色；
- 前端以服务端 Seed/候选事实和 SSE 刷新进度，计数保持单调；
- 对用户显示“需要复核”“等待处理”“已跳过”等行动语义；
- 整理运行中禁用一键发布并显示“整理完成后可一键发布”；
- 黄色表示需要人工复核，红色只表示系统执行失败。

这一步没有改变领域状态，但避免用户把正常运行、内容质量和系统故障理解成同一件事。

## 9. 第八轮：整理成功后，批量发布出现 SQLite 锁

候选生成完成后，用户发起 125 道题的一键发布。Operation 已被接受，前 35 道成功，第 36 道出现：

```text
sqlite3.OperationalError: database is locked
```

直接查询持久状态发现：

| 状态 | 数量 |
|---|---:|
| completed item | 35 |
| running item | 1 |
| pending item | 89 |

继续关联 Candidate、Draft、HITL、Publication 和 Agent Run：

```text
candidate.status           = review_pending
draft.status               = published
publication_run.state      = completed
pending_action.status      = approved
resolution.delivery_status = failed
delivery_error_code        = hitl_resume_failed
bulk_item.status           = running
```

这说明知识文件和 publication receipt 已经成功，失败的是随后把 Candidate 投影为 `published`。异常收口也需要写 SQLite，又遇到同一把锁，于是 Bulk Item 留在 running。

根因不是“一键发布没有开始”，而是一次业务操作跨越了文件系统、HITL、Publication 状态机和 Review 投影，产生了部分成功。即使只有一个 SQLite，只要有多个提交边界，就需要幂等补偿。

## 10. 发布恢复设计

修复没有重放整个 Candidate 发布入口，而是在最小幂等边界——HITL approval delivery——继续执行。SQLite busy/locked 时复用：

- 同一个 Pending Action；
- 同一个 Resolution Receipt；
- 同一个 Publication Run；
- 同一个业务 idempotency key。

首次失败后等待 50 ms，第二次失败后等待 150 ms，第三次仍失败则原样抛出。只重试 SQLite busy/locked；版本冲突、证据错误等业务异常不自动重试。

Operation reconcile 同时增加不变量：

```text
retryable terminal operation 不能遗留 running item
```

`partial_failure / failed / cancelled / interrupted` 中的 running item 会恢复为 pending。再次执行时跳过 completed；已经 durable published 的题只补候选投影，未处理题继续发布。

不能只调大 busy timeout，因为它只能降低冲突概率，不能处理文件已经写入、领域投影未完成的部分成功。

## 11. 最终结果与验证

### 整理链路

- 原材料：39,570 字符、2,564 行；
- 稳定切分：797 个 Section；
- 真实旧 Batch：80 个 completed Discovery、22 个 completed Enrichment 全部保留；
- 幂等恢复：66 个唯一 Seed，重复恢复不调用 Provider；
- 运行能力：最多 3 并发、实时耗时、渐进预览、暂停、刷新恢复和终止；
- 内容容错：单 Seed 独立 completed/degraded/retryable/skipped，内容异常不再拖垮整批；
- 真实整理最终产出 125 道可审核候选。

### 发布链路

| 指标 | 恢复前 | 恢复后 |
|---|---:|---:|
| Bulk completed items | 35 | 125 |
| Bulk running items | 1 | 0 |
| Bulk pending items | 89 | 0 |
| Published candidates | 35，另 1 条 publication 已 durable | 125 |
| Operation status | running / shutdown 后 cancelled | completed |

恢复 Execution `f784218e-b662-4c07-89fc-c7a425ce3070` 最终 completed，125 个候选均为 published，后端没有再次出现 `database is locked`。

自动验证覆盖了结构切分、并发峰值、暂停/恢复/终止、旧 Batch reconciliation、Provider 宽松解析、单 Seed 局部失败、发布锁故障注入和 Bulk Operation 恢复。浏览器还覆盖了桌面与 390px 的实时进度、状态语义和刷新恢复。

## 12. 根因总结

| 层次 | 根因或放大器 | 最终处理 |
|---|---|---|
| Provider 参数 | GLM 默认隐藏推理、输出预算不合适 | 显式 Thinking 映射，按 Agent 配置预算 |
| 任务建模 | 一次调用发现并补全所有题，输出无界 | Discovery / Enrichment 两阶段有界流水线 |
| 恢复粒度 | 整批或三题 Work Item 失败扩大重试范围 | Work Item 持久化，再下沉到单 Seed Task |
| 模型契约 | 提示词无法保证字段、数量和引用完全正确 | 宽松 Observation + 确定性 Normalizer + 严格领域 Contract |
| 长任务体验 | 串行、无耗时、无法暂停恢复 | 结构感知规划、最多 3 并发、Batch 控制状态机 |
| 可观测性 | 产品 Event 无法还原模型调用 | per-Execution 安全 JSONL Trace |
| 发布一致性 | 文件、HITL、Publication 和投影跨提交边界 | 幂等 delivery、有界锁重试、Operation reconcile |
| 用户认知 | 正常运行、需复核和失败语义混在一起 | 语义色、行动文案、发布前置门禁 |

最根本的问题是任务和副作用边界设计不足；Provider 参数、模型格式偏差和 SQLite 锁只是让问题在不同阶段暴露出来。

## 13. 可复用的工程经验

1. 不要用调大 token 代替任务边界设计；
2. 大模型任务要同时限制输入、输出、并发、循环和总产物数；
3. Provider 输出是 Observation，不是领域事实；
4. 提示词不是校验或安全边界，证据必须由应用拥有；
5. 重试要基于持久、幂等的最小工作单元，不能从头重放；
6. 内容质量问题、基础设施故障和安全错误要有不同终态；
7. 产品 Event、恢复 Checkpoint 和诊断 Trace 应职责分离；
8. 文件系统和数据库跨边界操作必须按部分成功设计补偿；
9. 测试通过后仍要用原失败数据恢复，核对最终持久事实；
10. 工程状态不能原样暴露给用户，要翻译成明确的状态和下一步行动。

## 14. 面试追问参考

**为什么不直接换更强的模型？**

更强模型可能提高格式遵循率，但不能保证输出规模、恢复语义、证据权限和副作用幂等。

**为什么不用 Provider 自动重试？**

SDK 不知道哪些业务单元已经提交，可能重复调用或重复副作用。产品 Runtime 才能依据 Work Item、Seed Task 和 receipt 精确恢复。

**为什么允许“降级”而不是全部严格失败？**

随手记天然不完整。可安全补齐的是展示元数据，答案和证据不能伪造；候选可以进入人工复核，但发布仍走严格校验和显式确认。

**为什么重复合法引用可以归一化，未知引用却必须失败？**

重复合法引用是格式偏差，稳定去重不会改变证据边界；未知或跨 Seed 引用可能伪造证据，风险完全不同。

**为什么不使用一个大事务解决发布锁？**

文件系统不能参与 SQLite 原子事务，大事务还会延长 writer 持锁时间。短事务、durable 状态机、内容哈希和幂等补偿更可靠。

**SQLite 是否不适合这个项目？**

当前单用户、单进程 bounded scheduler 仍适合 SQLite。未来若引入多进程 worker 或高并发写入，再迁移服务端数据库；但换数据库也不能替代幂等和部分成功恢复。

**如果重新做一次，最先改变什么？**

先定义 Discovery 与 Enrichment 的边界、单 Seed 恢复单元、输出上限和 Trace，再接真实 Provider，而不是先实现一次性完整生成。
