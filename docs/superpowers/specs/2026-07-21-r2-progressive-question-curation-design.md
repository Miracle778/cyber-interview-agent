# R2 渐进式题目整理设计

## 1. 背景与目标

当前题目整理把一份 source 按数字编号、空段落和字符数切块，然后要求同一个 `question_generation` Agent 在每次调用中同时识别全部题目、纠错、生成参考答案、分类、关键点、追问和来源引用，最后一次性返回 `QuestionCandidateBatch`。

真实 `Mybatis拦截器.md` 只包含 20,051 个输入字符，但属于高密度面试笔记：前 20,000 字符有 1,378 行、552 个空行、41 个 Markdown 标题、多个加粗问题、中文数字列表和大量短主题。现有分块器只识别 12 个带空格的 `1.`/`2.` 列表项，漏掉 `1、正向代理` 等真实题目边界，并把第一处编号前的 287 行前缀复制到多个分组。模型因此在单个 2,000–4,000 字符调用中尝试生成大量完整候选，火山 Ark Coding 端点最终返回 `400 InvalidParameter`。即使调用成功，当前聚合在 50 题时提前终止，也与“每个清晰独立题目都生成候选”冲突。

本设计把题目整理改为可恢复的渐进流水线，使文件大小和题目密度分别受控：本地先建立稳定语义 section；模型先发现轻量 question seed，再以小批次补全完整 candidate；每个工作单元持久记录，失败只重试当前单元；单次会话最多生成 200 个候选。

成功标准：

- 20,000 字符高密度笔记不再依赖一个大型 ToolStrategy 输出；
- Markdown 标题、加粗问题、问号行、`1.`、`1、`、`1)` 均可作为语义边界；
- 前缀只处理一次，所有 section 具有稳定 `sourceId#section-N`；
- discovery 单次最多返回 6 个 seed，enrichment 单次最多返回 3 个完整候选；
- 每个完成单元持久化，后端失败或重启后不重跑已完成单元；
- 整理会话最多聚合 200 个候选，达到上限时显式结束并记录截断原因；
- 单题修订继续只输出一个候选，不进入多题 discovery 流水线；
- 不改变发布、题目去重、active catalog、复习快照和 HITL 边界。

## 2. 候选方案

### 2.1 继续提高 token、超时或缩小字符块

优点是改动小。拒绝原因是输出规模取决于题目密度而不是输入字符数；真实原文在 4,000 和 2,000 字符下均返回 Ark `400 InvalidParameter`，继续缩小会制造大量碎片调用，仍无法保证每次候选数量。

### 2.2 更换界面模型名称

优点是可能绕过某个模型特性。拒绝原因是当前 `claude-haiku-4-5` 本地代理最终仍路由到 GLM-5.2，且模型替换不能修复前缀复制、边界漏识别、单次输出过大和 50 题硬截断。

### 2.3 渐进式 discovery + enrichment

本地 sectioner 先建立稳定小节；discovery 只返回简短 seed；enrichment 每次只补全少量候选；工作单元持久化并由 Graph 循环推进。该方案调用次数更多，但单次请求、输出、恢复和错误边界都可证明，采用此方案。

## 3. 语义切段

新增纯函数 sectioner，不调用模型、不写数据库。输入仍是应用层当前格式：

```text
<source-id>:<filename>
<最多 20,000 字符正文>
```

处理规则按顺序执行：

1. 把仅含空白、Unicode 零宽字符或空 HTML 占位的行归一为空行；不修改非空正文。
2. 识别 Markdown `#`–`######` 标题、整行加粗标题、以 `?`/`？` 结尾的问题行。
3. 识别 `1. text`、`1、text`、`1) text`，编号标点后允许零个或多个空格。
4. 显式边界开始一个 section，直到下一个显式边界；边界后的解释、代码和列表属于当前 section。
5. 第一处显式边界前的松散笔记按非空段落形成 section，不复制到后续 section。
6. 单个 section 超过 2,000 字符时按行切成 continuation section；无换行长文本按硬字符边界切分。
7. section 按来源内顺序编号，引用格式为 `<source-id>#section-0001`。正文哈希由规范化后的 section 内容计算，供工作单元幂等与重试校验。

sectioner 不判断“这是不是一道好题”；它只建立稳定、可审计的候选证据边界。错误切得偏细由 discovery 返回零 seed 或后续去重消化，不能把多个大章节重新拼成无界调用。

## 4. 两阶段 Agent 契约

### 4.1 Discovery

每次输入最多 6 个完整 section，且总正文不超过 6,000 字符。模型只判断其中可以形成哪些独立面试题，不生成答案。

```python
class QuestionSeed(BaseModel):
    question_text: str
    source_ref: str

class QuestionSeedChunk(BaseModel):
    seeds: list[QuestionSeed]  # 0..6
```

约束：

- 每个 seed 必须引用本次输入中的一个稳定 section ref；
- 同一 section 最多返回一个 seed；section 内确有多个独立题目时，sectioner 应优先在编号、标题或问号边界拆开；
- 纯答案、代码片段、日程、占位标题或重复表达可以返回零 seed；
- discovery Prompt 不要求纠错、答案、topic、难度、关键点或追问。

### 4.2 Enrichment

每次输入最多 3 个 seed，并附对应 section 正文与已有相似题。输出完整候选：

```python
class QuestionCandidateChunk(BaseModel):
    candidates: list[QuestionCandidate]  # 0..3
```

每个候选必须保留 seed 的 `source_ref`。模型可纠正明显错误、补齐答案和关键点，但不得为输入中不存在的第四个题目生成候选。单题修订使用独立的 one-candidate contract，不经过 discovery。

整个会话的聚合 contract 与单次 ToolStrategy contract 分离：单次最多 3 个完整候选；聚合最多 200 个。达到 200 时停止创建后续 enrichment work item，把 session/batch 标记为可审核完成，并在 summary warning 中记录 `candidate_limit_reached`，不得静默丢弃。

## 5. 持久工作单元与状态所有权

新增 additive Runtime migration 和 `review_curation_work_items`：

```text
id
batch_id
stage                  discovery | enrichment
unit_index
input_digest
source_refs_json
status                 pending | running | completed | failed
output_json
attempt_count
last_error_code
created_at
updated_at
UNIQUE(batch_id, stage, unit_index)
```

边界：

- source 正文继续只存在原 source artifact、Execution input 和 LangGraph checkpoint；work item 只持久化稳定 refs、摘要哈希和模型结构化输出，不复制原始正文。
- `output_json` 对 discovery 保存 seed，对 enrichment 保存严格 candidate proposal；正式 candidate/draft 仍由 execution completion 的既有确定性持久化流程创建。
- 创建 work item 使用 `batch_id + stage + unit_index + input_digest` 校验。同索引同摘要返回原记录；同索引异摘要稳定失败，防止旧 checkpoint 混入新输入。
- completed work item 在 Graph 重放时直接复用；failed item 增加 attempt count 后可显式重试；SDK 内部不做昂贵的隐式重复请求。
- `review_curation_sessions.completed_units/total_units` 投影当前阶段工作单元，不以 source 文件数冒充生成进度。

## 6. Graph 数据流

`question.curate` 改为显式循环 Graph：

```text
plan_sections
  -> discover_next <-> checkpoint/work-item
  -> plan_enrichment
  -> enrich_next <-> checkpoint/work-item
  -> reduce_candidates
  -> END
```

节点职责：

- `plan_sections`：纯函数切段，创建/复用 discovery work item，设置 generating 进度。
- `discover_next`：每次只执行一个 pending discovery item；成功后持久 output 并推进索引。
- `plan_enrichment`：校验所有 seed refs、去重 seed、每 3 个创建 enrichment item；超过 200 时记录 warning。
- `enrich_next`：每次只执行一个 pending enrichment item；成功后持久 output 并推进索引。
- `reduce_candidates`：对 completed enrichment outputs 做严格校验和现有高置信去重，把结果写入 Graph `candidates`；正式 draft/candidate 的创建仍由 `AgentExecutionService.persist_question_candidates` 统一执行。

Graph checkpoint 只保存 section refs、work item IDs、当前索引和有界聚合结果，不复制领域 candidate、draft 或 publication 状态。进程重启后从相同 batch/work items 恢复；用户对 failed execution 发起重试时复用 completed work items。

## 7. Provider、超时和错误处理

- GLM 4.5+ / 5.x 在 `reasoning_effort=none` 时显式发送 `thinking.type=disabled`；未知 OpenAI-compatible 模型不接收 GLM 扩展字段。
- discovery 输出预算为 2,048 token，enrichment 为 4,096 token；不再给所有 question-generation 调用统一 8,192 token。
- 两阶段 question-generation 请求超时为 180 秒，`max_retries=0`；失败由 work item 和产品 execution 的显式重试承担。
- Provider timeout、400/429/5xx 映射为稳定错误码并记录到 work item，不把 Provider 原始响应、请求正文或密钥写入事件、timeline 或 API。
- 任一 work item 失败时 batch/session 进入 failed，但已完成 item 保留。重试从首个 failed/pending item 继续。

## 8. API 与 UI 边界

现有创建整理会话 API 不变。session resource 的阶段仍是 `reading_sources -> generating -> merging -> summarizing -> waiting_for_command`，但 generating 进度改为真实工作单元：

- discovery 阶段展示“正在识别题目”；
- enrichment 阶段展示“正在补全候选”；
- completed/total 只对应当前阶段，不混合两个不同分母；
- 失败详情显示阶段、单元序号和稳定错误码，不显示正文或 Provider 原始错误；
- 重试原会话时复用 completed work items。

候选题审核、备注、重写、发布、删除和题目库页面契约不变。达到 200 上限时页面显示明确 warning，并允许用户先审核当前结果；本阶段不增加“继续下一批 200 题”的新产品操作。

## 9. 测试与验收

### 9.1 纯函数与契约

- 中文编号无空格、Markdown 标题、加粗标题、问号行、零宽空白；
- 前缀只出现一次，section ref 稳定；
- section 硬上限 2,000，discovery pack 最多 6 个，enrichment pack 最多 3 个；
- discovery 不接受答案字段，enrichment 不接受第四个 candidate；
- 聚合 200 时显式 warning，不静默截断。

### 9.2 Repository 与 Graph

- work item 同摘要幂等、异摘要冲突；
- discovery 第 N 项失败后重试不调用已完成的 1..N-1；
- enrichment 重启恢复、failed item 单独重试；
- malformed source ref、越界输出、重复 seed 和重复 candidate 均由 reducer 拒绝或合并；
- 单题 revise 保持一个候选和原有生命周期。

### 9.3 真实文档

- 本地使用授权的 `Mybatis拦截器.md` 验证 section 数、工作单元数、前缀不重复和候选不超过 200；
- 真实 Provider 跑完整 discovery/enrichment，记录每阶段单元数、成功/失败、耗时和 usage，不记录正文或响应体；
- 停止后重试验证 completed work item 不重复调用；
- 完成后候选可进入现有审核、发布和题目库流程。

## 10. 非目标

- 不建设通用文档理解平台、向量检索或任意自主 Planner；
- 不自动发布候选，不改变 HITL；
- 不在本阶段支持单次会话超过 200 个候选或继续下一批；
- 不让模型决定 section、work item、重试、停止条件或数据库写入；
- 不把原始 source 正文复制进新的领域表或产品事件。
