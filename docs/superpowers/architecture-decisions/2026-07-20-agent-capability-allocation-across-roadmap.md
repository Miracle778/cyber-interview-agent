# ADR：全路线 Agent 的 Tool、Time Travel 与 Plan-and-Execute 能力分配

- 状态：Accepted
- 决定日期：2026-07-20
- 适用阶段：R0-R8
- 关联路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- 关联设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 关联决定：
  - `docs/superpowers/architecture-decisions/2026-07-15-agent-context-assembly.md`
  - `docs/superpowers/architecture-decisions/2026-07-16-unified-cancellable-execution-runtime.md`
  - `docs/superpowers/architecture-decisions/2026-07-20-domain-agent-tool-and-write-boundaries.md`

## 背景

项目已经实现 R1 Agent Harness 与 R2 复习 Agent，并计划继续建设个人信息、岗位追踪、面试复盘、模拟面试、知识库产品化和外部 Channel。不同 Agent 的任务形态差异很大：有的是一次结构化提取或评价，有的是跨多份材料探索证据，有的是长生命周期领域工作流，还有的是包含多个待确认变更的复杂操作。

`Tool`、`Time Travel` 和 `Plan-and-Execute` 容易被当作 Agent 的通用高级能力统一启用，但这样会混淆以下边界：

- Provider 用 ToolStrategy 返回结构化数据，不等于 Agent 获得业务工具；
- checkpoint 恢复和 SSE 事件回放，不等于允许用户回退并改写历史；
- 显式领域 Graph 执行固定流程，不等于模型拥有自主规划权；
- 用户可见行动计划、模型临时读取计划和内部思维过程不是同一种状态；
- 派生讨论 Session、模拟面试子 Session 和从历史 checkpoint 分叉也不是同一概念。

需要按全部已实现与路线图 Agent 的真实职责分配能力，防止后续阶段复制一个拥有通用读写工具、任意历史分叉和自主执行权的万能 Agent。

## 选择标准

- 能在调用前确定完整、有界输入时，不增加工具循环；
- 证据位置未知时允许按需探索，但只暴露最小只读资源接口；
- 用户资料、题目、掌握度、Todo 和知识发布保持唯一领域状态所有者；
- 重试、取消、恢复和分支不能重复已完成的副作用；
- 用户可理解并审核模型产生的多项变更计划；
- 长流程可恢复，但不把内部 checkpoint 变成用户可直接编辑的业务历史；
- Agent 内部工作状态、可信运行上下文和领域事实具有不同 schema 与持久化所有者；
- 大材料和 Tool 结果可以按引用重载，不通过清空正文制造不可恢复的“假 Offload”；
- R8 Channel 复用 Web 的应用服务和权限，不通过传输层扩大 Agent 能力；
- 能力按真实需求启用，不为了“更 Agentic”而增加成本、延迟和失败面。

## 候选方案

### 方案 A：所有 Agent 使用统一 Tool、Time Travel 和自主 Planner

每个 Agent 都获得搜索、读取、修改、发布工具，允许从任意 checkpoint 继续或分叉，并由通用 Planner 生成和执行步骤。

优点：表面能力统一；原型阶段可以快速组合新任务。

拒绝原因：一次评价和摘要也会进入不必要的循环；模型同时拥有资源选择、写入顺序、停止条件和历史分支；旧 checkpoint 可能重放发布、Todo、掌握度或外部消息；统一能力集扩大隐私、审计、幂等和恢复成本。

### 方案 B：所有 Agent 永远无 Tool、无 Plan、无历史能力

应用层一次性注入全部上下文，所有流程都写成固定 Graph，历史只保留最终产品结果。

优点：权限最小；执行路径确定；易于测试。

拒绝其作为统一方案的原因：R3-R6 的跨材料探索无法在调用前总是确定相关证据；一次性注入全部简历、JD、知识库和复盘材料会放大隐私与 token 成本；多项画像变更和模拟面试编排仍需要用户可见、可验证的结构化计划。

### 方案 C：按任务形态分层分配能力

已知输入的转换、评价、分类和总结 Agent 不使用业务 Tool；证据位置未知的探索 Agent 只使用有界只读 Tool；多项变更使用结构化 proposal 与确定性 executor；长流程使用 checkpoint 恢复和事件回放，但不开放通用 Time Travel；只有 R6 使用固定主从委派。

优点：保留确定性任务的简单性，又覆盖真正需要探索和编排的场景；写入、历史和恢复都有明确状态所有者；能力可以按 role 做 allowlist、预算和验收。

代价：每个阶段必须明确 role、工具和 plan contract；应用服务需要实现 proposal 校验、确认、幂等和逐项结果；不能只注册一组万能工具完成所有功能。

## 决定

采用方案 C。

### 1. 能力分级

#### 1.1 业务 Tool

| 等级 | 含义 | 允许范围 |
|---|---|---|
| `T0` | 无业务 Tool | 应用层注入有界输入；模型只返回文本或结构化输出 |
| `T1` | 有界只读 Tool | 只按稳定资源 ID、版本和 evidence ref 搜索或读取；服务端注入 workspace/scope；限制条数、字节、调用次数和总预算 |
| `T2` | 受控领域命令 | 不是模型可自由调用的 Tool；application/Graph 在校验、确认后执行写入并记录 receipt |

R0-R8 不给领域 Agent 自由写入 Tool。修改、删除、发布、设置主版本、更新掌握度、创建正式 Todo 和发送外部主动消息都属于 `T2`，不进入 ReAct allowlist。`ToolStrategy` 结构化输出不计为业务 Tool。

#### 1.2 Plan-and-Execute

| 等级 | 含义 | 持久化与执行边界 |
|---|---|---|
| `P0` | 无计划 | 一次提取、评价、分类、总结或直接回答 |
| `P1` | 固定领域 Graph | 步骤由代码定义；模型只在指定节点产出结果，不是 Planner |
| `P2` | 结构化变更计划 | 模型输出稳定目标、expected version、evidence 和建议动作；领域服务校验、展示差异、确认后确定性执行 |
| `P3` | 有界只读探索计划 | Agent 可根据只读 Tool 结果选择下一次读取；计划只服务当前 execution，受调用、token、时间、重复和无进展限制 |
| `P4` | 固定委派计划 | 仅用于 R6；主 Agent 生成并冻结模拟面试计划，单一面试子 Agent 在隔离 Session 中执行；不允许任意动态 Agent 生成或递归委派 |

项目不引入通用自主 Planner Agent，也不允许模型生成任意工具名和参数后自行完成领域写入。

`P2` 用户可见计划按以下状态持久化在领域表，而不是只存在于消息或 checkpoint：

```text
proposed
  -> validated
  -> awaiting_confirmation
  -> executing
  -> completed | partial_failure | cancelled
```

只读 `P3` 计划可以只存在于当前 execution/checkpoint；不得展示模型内部思维过程。R4 正式 Todo 是领域资源，不等同于 Agent 的执行计划。

#### 1.3 恢复、回放与 Time Travel

明确区分：

- **checkpoint 恢复**：继续同一未完成 execution；
- **产品事件回放**：重连后重放安全 SSE event，恢复 UI 投影；
- **领域版本历史**：查看简历、画像、题目、JD、复盘或知识文档的不可变版本；
- **Time Travel**：选择历史 checkpoint，修改状态并从该点重新执行或分叉。

R0-R8 核心产品均不需要通用 Time Travel。长流程需要 checkpoint 恢复和事件回放，长期资产需要领域版本；它们不能由 Time Travel 替代。

原因是 checkpoint 可能位于发布、掌握度更新、Todo、文件写入或 Channel 消息之前。重新执行历史节点无法仅凭 checkpoint 证明副作用 exactly-once，也会让当前领域事实与历史 Graph state 分叉。

如果未来确有历史分叉需求，只允许实现“安全派生”：从不可变领域快照创建新的 Session、execution 和 lineage，绝不倒退活动 Session，也不复制 pending action、receipt、active publication、Todo 状态或已发送 Channel 消息。所有新副作用重新走当前版本校验和用户确认。该能力是新的产品功能，不得直接暴露 LangGraph 内部 checkpoint API。

#### 1.4 `state_schema` 准入边界

`create_agent` 未传 `state_schema` 时使用默认 `AgentState`，其核心字段是模型消息、内部跳转和可选结构化响应。多轮消息、普通 Tool call、checkpoint 和 `response_format` 本身不构成自定义 `state_schema` 的理由。

只有一个字段同时满足以下条件时，才进入 role Agent 的自定义 `state_schema`：

1. 字段在同一个 `create_agent` 循环中产生或更新，不是调用前已确定的输入；
2. 后续模型、Tool 或 middleware 步骤必须再次读取它；
3. execution 中断或进程恢复后必须从该值继续，而不是安全地重新计算；
4. 字段只属于该 role Agent 的内部工作过程，不是用户可见领域事实；
5. 字段具有明确的覆盖、追加、去重或计数 reducer，以及可序列化、可脱敏的 checkpoint 表达。

状态归属固定为：

| 数据性质 | 所有者 | 不使用 `state_schema` 的原因 |
|---|---|---|
| 本次问题、简历片段、回答、重写意见 | Agent 输入消息 | 调用前已知，不需要 Agent 内部更新 |
| 最终提取、评价、分类或报告 | `response_format` / 节点返回值 | 它是输出契约，不是循环工作状态 |
| workspace、session、execution、权限和 Tool scope | `context_schema=AgentContext` | 可信、只读、由服务端注入，不允许模型修改 |
| 轮次进度、画像版本、Action Plan、Todo、publication | 外层领域 `StateGraph` 与领域数据库 | 属于产品业务真相，需要版本、事务、HITL 和 receipt |
| 跨 Session 偏好、长期记忆和共享资料 | 领域 Store/repository | 生命周期超出单一 Agent thread |
| 搜索游标、已加载 evidence refs、临时剩余预算、内部 step cursor | 自定义 `state_schema`，仅在满足上述五项时 | 属于可恢复的 Agent 内部循环状态 |

当前 R2 role Agent 不需要自定义 `state_schema`：题目、回答、attempts 和来源片段由应用层组装；轮次、input interrupt、报告和发布进度属于外层 Graph/领域 repository；role Agent 只需默认消息与结构化响应。`AgentFactory` 传入 `context_schema=AgentContext`，但不传 `state_schema`，这是当前状态所有权设计的结果，不是遗漏。

后续阶段按以下规则采用：

- R3-R5 的一次提取、评价、清洗和总结 Agent 继续使用默认 `AgentState`；
- R3-R5 的只读探索 Agent 先使用默认消息 + `T1` Tool；只有真实用例要求在 checkpoint 后恢复搜索游标、已加载 evidence refs 或 unresolved conflicts 时，才新增 role state；
- R3 `ProfileActionPlan`、R4 Todo 和 R5 复盘候选始终是领域资源，不得只保存在 Agent state；
- R6 面试进度、题量、rubric 和终止条件属于外层 `MockInterviewState`；面试子 Agent 默认仍不需要自定义 state；
- 如果字段仅服务一个 middleware，例如 Context Offload 的临时引用或预算，优先由该 middleware 声明自己的 state schema；只有多个 role 节点共同读写时，才由 `AgentSpec` 向 `create_agent(state_schema=...)` 暴露可选 schema。

自定义 Agent state 禁止保存 secret、整份个人材料、完整 Vault 文档、可由 ID 重载的大正文或正式业务状态。checkpoint 中优先只保存稳定引用、游标和恢复必需的紧凑结果。

#### 1.5 Context Offload 边界

Context Offload 定义为：把当前模型上下文中的大段材料、历史消息或 Tool 结果持久化到受控存储，在消息/state 中保留摘要和稳定引用，并允许 Agent 在授权范围内按引用分段重新读取。

当前实现只具备相关基础，不宣称已经完成通用 Context Offload：

- `ProjectingSummarizationMiddleware` 在达到 token/message 阈值时压缩早期消息；这是 compaction，不能按原文引用重载；
- `ContextEditingMiddleware` 默认在高 token 阈值后把旧 ToolMessage 替换为 `[cleared]` 并保留最近结果；它不创建持久 artifact ref，也不能恢复被清理正文；
- R2 生产 Agent 的业务 Tool allowlist 为空，因此旧 Tool 结果清理目前基本不会触发；
- `ContextAssembler` 已把领域事实留在 repository，只按预算组装摘要、最近完整 turn、轻量索引和聚焦资源；这是领域级外置与按需注入，也是 R3 Offload 的直接基础。

采用两层方案：

1. **领域 Evidence Offload，R3 首次落地**：简历、项目文档、博客、研究材料和解析文本保存在 `personal_materials`、材料版本与 evidence span/store 中；Agent 上下文只携带材料 ID、版本、内容哈希、摘要和 evidence ref；`T1` Tool 按稳定 ref 返回有界脱敏片段。
2. **通用 Runtime Artifact Offload，按证据延后**：只有三个以上工具型 Agent 反复产生超预算 Tool 结果，或 R3 真实验收证明领域 evidence ref 无法覆盖中间产物时，才建设共享 artifact 协议。

领域 Evidence Offload 必须满足：

- evidence ref 绑定 workspace、材料 ID、不可变版本、内容哈希和片段范围；
- Tool schema 不接受绝对路径、任意 workspace/scope 或未授权文件名；
- 搜索结果先返回轻量摘要和 refs，精确读取再返回受长度限制的片段；
- 原始敏感正文不进入 trace、产品 event、session metadata 或 Agent title；
- 材料归档、删除和权限变化后，旧 ref 按领域生命周期拒绝读取或只允许审计读取；
- Agent state/checkpoint 只保存 refs、游标和必要摘要，不复制大正文；
- 同一 ref 的重复读取可缓存，但缓存不成为新的领域真相源。

如果未来实现 Runtime Artifact Offload，固定流程为：

```text
large Tool/model intermediate result
  -> server-owned artifact store + content hash
  -> short summary + artifact ref in ToolMessage/Agent state
  -> bounded read_context_artifact(ref, range)
  -> scope, audit, size, TTL and deletion policy
```

Agent 不获得任意 `write_file` scratchpad Tool；artifact 由 middleware 或 Tool handler 依据策略写入。正式画像、题目、Todo、知识文档和用户上传材料不进入临时 artifact store。

启用 `T1` Tool 前必须调整 Context Editing 配置：清理/Offload 阈值按实际模型 context limit 和 role 预算计算，不能继续依赖固定 100k token；工具型 Agent 应优先外置旧 Tool 大结果，再触发整段会话摘要。仅把正文替换为 `[cleared]` 而没有可重读 ref，不计为完成 Offload。

### 2. 已实现 Agent 能力矩阵

| 阶段 / 组件 | 业务 Tool | Plan-and-Execute | 恢复要求 | Time Travel | 决定说明 |
|---|---|---|---|---|---|
| R0/R1 Provider 连通性检查 | 不适用 | `P0` | 无 | 不需要 | 确定性 adapter 调用，不是领域 Agent |
| R1/R2 `review.single` evaluator | `T0` | `P0`；外层为 `P1` | execution checkpoint | 不需要 | 题目、参考答案和用户回答已冻结 |
| R1/R2 `review.single` reporter | `T0` | `P0`；外层为 `P1` | 随宿主 execution | 不需要 | 只消费已验证评价，不检索外部资料 |
| R1 `knowledge.publish` Graph/HITL | 不适用，写入为 `T2` | `P1` | 必须恢复 interrupt、version 和 receipt | 禁止 | 这是确定性领域流程，不是发布 Agent |
| R2 `QuestionCurationAgent` | `T0` | `P0`；整理 Graph 为 `P1` | curation execution checkpoint | 不需要 | 应用层已选择、分片并注入 source excerpts 和相似题摘要 |
| R2 curation command classifier | `T0` | `P2` | 命令 execution 可取消/重试；classifier 自身无长期 checkpoint | 不需要 | 只生成 `CurationCommandPlan`，稳定 ID 解析和副作用由应用服务拥有 |
| R2 curation context summarizer | `T0` | `P0` | 摘要游标和领域焦点持久化 | 不需要 | 摘要不是领域事实，也不是 Time Travel 快照 |
| R2 curation responder | `T0` | `P0` | 当前 execution 的流式临时消息可取消 | 不需要 | 普通回答不获得发布、拒绝、重写工具 |
| R2 相似题模糊判断 worker（按需启用） | `T0` | `P0` | 无独立长期恢复 | 不需要 | 输入是领域层召回的候选对；唯一 reducer 写入 |
| R2 round evaluator / follow-up evaluator | `T0` | `P0`；轮次 Graph 为 `P1` | 轮次 checkpoint 和 input interrupt 必须恢复 | 不需要 | 冻结题目、回答和 supplement 已知 |
| R2 round reporter | `T0` | `P0` | 随轮次恢复 | 不需要 | attempts、settings 和确认报告已由应用层组装 |
| R2 discussion Agent | 当前 `T0`；确有跨知识探索证据后才升级 `T1` | 当前 `P0`；升级 Tool 后为 `P3` | 独立 discussion Session/context | 不需要 | 派生讨论 Session 是上下文隔离，不是 Time Travel |
| session title、role summary 等通用模型辅助 | `T0` | `P0` | 随宿主 Session；失败可降级 | 不需要 | 不拥有领域状态或副作用 |

R2 生产代码继续保持业务 Tool allowlist 为空。设计中预留的 `question_tools`、`discussion_tools` 不代表已经授予权限；只有真实验收证明预组装上下文不足时，才按 role 启用 `T1`。

### 3. R3-R8 待实现 Agent 能力矩阵

#### 3.1 R3 个人信息 Agent

| 组件 | 业务 Tool | Plan-and-Execute | 恢复要求 | Time Travel | 决定说明 |
|---|---|---|---|---|---|
| 材料解析、脱敏、版本登记 | 不适用 | `P1` | 后台 execution 可恢复/重试 | 不需要 | 文件校验、解析、脱敏、索引是基础设施，不是 Agent Tool |
| 结构化简历/画像提取 Agent | `T0` | `P0` | 随材料处理 execution | 不需要 | 只消费当前材料版本和 evidence spans |
| 简历评价与润色建议 Agent | `T0` | `P0` | 建议草稿和来源持久化 | 不需要 | 当前简历、画像和评价标准在调用前已知 |
| 个人资料会话 / 证据探索 Agent | `T1` | `P3` | 长会话 checkpoint + `profile_agent_context` | 不需要 | 可使用个人材料、画像、版本比较和 active knowledge 的最小只读工具 |
| 多项画像修改 / 润色采纳 | 读取为 `T1`，写入为 `T2` | `P2`，必要时先 `P3` | Action Plan、逐项结果、幂等 receipt 持久化 | 禁止 | exact diff 确认后创建新画像/简历版本；确认画像不等于确认发布 |
| 画像推送知识库 | 不适用，发布为 `T2` | `P1` | 独立 `knowledge.publish` execution | 禁止 | 与画像修改分成两次授权 |
| 偏好、长期记忆、Todo 候选提取 | `T0` | `P0` | 候选与来源持久化，失败可降级 | 不需要 | R3 只产生候选，不创建正式 Todo 或静默长期记忆 |

R3 不需要派生子 Session 或 Time Travel。不同简历评估、项目补强和技术栈检查使用共享领域画像事实的同级 `profile.manage` Session；材料版本和 claim 版本承担历史能力。旧会话删除不删除画像事实。

#### 3.2 R4 岗位与 JD 追踪

| 组件 | 业务 Tool | Plan-and-Execute | 恢复要求 | Time Travel | 决定说明 |
|---|---|---|---|---|---|
| JD 解析与结构化提取 Agent | `T0` | `P0` | 随导入 execution | 不需要 | 当前 JD 文本已知 |
| 岗位匹配、优势、风险与缺口分析 Agent | `T1` | `P3` | 分析 execution + 证据快照 | 不需要 | 需要跨 JD、确认画像、题库和 active knowledge 找证据；只读 |
| 岗位持续对话 Agent | `T1` | `P3` | 独立岗位 Session/context | 不需要 | 只读岗位授权范围；不直接改画像、题库或 Todo |
| 准备方案 / 多项下一步建议 | 读取为 `T1`，正式动作是 `T2` | `P2` + `P3` | 用户可见计划和逐项状态持久化 | 禁止 | 模型提出学习范围或 Todo 候选，用户确认后由 Todo Service 创建 |
| Todo 候选提取 Agent/middleware | `T0` | `P0` | 候选、来源和置信度持久化 | 不需要 | 不拥有去重、截止时间、完成、撤销状态机 |
| Todo Service | 不适用，写入为 `T2` | `P1` | 领域 version/receipt | 禁止 | 它是领域服务，不是 Agent |

重新分析旧 JD、旧画像或不同假设时，创建绑定明确版本快照的新 analysis execution；不回退原分析 checkpoint。

#### 3.3 R5 面试复盘 Agent

| 组件 | 业务 Tool | Plan-and-Execute | 恢复要求 | Time Travel | 决定说明 |
|---|---|---|---|---|---|
| 转写清洗、说话人整理、问题推断 Agent | `T0` | `P0`；处理流水线为 `P1` | 长转写处理 execution | 不需要 | 输入是当前转写版本；推断必须单独标记置信度和证据 |
| 回答表现、表达问题和经验候选提取 Agent | `T0` | `P0` | 结构化草稿与证据持久化 | 不需要 | 只分析已选中的转写片段和岗位快照 |
| 跨知识缺口验证 Agent | `T1` | `P3` | 分析 execution + evidence refs | 不需要 | 只读题库、确认画像、岗位和 active knowledge |
| 复盘持续对话 Agent | `T1` | `P3` | 独立 retrospective Session/context | 不需要 | 可以探索证据，不直接改个人资料、题库或知识库 |
| 行动项、关键结论、项目经验候选提取 | `T0` | `P0` | 候选与来源持久化 | 不需要 | 候选进入对应审核区，不自动成为正式资源 |
| 复盘产物选择与发布 | 不适用，写入为 `T2` | 默认 `P1`；若支持复杂自然语言批量选择才使用 `P2` | publication receipt | 禁止 | 发布范围必须可见并独立确认 |

#### 3.4 R6 模拟面试 Agent

| 组件 | 业务 Tool | Plan-and-Execute | 恢复要求 | Time Travel | 决定说明 |
|---|---|---|---|---|---|
| 主 Agent / 面试方案生成 | 预备阶段 `T1` | `P2` + `P4` | 计划冻结为 `MockInterviewPlan` | 不需要 | 只读岗位、JD、画像、题库、知识库和薄弱点；领域服务校验题量、时间、rubric 和预算 |
| 面试子 Agent | `T0` | 执行冻结的 `P4` 计划，并在上限内自适应追问 | 独立 mock Session/thread checkpoint | 不需要 | 不在面试中继续浏览全部资料，避免泄露参考答案和上下文污染 |
| 单题评价 / 风险标记 Agent | `T0` | `P0` | 随 mock Session | 不需要 | 消费冻结问题、回答和 rubric |
| 主 Agent 结束汇总 | `T0` | `P0`；外层 Graph 为 `P1` | 随 mock Session | 不需要 | 只接收结构化面试结果，不接收子 Agent 的完整内部消息历史 |
| 模拟面试后持续讨论 | 必要时 `T1` | `P3` | 独立或同级 follow-up Session | 不需要 | 只读已结束面试证据和授权知识 |
| 总结推送知识库 | 不适用，写入为 `T2` | `P1` | publication receipt | 禁止 | 不由主 Agent 或子 Agent 直接发布 |

R6 的主从关系是固定委派，不是通用 supervisor：只能创建一个受预算约束的面试子 Agent，不能动态生成更多 Agent、递归委派或改变工具权限。用户“重来一次”创建新的 mock Session 并引用同一或新版计划，不从历史 checkpoint 重放。

#### 3.5 R7 知识库与本地产品化

R7 路线中的文档列表、索引重建、外部修改检测、冲突处理、备份、诊断和首页聚合默认是确定性产品能力，不新增领域 Agent，也不需要 Plan-and-Execute 或 Time Travel。

如果 R7 后续明确增加“知识关系探索 Agent”，它只能使用 `T1 + P3`，读取 active knowledge、关系和安全 metadata；冲突写入、覆盖 Obsidian 文件、重建索引和删除文档仍为 `T2 + P1`。查看文件历史使用领域版本和 checksum，不暴露 checkpoint Time Travel。

#### 3.6 R8 微信、飞书原生 Channel

Channel Adapter、账号绑定、签名校验、消息去重、乱序处理、卡片映射和传输重试不是 Agent，不获得业务 Tool、Planner 或 Time Travel。

如果自然语言无法确定目标场景，先使用确定性路由，必要时调用一次 `T0 + P0` 的结构化 classifier。路由器只能返回已有 Agent kind、Session 选择或澄清，不执行领域动作。

Channel 中的复习、复盘和模拟面试完全继承对应内部 Agent 的 Tool、计划、checkpoint、HITL 和发布边界：

- 不增加 Channel 专用 Tool allowlist；
- 不允许消息正文自报 workspace/session/scope；
- 不允许 Channel 回放历史消息来模拟 Time Travel；
- 重复 webhook 通过 event ID 和 idempotency receipt 去重；
- 过期确认不恢复旧 checkpoint 执行，而是返回当前资源状态；
- 主动消息由确定性 Channel service 发送，不作为模型写工具。

### 4. 按能力汇总

#### 4.1 哪些 Agent 需要 Tool

需要 `T1` 的是证据位置无法在调用前完全确定的探索角色：

- R3 个人资料持续对话、跨材料证据探索和复杂画像变更的读取阶段；
- R4 岗位匹配/缺口分析、岗位持续对话和准备方案的读取阶段；
- R5 跨知识缺口验证和复盘持续对话；
- R6 主 Agent 的面试准备阶段，以及按需的面试后讨论；
- 未来如确认建设的 R7 知识关系探索 Agent。

不需要业务 Tool 的是提取、清洗、分类、评价、总结、报告、候选生成、context summary、标题和已知上下文问答。没有任何 R0-R8 Agent 需要自由写入 Tool。

#### 4.2 哪些 Agent 需要 Time Travel

没有任何 R0-R8 核心产品 Agent 需要通用 Time Travel。

- R2 复习和 R6 模拟面试需要 checkpoint 恢复；
- R2-R8 的交互 execution 需要安全事件回放；
- R2 题目、R3 简历/画像、R4 JD/分析、R5 复盘和 R7 文档需要领域版本；
- R2 discussion 和 R6 interviewer 的派生 Session 用于上下文隔离；
- 上述能力都不是 Time Travel。

Time Travel 只保留为未来开发诊断或“安全派生新 Session”的候选能力，不进入当前产品承诺。

#### 4.3 哪些 Agent 需要 Plan-and-Execute

需要受约束 Plan-and-Execute 的场景：

- R2 题库复杂自然语言命令：`P2`，已经采用 `Plan -> Validate -> Execute`；
- R3 多项画像修改、润色采纳和复杂材料操作：`P2`，探索阶段可先用 `P3`；
- R4 岗位准备方案和正式 Todo 候选确认：`P2 + P3`；
- R5 只有在增加复杂自然语言批量选择/迁移时才需要 `P2`，普通复盘分析不需要；
- R6 面试主 Agent：`P2 + P4`，生成冻结计划并委派单一子 Agent；
- 探索型对话 Agent：仅需要 `P3` 的只读短计划，不需要自主写入执行。

其他 Agent 使用 `P0` 或代码定义的 `P1`。项目不建设“所有输入先规划”的通用 Planner。

### 5. 状态所有权与安全约束

- 领域数据库保存材料、题目、attempt、画像 claim、岗位、复盘、Todo、Action Plan、版本、状态和 receipt；
- LangGraph checkpoint 只保存恢复当前 execution 所需的紧凑 Graph/role 状态；
- Vault 保存用户确认后的长期 Markdown，不保存 Agent 临时执行计划；
- 产品 timeline 保存用户可见消息和稳定资源引用，不作为领域事实真相；
- `P2` Action Plan 一旦跨 execution、需要用户确认或具有逐项结果，就必须保存到领域表；
- `P3` 临时读取顺序不得被宣传为 Chain of Thought，也不得进入可观测性正文；
- 历史 fork 不复制 secret、临时工具结果、pending action、receipt 或 active side effect；
- 自定义 `state_schema` 只保存 role Agent 内部可变工作状态；业务事实、可信权限和跨 Session 记忆分别归领域层、`context_schema` 和 Store；
- Context Offload 优先使用领域 evidence ref；通用 artifact store 未满足复用触发条件前不建设；
- 每个 `T1` role 必须有独立 allowlist、scope、调用/结果/token/时间上限、审计和 no-progress 保护；
- Tool 结果只能返回完成当前任务所需字段，并优先返回 evidence ref 而不是整份个人材料；
- 任何模型 plan 都不能扩大用户在提交时选择的资源集合或权限 scope。

## 结果

正向结果：

- 现有 R2 不需要为了后续阶段改造成通用 ReAct Agent；
- R3-R6 真正需要探索的角色获得最小只读能力；
- 写入、发布、Todo 和外部消息继续具有稳定版本、确认、幂等和恢复边界；
- checkpoint 恢复、领域版本、派生 Session 和 Time Travel 的语义不再混用；
- R6 获得足够的主从编排能力，但不会引入通用 supervisor；
- `state_schema`、`context_schema`、外层 Graph state 和领域事实形成明确准入规则；
- R3 可以通过 evidence ref 控制个人材料上下文，不需要先建设通用 Agent scratchpad；
- 每个未来阶段 spec 可以直接引用矩阵，再根据真实用例收窄 role allowlist。

负向结果与风险：

- R3-R6 需要建设多组 ID/evidence-ref 驱动的只读工具和领域 adapter；
- `P2` 会增加 Action Plan、逐项结果、版本冲突和部分失败测试；
- R3 Evidence Offload 需要材料版本、片段引用、脱敏查询和引用失效测试；
- 不预建通用 Artifact Offload 意味着首批工具型 Agent 仍需通过领域 adapter 控制中间结果大小；
- 不提供通用 Time Travel 后，用户不能任意回退 Agent 对话并改变历史结果，需要通过新版本或新 Session 表达重做；
- 如果未来统一入口需要跨 Agent 路由，仍需单独设计，不能把现有 classifier 扩成万能 supervisor；
- 矩阵是阶段默认值，未来 spec 仍需用真实用例验证，不能仅凭本 ADR 自动授予 Tool。

## 重新评估条件

满足任一条件时重新评估对应能力，而不是整体放开：

- 某个 `T0` role 的真实验收反复证明，应用层无法在合理 token 预算内确定相关证据；
- 三个以上 `T1` role 出现相同安全查询，需要提取共享只读资源协议；
- 三个以上工具型 Agent 产生无法由领域 evidence ref 表达的大型中间结果，需要共享 Runtime Artifact Offload；
- 某个 role 在 checkpoint 恢复时必须延续消息之外的 Agent 内部可变状态，需要给 `AgentSpec` 增加可选 `state_schema`；
- 固定 Context Editing 阈值在真实模型窗口下频繁晚于 hard limit 或早于有效摘要时，需要按 role/model 重新校准；
- 官方 Runtime 提供可验证的事务化、exactly-once Tool 副作用和恢复协议；
- 用户对“从某个历史状态创建分支”的需求无法由领域版本 + 新 Session 满足；
- R6 固定单子 Agent 无法覆盖真实模拟面试，而必须出现多个独立、并行、可审计的专业面试角色；
- R8 出现管理员授权的批量跨 Agent 操作，需要新的角色权限、selection snapshot 和确认协议；
- 通用 Planner 的收益经过至少三个领域的重复模式证明，且不会吸收领域状态机、HITL 或副作用所有权。
