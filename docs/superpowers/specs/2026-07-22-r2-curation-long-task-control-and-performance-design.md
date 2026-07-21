# R2 题目整理长任务控制与性能设计

- 状态：已确认
- 日期：2026-07-22
- 适用范围：R2 题目整理，R3 及后续长任务复用同一状态边界
- 关联设计：`2026-07-21-r2-progressive-question-curation-design.md`
- 关联 ADR：`../architecture-decisions/2026-07-22-resumable-agent-task-boundary.md`

## 1. 背景

R2 已把题目整理从一次大型结构化输出拆为 discovery、enrichment 和持久 work item。真实材料验证了单元级失败恢复，但也暴露了三个问题：

1. 页面没有实时显示 Agent 已运行时间；
2. 约 39,570 字的材料被拆为 797 个 section、133 个 discovery 单元，再产生约 45 个 enrichment 单元，近 180 次 Provider 调用基本串行；
3. 通用 Execution 可以取消，但初次整理没有完整的暂停、终止、恢复和领域状态对账。

JSONL Agent Trace 另有一个可读性问题：权威时间使用 UTC，直接查看时需要手动换算北京时间。

本设计保留“两阶段结构化输出 + 持久 work item”的正确方向，修正过细分块、串行调度和控制状态缺口。

## 2. 目标

- 运行中实时展示本次耗时，终态冻结耗时，刷新后继续正确计时；
- Batch 保存长任务状态，Execution 只表示一次运行尝试；
- 暂停保留进度并允许继续，终止关闭 Batch 且不可继续；
- failed、paused、interrupted 从原 Batch 和未完成 work item 恢复；
- 结构明确的题目材料优先确定性识别题目边界；
- 普通文章使用较大语义窗口进行 LLM discovery；
- discovery 和 enrichment 最多各并发 3 个 Provider 请求；
- 候选补全结果逐单元落库并渐进展示，最终去重后才开放确认和发布；
- JSONL 同时提供 UTC 权威时间和北京时间可读字段。

## 3. 非目标

- 不引入通用工作流引擎、分布式任务队列、Time Travel 或动态 Supervisor；
- 不允许模型决定重试、并发、停止条件或领域状态；
- 不改变候选确认、知识发布、HITL 和题目生命周期边界；
- 不承诺 Provider 请求严格只调用一次；网络结果不确定时允许重发当前未提交 work item；
- 不让处理中、尚未最终归并的候选进入确认或发布。

## 4. 状态所有权

| 对象 | 职责 |
|---|---|
| `agent_runs` / Execution | 一次具体运行尝试、模型配置、开始结束时间和运行终态 |
| Question Batch | 可暂停、可恢复、可终止的领域长任务 |
| Curation Work Item | 最小恢复断点、输入摘要、严格结构化输出和尝试次数 |
| Curation Session | 面向页面的阶段、进度、控制能力和最近活动 Batch 投影 |
| LangGraph Checkpoint | 当前 Graph 编排位置，不拥有正式 Batch 或候选事实 |
| 前端本地状态 | 秒表刷新、展开、筛选和未提交输入 |

Execution 完成、失败或取消不直接等于整个 Batch 完成、失败或终止。恢复总是创建新 Execution，并绑定原 Batch；completed work item 不重放。

## 5. 长任务状态机

Batch 使用以下状态：

```text
generating
  ├─ pause request     → paused
  ├─ process exit      → interrupted
  ├─ provider/error    → failed
  ├─ terminate request → terminated
  └─ reduce complete   → review_pending

paused | interrupted | failed
  ├─ resume            → generating
  └─ terminate         → terminated

review_pending → completed
```

`terminated` 是不可恢复终态。再次整理相同材料必须创建新 Batch。

### 5.1 暂停

1. 持久化带幂等键和 expected version 的 pause 请求；
2. 当前 Execution 进入 `cancelling`；
3. 停止读取 Provider 响应并取消本地 task；
4. 已经严格校验并提交的 work item 保持 completed；
5. 未提交的当前 work item 标记为可重试中断；
6. Batch 原子进入 `paused`。

页面先显示“正在暂停…”，收到领域终态后显示“已暂停”。Provider 取消是 best-effort，已经发送的 token 可能仍被计费。

### 5.2 恢复

恢复只接受 `paused`、`interrupted` 或 `failed`：

1. 把遗留 running work item 转为可重试状态；
2. 创建新 Execution 并记录恢复原因；
3. 绑定原 Batch 和不可变输入；
4. 跳过所有 completed work item；
5. Batch 进入 `generating`。

### 5.3 终止

终止先持久化控制意图，再取消活动 Execution，最终把 Batch 设置为 `terminated`。completed work item 只保留为本地审计事实；`resume` 对 terminated Batch 固定返回 `409 Conflict`。

### 5.4 重启恢复

服务启动时统一对账：

- 活动 Execution 已 interrupted 且没有控制意图：Batch 转 `interrupted`；
- 已持久化 pause 意图：Batch 转 `paused`；
- 已持久化 terminate 意图：Batch 转 `terminated`；
- 孤立 running work item 转为可重试中断；
- completed 输出保持不变。

## 6. 结构感知混合流水线

### 6.1 稳定原子 section

继续保留现有标题、空行、编号、问句和 2,000 字符硬上限，用于生成稳定 source ref 和证据定位。原子 section 不再直接决定 Provider 调用次数。

### 6.2 规则优先题目边界

确定性代码先识别明确题目锚点：问句标题、编号题目、Markdown/加粗题目标题。一个锚点到下一个锚点形成题目范围，并直接产生 question seed；规则只识别边界，不生成答案。

`QuestionSeed` 从单一 `source_ref` 扩展为一个主锚点和有界 `source_refs`。主锚点标识题目标题，引用列表覆盖该题直到下一题之前的解释、代码和答案片段；所有引用必须属于当前 work item，顺序稳定且不得跨来源。LLM discovery 使用相同契约，因此后续 enrichment 不会因结构化快速路径而丢失题目正文。

每段原文必须进入覆盖表，状态只能是：

- `deterministic_seed`：明确题目范围；
- `llm_discovery`：没有明确题目结构的普通文本窗口。

不得静默丢弃未覆盖内容。重叠锚点使用稳定 source ref 和 digest 归一化。

### 6.3 普通文本 Discovery

未覆盖文本按语义边界打包为最多约 6,000 字符的窗口，不再设置“每 6 个 section 强制切包”。窗口仍受模型上下文预算和稳定 input digest 约束。

结构化材料可以跳过绝大多数 discovery 模型调用；普通约 4 万字文章预期产生约 7–10 个 discovery work item，而不是 133 个。

### 6.4 Enrichment

Enrichment 继续每次最多补全 3 个 seed，保持 4,096 visible output token 上限。每次只携带当前 seed、对应证据和经过确定性预筛选的有界相似题，不再依赖前面所有 enrichment 输出。

跨 work item 重复由最终 reducer 统一合并，因此 enrichment 可以安全并发。

## 7. 有界并发调度

- discovery 默认最多 3 个活动 work item；
- enrichment 默认最多 3 个活动 work item；
- 每个 work item 使用独立稳定 thread、输入摘要和状态条件；
- 每个 worker 完成后立即验证并提交自己的输出；
- 一个 worker 失败时，其他已运行 worker 继续完成并保存；调度波次结束后再把 Batch 转 failed；
- 429、明确 Provider 过载或 `Retry-After` 会临时把并发降为 1；
- 429/5xx/网络错误最多自动重试一次；结构校验错误不自动重试；
- discovery 超时为 90 秒，enrichment 超时保持 180 秒。

Provider 调用属于至少一次语义。领域提交通过 `pending|failed|interrupted → running → completed` 条件更新、input digest 和不可变 completed output 达到精确一次效果。

## 8. 渐进候选

每个 enrichment work item 成功后立即提供经过 Schema 校验的只读候选预览和累计数量。预览使用 work item ID 与候选 ordinal 形成稳定临时标识。

最终 reducer 完成前：

- 可以查看已生成候选；
- 不允许确认、编辑后确认、发布或建立正式 draft；
- 页面明确标记“处理中预览”。

全部 work item 完成后，reducer 做跨单元去重、证据合并和稳定排序，再由现有应用服务创建正式 candidate/draft。

## 9. 数据调整

Runtime additive migration 需要：

1. 扩展 `review_question_batches.status`：`generating | paused | interrupted | review_pending | completed | failed | terminated`；
2. 扩展 `review_curation_sessions.stage`：加入 `paused | interrupted | terminated`；
3. 为 Batch 增加乐观版本和持久控制意图；
4. 新增 Batch–Execution 尝试关系，记录 execution、ordinal、start reason 和创建时间；
5. 扩展 work item 状态或错误码，使 pause、process interruption 和 provider failure 可区分；
6. 保留当前 `run_id` 作为最近 Execution 兼容投影，不再把它当完整历史。

累计处理耗时由关联 Execution 的有效运行区间计算，不包含 paused 等待时间。数据库和 API 的权威时间仍使用带时区 UTC ISO 时间。

## 10. API 与事件

新增领域控制 API：

```http
POST /api/review/curation-sessions/{id}/pause
POST /api/review/curation-sessions/{id}/resume
POST /api/review/curation-sessions/{id}/terminate
```

请求必须包含 `Idempotency-Key` 和 `expectedBatchVersion`。现有 `/retry` 作为兼容入口委托给 resume。

`CurationSessionResource` 增加：

```text
batchStatus / batchVersion
progress.phase / completed / total / generatedCandidateCount / activeWorkers
timing.currentElapsedMs / cumulativeElapsedMs
controls.canPause / canResume / canTerminate
provisionalCandidates[]
```

继续使用现有 session SSE。`curation.progress.changed` 在并发完成时发布单调计数；控制状态通过安全的 curation control/stage event 投影，不包含正文、Provider 响应或模型推理。

## 11. 前端交互

运行卡展示当前阶段、完成单元、已生成候选和实时本次耗时。秒表由服务端 started timestamp 加前端本地 tick 计算，不需要每秒请求后端；终态使用 finished timestamp 或服务端累计值冻结。

运行中提供主操作“暂停整理”，更多操作中提供危险的“终止整理”。状态行为：

- `pausing`：显示“正在暂停…”，禁止重复提交；
- `paused`：显示“继续整理”和“终止整理”；
- `failed`：显示失败原因、“继续整理”和“终止整理”；
- `interrupted`：说明服务中断，提供“继续整理”；
- `terminated`：只说明已终止，不提供恢复；
- `review_pending/completed`：冻结耗时和最终进度。

暂停、失败、终止使用不同图标、文案和语义色。进度、秒表和控制结果使用适当 `aria-live`，但每秒 tick 不反复播报给屏幕阅读器。

## 12. JSONL 时间语义

Trace schema v2 新写入行同时包含：

```json
{
  "schema_version": 2,
  "timestamp": "2026-07-21T16:30:00.123+00:00",
  "local_timestamp": "2026-07-22T00:30:00.123+08:00",
  "timezone": "Asia/Shanghai"
}
```

- `timestamp` 是权威 UTC 时间，用于排序、关联和机器处理；
- `local_timestamp` 是北京时间可读投影；
- `timezone` 明确转换来源；
- 旧 schema v1 行继续可读，不重写历史文件；
- latency/duration 使用单调时钟测量，不能通过两个本地时间字符串相减。

## 13. 竞争与错误处理

- 暂停、终止和自然完成竞争时，通过 Batch version 和条件更新决定唯一终态；
- 已经 completed 的 work item 不因随后到达的取消请求回滚；
- Provider 返回后、提交前收到暂停时，只有完整校验并成功条件提交的结果才算完成；
- 同一 Batch 同时最多一个活动 Execution；
- 多标签页重复控制由幂等 receipt 返回原结果；
- provisional candidate 不是领域正式候选，不进入发布、上下文或知识库；
- Trace 写入继续 fail-open，不影响业务状态。

## 14. 测试与验收

### 14.1 纯函数与质量

- 明确题目锚点无需 discovery 模型调用；
- 未覆盖文本全部进入 LLM 窗口；
- 约 4 万字无结构文本形成约 7–10 个窗口；
- 稳定 ref/digest 在重试后不变化；
- 结构规则不会把答案列表统一误判为独立问题。

### 14.2 并发与恢复

- fake Provider 屏障证明最大活动调用不超过 3；
- 完成顺序不同不会让 completed 计数倒退；
- 一个 worker 失败时，其他成功结果仍提交；
- 暂停、失败和进程中断恢复后，completed work item 调用次数不增加；
- terminated resume 返回 409；
- 取消和自然完成竞争只有一个终态；
- 重启对账不留下 running work item。

### 14.3 API 与前端

- pause/resume/terminate 幂等、expected version 冲突和权限边界；
- SSE 重放顺序、刷新恢复和渐进候选；
- fake timer 验证运行中计时、终态冻结、暂停不累计和恢复后累计；
- 按钮、颜色、状态文案和无障碍语义互不混淆；
- 处理中预览不能确认或发布。

### 14.4 Trace

- 新行含 UTC、`+08:00` 本地时间和 `Asia/Shanghai`；
- UTC 与本地时间表示同一瞬间；
- v1/v2 混合文件可读取且 sequence 单调；
- duration 使用单调时钟；
- 时间字段变更不扩大正文或凭据暴露。

### 14.5 真实验收

使用已授权材料记录旧/新 discovery 单元数、Provider 调用数、首个候选时间、总耗时、暂停响应、恢复调用数和最终候选数。完整正文和 Provider 响应只保留在受控本地 Trace，不进入验收文档。

## 15. 成熟度与复用边界

R2 首先实现领域 Batch adapter，不提前建设通用 `LongTask` 数据表。共享的是状态语义和 Execution/领域任务/work item 三层边界。

R3 `profile.ingest` 后续以 MaterialVersion 作为领域长任务、Evidence/Proposal receipt 作为恢复事实，采用相同暂停、终止、恢复规则。出现第三个真实领域后，再评估是否抽取通用 application protocol。
