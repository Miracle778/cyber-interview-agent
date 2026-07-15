# Agent Context Assembly 设计

## 1. 背景

R2 题库整理会话允许用户使用“第 6 题是什么”“这题发布吧”“加了备注的重新生成，其他的发布”等自然语言继续操作候选题。当前实现为了修复近距离指代，只向模型拼接最近 8 条可见消息，并在每次调用中附带全部候选题的完整内容。

该实现可以覆盖紧邻的两三轮交互，但存在四个结构性问题：

- 固定消息条数不等于稳定 token 预算，也不能保证保留完整对话轮次；
- “这题”依赖模型从文本猜测，没有可恢复、可审计的领域焦点；
- 候选题数量增长后，全量正文会显著增加成本、延迟和上下文污染；
- 现有 summarization middleware 只能压缩送入 role Agent 的消息，不能替代产品会话的领域记忆与资源选择。

本设计建立可供后续 Agent 复用的上下文组装骨架，并首先迁移题库整理命令链路。它不在本切片迁移答案评价、报告、讨论等全部 R2 Agent。

## 2. 目标与非目标

### 2.1 目标

- 以 token 预算和完整 turn 取代固定 8 条消息窗口；
- 持久化题库整理会话的当前焦点、最近操作和压缩游标；
- 显式命令优先确定性解析，复杂或含糊表达才调用模型；
- 仅向模型注入当前相关资源的全文，其他资源使用轻量索引；
- 压缩后仍保留稳定资源 ID、决定、备注和未解决事项；
- 保留现有官方 Agent middleware 作为模型调用级的最后保护；
- 提供不包含 candidate、resume、JD 等业务字段的通用 ContextAssembler 协议。

### 2.2 非目标

- 不创建多 Agent supervisor、动态 Agent registry 或通用记忆平台；
- 不把所有输入都强制交给一个长期运行的 Intent Agent；
- 不让摘要成为候选题、发布状态或用户消息的事实来源；
- 不在本切片迁移 `question_generation`、`answer_evaluation`、`report_summarization` 和 `agent_chat` 的既有上下文；
- 不改变题目发布、HITL、Vault、索引和 version/hash 的领域边界；
- 不以 Langfuse 可用作为开发或验收前提。

## 3. 术语与命名

### 3.1 业务 Agent

`QuestionCurationAgent` 是题库整理模块中真正负责根据来源生成、补充和重写候选题的业务 Agent。它在 `question.curate` Graph 中运行，使用稳定 role thread 和 checkpoint。

### 3.2 命令解释器

现有 `CurationIntentAgent` 更名为 `CurationCommandInterpreter`。它不是用户可见的长期 Agent，而是一个受约束的命令解释组件：

1. `DeterministicCurationCommandParser` 处理序号、明确范围和唯一焦点等可确定表达；
2. `StructuredCurationCommandClassifier` 只在规则不能安全决定时进行一次结构化模型调用；
3. 两者统一返回 `CurationCommandPlan`，不直接执行任何副作用；现有 `CurationIntentPlan` 同步更名，避免继续把分类结果误解成独立 Agent。

`StructuredCurationCommandClassifier` 可以继续使用 `create_agent` 获得结构化输出和统一 middleware 治理，但不拥有长期 thread/checkpoint。Agent/组件名称必须表达职责，模型用途绑定只决定使用哪个模型配置；`AgentSpec` 应允许执行名称与 model role 分离，默认值保持现有调用方不变。

### 3.3 ContextAssembler

`ContextAssembler` 是无领域知识的纯组装边界。它根据预算选择结构化工作状态、历史摘要、最近完整 turn 和按优先级排序的资源，返回本次模型调用的上下文材料及用量事实。

## 4. 推荐架构

```text
产品 timeline / 领域 repository
             |
             v
 CurationContextProjection
 - focused candidate IDs
 - last intent/result
 - dialogue summary/cursor
             |
             v
 DeterministicCurationCommandParser
       | 无法安全决定
       v
 CurationContextAdapter
       |
       v
 ContextAssembler
 - token budget
 - recent complete turns
 - structured summary
 - focused full resources
 - lightweight resource index
       |
       v
 StructuredCurationCommandClassifier
       |
       v
 CurationCommandPlan
       |
       v
 CurationCommandService
 - summary version
 - candidate state
 - permission/idempotency
 - domain side effects
```

该架构采用“通用组装协议 + 领域记忆投影”，不建立持有所有 Agent 状态的通用 JSON 大表，也不建立平行 middleware pipeline。

## 5. 通用上下文协议

通用层提供以下窄类型，具体名称可在实施计划中按当前 Python 模块风格落地，但语义不得合并成无类型字典：

```text
ContextBudget
  max_input_tokens
  reserved_output_tokens
  reserved_system_tokens
  reserved_schema_tokens
  reserved_tool_tokens

ContextMessage
  sequence
  role
  content
  resource_refs[]
  token_count

ContextResource
  ref
  label
  content
  priority
  token_count

ContextSummary
  text
  resource_refs[]
  decisions[]
  open_items[]
  through_sequence

ContextMaterial
  working_state
  prior_summary
  messages[]
  resources[]

AssembledContext
  working_state
  summary
  recent_messages[]
  selected_resources[]
  estimated_input_tokens
  threshold_tokens
  compacted
```

`ContextAssembler` 不查询数据库、不调用模型、不修改领域状态。领域 adapter 负责加载材料；summary service 负责生成和持久化压缩摘要；usage projection 负责把无正文的 token/压缩事实投影给产品页面。

## 6. 题库整理领域记忆

新增 `review_curation_context` 记录：

| 字段 | 含义 |
|---|---|
| `session_id` | 主键并关联整理会话 |
| `version` | 乐观锁版本 |
| `focused_candidate_ids_json` | 当前唯一或多个明确焦点 |
| `last_intent` | 最近一次成功解释并执行的意图 |
| `last_result_candidate_ids_json` | 最近操作涉及的候选题 |
| `dialogue_summary_json` | 早期对话的结构化压缩摘要 |
| `summarized_through_message_id` | 摘要覆盖的最后消息 |
| `created_at` / `updated_at` | 审计时间 |

状态所有权保持明确：

| 信息 | 唯一事实来源 |
|---|---|
| 候选题正文、答案、关键点 | candidate/draft repository |
| 发布、拒绝和 draft version | publication/domain repository |
| 用户可见对话 | product session timeline |
| 当前焦点和压缩游标 | `review_curation_context` |
| role Agent 内部消息和 summary | LangGraph checkpoint |
| 页面上下文用量 | usage projection，可从调用重建 |

上下文摘要只能引用稳定 ID，不能覆盖或修订领域事实。

## 7. 命令处理流程

1. 读取 curation session、summary version 和 `review_curation_context`；
2. 对输入执行确定性解析：明确序号、recommended/noted/unnoted/all 范围和唯一有效焦点优先；
3. 如果得到唯一安全计划，跳过模型调用；
4. 否则由 adapter 读取未被摘要覆盖的产品消息，按 user/assistant 完整 turn 组织；
5. 当旧历史超过分配预算时，summary service 只压缩早期完整 turn，并以 CAS 推进 summary cursor；
6. 加载焦点候选题全文；其他候选题只加载序号、标题、状态、推荐、备注标记和稳定 ID；
7. `ContextAssembler` 在预算内选择材料；
8. classifier 返回严格 `CurationCommandPlan`；
9. `CurationCommandService` 重新校验 summary version、candidate IDs、状态、权限和幂等 receipt；
10. 操作成功后以 CAS 更新焦点、最近意图和最近结果；失败、超时、非法结构或澄清不更新焦点。

显式 inspect 成功后更新焦点。单题 publish/reject/regenerate 成功后保留该题为最近结果；多题操作保留多个焦点，后续“这题”必须澄清，不能任选其一。

## 8. Token 预算与压缩

模型调用可用输入预算按以下顺序计算：

```text
available input = model context limit
                - system prompt
                - structured output schema
                - reserved output
                - tool/safety headroom
```

剩余预算按优先级分配：

1. 当前用户输入和结构化工作状态；
2. 当前焦点资源全文；
3. 历史结构化摘要；
4. 最近完整对话 turn；
5. 其他候选题轻量索引；
6. 低优先级历史文本。

不得从中间截断单条消息或拆散 user/assistant turn。token counter 优先使用当前模型能力；无法使用时采用保守字符估算并标记 degraded。估算仍无法满足硬预算时返回 `context_budget_exceeded`，不发送超限 prompt。

压缩摘要必须保留：

- candidate ID、当时序号和资源类型；
- 用户已经表达的决定与备注；
- 最近明确焦点和多焦点歧义；
- 已执行操作及稳定 receipt/resource ref；
- 未解决问题和需要澄清的事项。

现有 `ProjectingSummarizationMiddleware` 继续作为 role Agent 消息历史接近模型窗口时的最后保护。领域压缩发生在模型调用前，两者职责不同，不创建新的 middleware 协议。

## 9. 失败、恢复与幂等

- 模型失败、超时、schema 非法或含糊计划均 fail-closed，不产生发布、拒绝、重写等副作用；
- summary 模型失败时保留结构化焦点、最近 turn 和焦点资源，丢弃更早低优先级文本并记录 warning；
- context 记录损坏时只从带稳定 `candidateIds` 的结构化 timeline payload 重建，不解析自然语言猜测；
- candidate 被删除、版本改变或状态不允许时，领域校验拒绝过期计划；
- context CAS 冲突只重新加载一次；状态已经变化时返回可重试冲突，不循环写入；
- 相同 idempotency key 返回原 receipt，不重复解释、摘要、更新焦点或执行副作用；
- 服务重启后从 SQLite 恢复领域焦点和 timeline，不依赖进程内缓存。

## 10. 数据迁移

使用 additive runtime database migration 新建 `review_curation_context`：

- 新整理会话同步创建空 context；
- 既有整理会话首次访问时，从最新带 `candidateIds` 的可见结构化消息惰性建立焦点；
- 不从普通消息正文反推候选题；
- 新路径上线后删除固定 8 条拼装逻辑，不保留双路径或 feature flag；
- 本迁移只保护当前 R2 数据，不恢复已移除的旧 Runtime 协议。

## 11. 后续 Agent 的复用边界

后续持续对话型 Agent 可以复用 ContextAssembler，但必须定义自己的领域 adapter 和状态 schema：

- 个人信息 Agent 使用 resume/profile item 焦点；
- 岗位 Agent 使用 job/JD/gap/todo candidate 焦点；
- 复盘 Agent 使用 transcript/question/action item 焦点；
- Channel Adapter 恢复对应内部 product session 的领域状态；
- 模拟面试的主 Agent 与子 Agent 使用隔离 thread，只交换结构化总结。

一次性 role Agent 不默认继承完整产品对话。答案评价、题目生成、相似性判断和报告生成只接收本次任务所需的结构化输入，避免重复处理无关历史。

## 12. API 与前端投影

本切片不新增暴露摘要正文的公共 API。现有整理会话资源继续提供用户消息、候选题、运行状态和 context usage：

- `currentContextTokens` 来自实际 assembled input；
- `thresholdTokens` 来自本次模型预算；
- `contextCompacted` 在领域摘要推进或 middleware 真正压缩时标记；
- 前端不得用 timeline 消息条数、累计 usage 或数据库行数推算上下文状态。

明确命令被确定性解析且未调用模型时，可以记录零模型调用和本次解析来源，但不得伪造 token 用量。

## 13. 安全边界

- interpreter/classifier 不拥有发布、删除、Vault 或索引写工具；
- 模型输出只能包含候选选择器、反馈、澄清和无副作用回复；
- workspace/session/run 身份继续由服务端 `AgentContext` 注入；
- summary、trace 和 warning 不记录 Provider secret 或完整 Vault/source 正文；
- 发布、拒绝和重写继续受 summary version、candidate state、idempotency 和现有领域服务约束。

## 14. 测试与验收

### 14.1 单元测试

- ContextAssembler 按 token 预算裁剪并保留完整 turn；
- system/schema/output/tool 预留参与预算；
- 焦点资源优先于普通索引；
- 确定性 parser 覆盖明确序号、范围、唯一焦点和多焦点澄清；
- context repository 覆盖 CAS、幂等和结构化 timeline 重建。

### 14.2 集成测试

- 超过 8 条消息后仍能通过持久焦点理解“这题”；
- classifier 只收到焦点题全文和其他题轻量索引；
- 压缩后保留 candidate ID、备注和未解决事项；
- summary 失败安全降级，硬预算不足返回稳定错误；
- 重启后焦点、摘要游标和命令幂等仍成立；
- 已删除、已拒绝或版本过期焦点不能产生错误副作用。

### 14.3 浏览器验收

1. 查看一题，插入多轮普通交流，再输入“这题发布吧”；
2. 重启服务后恢复同一会话并继续使用指代；
3. 建立多题焦点后输入“这题发布吧”，页面展示澄清且不误发布；
4. context token/阈值/压缩状态与实际调用一致；
5. 默认不配置 Langfuse，业务行为仍完整可用。

实施期间使用针对性测试；跨层接通后最多一次集成回归，最终最多一次全量后端/前端回归和 build。

## 15. 完成标准

- 固定 8 条上下文逻辑被删除；
- `CurationIntentAgent` 命名和职责收敛为命令解释组件；
- 确定性解析优先，LLM classifier 只处理剩余复杂表达；
- 当前焦点、摘要和游标能够持久化、重启恢复和审计；
- ContextAssembler 不含题库领域字段，并有独立单元测试；
- token 用量和压缩状态来自真实 assembled input；
- 领域副作用仍由现有 Graph/application service 确定性执行；
- 针对性、集成、最终回归、build 和浏览器场景均有最新证据。
