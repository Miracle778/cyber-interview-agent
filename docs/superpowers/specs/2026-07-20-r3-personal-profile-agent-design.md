# R3 个人画像 Agent 设计规格

日期：2026-07-20

状态：方案已确认，待文档复核
产品阶段：R3 个人材料、结构化画像与知识发布

## 1. 背景

R0-R2 已建立 Workspace、Provider、统一 Agent Runtime、Session、Execution、LangGraph checkpoint、可重放产品事件、HITL、知识草稿与发布，以及题库和复习闭环。R3 在这些能力上建设个人画像，不另建一套 Agent Runtime。

个人画像不是由模型自由维护的一段简历文本，而是由不可变材料版本、可定位证据、用户确认的结构化事实、修改提案、执行回执和知识发布版本共同组成的长期领域资产。

R3 必须解决以下风险：

- 模型不能把推断或润色直接写成用户事实；
- 删除或替换简历不能让 Evidence、Claim 与已发布知识失去可解释关系；
- 长简历和多份材料不能全部塞进会话 checkpoint；
- 连续对话需要按需读取个人材料，但不能访问任意路径或扩大 Workspace scope；
- 多项修改、批量确认和发布必须支持精确 Diff、幂等、停止、部分成功与恢复；
- 画像确认与知识发布必须保持两次独立授权。

本规格遵守既有的 Agent Context Assembly、统一可取消执行 Runtime、Agent Tool/写入边界和全路线能力分配 ADR。

## 2. 目标

R3 第一里程碑交付完整的简历纵向闭环：

```text
上传简历
→ 创建不可变版本
→ 解析为 Evidence
→ 提取 Claim 候选
→ 用户逐项审核
→ Agent 评估、润色和连续讨论
→ 用户确认精确修改
→ 用户选择发布范围
→ 独立确认知识发布
→ Active Knowledge
```

完成后必须满足：

- 原始简历、材料版本、Evidence、Claim、Proposal 和发布版本相互可追溯；
- 未确认候选不能成为正式画像；
- 未确认画像不能自动发布；
- 已确认画像可以稳定提供给 R4-R6；
- Session、Execution、Checkpoint 与领域事实职责清晰；
- 长材料使用 Evidence Offload，而不是长期占用消息上下文；
- 用户可以观察执行、停止、重试、刷新和恢复。

## 3. 非目标

R3 第一里程碑不实现：

- 通用自主 ReAct 写入、通用 Time Travel、通用自主 Planner 或动态 Supervisor；
- 任意文件读写 Tool、扫描 PDF OCR、向量数据库；
- GitHub OAuth 与持续同步、博客站点自动爬取；
- 自动修改长期记忆、正式 Todo 执行系统；
- 自动发布个人知识、自动删除或覆盖旧 Claim；
- 从画像会话派生子会话；
- 跨 Workspace 或跨用户材料访问。

## 4. 总体架构决定

### 4.1 Claim/Evidence 中心模型

R3 采用 Claim/Evidence-centric 架构，不采用文档中心或会话中心架构。

```text
PersonalMaterial
  → PersonalMaterialVersion
    → EvidenceSpan
      → ProfileClaimVersion
        → ProfileProposal / ProfileActionPlan
          → PublicationSelection
            → KnowledgeDraft
              → ActiveKnowledge
```

文档中心难以表达同一事实跨版本、跨材料的支持和冲突；会话中心会让正式画像依赖消息历史和 checkpoint 生命周期。Claim/Evidence 模型可以独立管理来源、确认、冲突、版本和发布状态。

### 4.2 写入边界

R3 Agent 不获得更新/删除 Claim、删除材料、设置主简历、发布知识、写任意文件、创建 Todo 或修改长期记忆的 Tool。

领域变更统一经过：

```text
模型生成结构化 Proposal
→ 服务端验证
→ 固化不可变输入快照
→ 生成精确 Diff
→ 用户显式确认
→ 确定性领域服务执行
→ 保存逐项 Receipt
```

### 4.3 Time Travel 与 Plan-and-Execute

R3 不建设通用 Time Travel。Execution 恢复由 checkpoint 承担，页面回放由持久 Event cursor 承担，材料和画像历史由领域版本承担，重做任务通过不可变快照上的新 Execution 表达。

R3 只采用受约束 Plan-and-Execute：固定领域 Graph；复杂多项修改生成结构化 `ProfileActionPlan`；用户选择并确认计划项目；确定性执行器逐项执行。模型不能自由规划无限步骤或直接执行写操作。

## 5. 领域模型

### 5.1 PersonalMaterial

```text
id
workspace_id
type: resume | github | blog | research | project_document
title
primary_role
current_version_id
lifecycle_status: active | archived
version
created_at
updated_at
```

第一里程碑实现 `resume`。同一 Workspace 同一 `primary_role` 最多指向一份活动材料。

### 5.2 PersonalMaterialVersion

```text
id
material_id
version_number
source_type: upload | derived_draft
file_name
mime_type
content_sha256
storage_ref
processing_status
derived_from_version_id
created_by
created_at
```

处理状态：

```text
uploaded → parsing → parsed → extracting → ready
                     ↘ parse_failed / extraction_failed
```

版本不可原地修改。AI 润色只能创建 `derived_draft` 派生版本，经用户确认后才能成为正式版本或主简历。

### 5.3 EvidenceSpan

```text
id
material_version_id
section
start_offset
end_offset
sanitized_text
content_sha256
sensitivity
created_at
```

Evidence 必须绑定不可变版本。Agent 上下文默认只保存 Evidence ID、类型和摘要；正文通过只读 Tool 有界加载。删除原始内容后，Evidence 变为 tombstone，不保留可恢复敏感正文。

### 5.4 ProfileClaim 与 ProfileClaimVersion

`ProfileClaim` 是稳定逻辑事实：

```text
id
workspace_id
claim_type
current_confirmed_version_id
version
created_at
updated_at
```

第一里程碑支持 skill、project、experience、education 和 link。

`ProfileClaimVersion`：

```text
id
claim_id
value
status: proposed | confirmed | rejected | superseded
support_status: supported | conflicted | unsupported
evidence_refs[]
source
expected_previous_version
created_at
confirmed_at
```

`status` 表示用户决定，`support_status` 表示证据状态。原材料永久删除后，用户确认过的 Claim 可以保持 `confirmed`，但必须转为 `unsupported`。新材料与现有 Claim 冲突时创建候选版本和冲突关系，不自动覆盖已确认版本。

### 5.5 ProfileProposal

```text
id
proposal_type
target_claim_id
base_claim_version_id
proposed_value
reason
evidence_refs[]
status: pending | accepted | rejected | superseded
created_by_execution_id
created_at
```

评估、润色和一致性检查只生成 Proposal。用户可以直接接受或编辑后接受；编辑值形成新 Claim Version，并保留与原 Proposal 的关系。

### 5.6 ProfileActionPlan

```text
id
session_id
execution_id
request_summary
base_profile_version
selection_snapshot
items[]
status
version
expires_at
created_at
```

模型先产生尚未持久化的 `ProfileActionPlanProposal`。服务端校验通过后才创建领域 `ProfileActionPlan`。状态机与全路线能力 ADR 保持一致：

```text
proposed → validated → awaiting_confirmation → executing
                                                ├─ completed
                                                ├─ partially_completed
                                                ├─ failed
                                                └─ cancelled
```

如果目标 Profile 或 Claim 版本变化，计划进入 `expired`，必须重新计算 Diff。

Item 至少包含 `item_id`、operation、target、expected_version、before、after、evidence_refs、status、receipt_id 和 error_code。

### 5.7 PublicationSelection

```text
id
workspace_id
claim_version_ids[]
excluded_sensitive_fields[]
profile_version
status
created_at
```

发布选择独立于 Claim 确认，并进入已有 Knowledge Draft/HITL/Publication 流程，不能直接写入 Active Knowledge。

## 6. 存储与状态所有权

| 状态 | 所有者 |
|---|---|
| 原始文件 | Workspace 私有内容寻址材料存储 |
| 材料元数据与版本 | Personal Material Repository |
| Evidence 与引用 | Evidence Repository |
| Claim、Proposal、Action Plan、Receipt | Profile Repository |
| 当前 Material/Claim/Proposal 焦点 | `profile_agent_context` 领域投影 |
| Session 正式消息 | `agent_messages` |
| Execution 与可重放产品事件 | Agent Runtime Repository |
| Agent 循环消息与中断点 | LangGraph checkpoint |
| Tool 安全审计 | `tool_audits` |
| Knowledge Draft、Publication、Active 投影 | Knowledge 领域 |
| 页面筛选、展开和未提交输入 | 前端本地状态 |

Checkpoint 不保存完整简历、完整画像、正式 Action Plan 或发布选择。删除 Session 不删除材料、Claim、Proposal Receipt 或知识资产。

原文件使用内容哈希生成不可猜测存储引用，位于 Workspace 私有材料目录，不进入 Knowledge Vault，不允许模型传入任意路径读取。

## 7. Context Offload

R3 实现领域 Evidence Offload，而不是通用运行时 Artifact Offload。

上下文装配优先顺序：

1. 当前用户请求；
2. 当前焦点 Material、Version、Claim、Proposal 的稳定 ID；
3. 已确认画像的有界摘要；
4. 相关 Evidence 摘要和引用；
5. 最近完整对话 turn；
6. 持久化结构化会话摘要；
7. 只读 Tool 按需加载正文。

第一版不引入向量数据库。Resume 范围内使用材料、版本、章节、Claim 类型、稳定引用和有界关键词检索；多来源语义检索出现真实需求后再评估向量索引。

## 8. Agent 角色

| Agent | 模型用途 | 输入/输出 | Tool | State |
|---|---|---|---|---|
| `profile_extraction` | 新增同名绑定 | 指定版本/Evidence → Claim 候选 | 无 | 默认 `AgentState` |
| `profile_assessment` | 新增同名绑定 | 材料/Claim 快照 → Assessment/Proposal | 无 | 默认 `AgentState` |
| `profile_chat` | 复用 `agent_chat` | 会话与领域焦点 → 最终回答 | 最小只读 allowlist | 默认 `AgentState` |
| `profile_action_planner` | 先复用 `profile_assessment` | 修改请求/快照 → Action Plan Proposal | 默认无，必要时最小只读 | 默认 `AgentState` |

`ProfileActionPlan` 是领域数据，不属于 `AgentState`。Planner 不持有跨 Execution 隐藏计划，也不执行写操作。

## 9. Graph 设计

### 9.1 profile.ingest

后台 Graph，每个材料版本一条 Execution，不创建用户可见的对话 Session。为复用现有 Execution/Event/Tool Audit 的 Session 外键和恢复能力，Runtime 内部为每个材料版本创建隐藏的 `profile.ingest` system session；它不进入画像会话列表、不保存对话消息，也不接受用户聊天输入。

```text
校验文件
→ 保存不可变版本
→ 确定性解析、脱敏和切片
→ 保存 Evidence
→ profile_extraction
→ 校验 Evidence 引用
→ 幂等保存 Claim 候选
→ ready / failed
```

解析失败保留版本；提取失败保留 Evidence。重试从已持久化安全阶段继续，不重复上传、Evidence 或 Claim。

### 9.2 profile.assess

```text
锁定 Material/Claim 快照
→ profile_assessment
→ 校验结构化输出
→ 幂等保存 ProfileProposal
→ 投影会话卡片
```

失败不创建正式 Claim，也不留下半完成 Proposal。

### 9.3 profile.manage

```text
持久化用户消息和领域焦点
→ 安全路由
   ├─ 简单问答：profile_chat
   ├─ 明确单项命令：确定性领域命令
   └─ 多项复杂修改：profile_action_planner
                          ↓
                    ProfileActionPlan
                          ↓
                     用户显式确认
                          ↓
                    确定性执行器
```

停止只停止当前 Execution。未完成流式输出不作为正式消息进入后续上下文，已确认领域事实不受 Execution 失败影响。

### 9.4 knowledge.publish

复用既有发布边界：

```text
PublicationSelection
→ 发布预览
→ Knowledge Draft
→ 独立 HITL
→ Vault Version
→ Active Knowledge
```

不创建能够自行发布知识的 Profile Publish Agent。

## 10. Tool 设计

第一里程碑定义以下只读 Tool：

- `list_personal_materials`
- `search_personal_materials`
- `read_personal_evidence`
- `get_profile_claims`
- `get_profile_claim_evidence`
- `compare_material_versions`
- `search_active_knowledge`
- `get_profile_publication_status`

`profile_extraction` 和 `profile_assessment` 无 Tool；`profile_chat` 按任务获得材料、Evidence、Claim、版本对比及知识状态的最小子集；Planner 默认消费已装配上下文，确需补证时才使用最小只读子集。

Tool Schema 只包含业务查询参数。`workspace_id`、`session_id`、`run_id`、`allowed_tools` 和 `allowed_scopes` 由服务端 `AgentContext` 注入，模型不能覆盖。Tool 必须验证稳定资源 ID 属于当前 Workspace。

每个 `profile_chat` Execution 默认最多 6 次 Tool Call；相同 Tool 与规范化参数最多 2 次；单次结果有条目数和正文长度上限；超限后必须回答、澄清或安全失败。No Progress Middleware 将 Tool 名称和规范化参数纳入指纹。

Tool 返回统一 envelope：

```json
{
  "status": "ok",
  "items": [],
  "evidenceRefs": [],
  "truncated": false,
  "nextCursor": null
}
```

失败使用稳定错误码，不返回数据库异常、路径、Provider 原文或 secret。

## 11. Message、Event 与 Tool Audit

### 11.1 Agent 协议消息

R3 直接使用 LangChain 标准 `HumanMessage`、`AIMessage`/`AIMessageChunk`、`AIMessage.tool_calls` 和 `ToolMessage`，不建立平行协议。

`create_agent` 负责：

```text
模型接收 Tool Schema
→ AIMessage 产生 tool_calls
→ Middleware 校验权限和 HITL
→ 标准 Tool 执行
→ ToolMessage 回到消息状态
→ 模型继续生成或再次调用 Tool
```

`ToolStrategy(response_format)` 可能利用 Provider Tool Calling 生成结构化输出，但不是业务 Tool，不产生业务 Tool Audit 或产品 Tool Event。

### 11.2 产品 Message

产品 `MessageRecord` 只保存用户可见的正式请求、完成后的 Agent 回答和 Claim/Proposal/Action Plan/Receipt 等 typed card。内部 ToolMessage、模型原始结构化 JSON 和未完成流式文本不直接保存为正式产品 Message。

### 11.3 产品 Event

R3 新增：

```text
profile.ingest.parsing
profile.ingest.extracting
profile.claims.proposed
profile.action_plan.created
profile.action_plan.item_completed
agent.tool.started
agent.tool.completed
agent.tool.failed
```

Tool Event payload 只允许 execution_id、tool_call_id、tool_name、purpose、status、result_count 和 error_code。原始参数、简历/Evidence 正文、Tool 原始结果、Provider 请求响应、敏感 Profile 值和模型推理不得进入 Event。

UI 将其显示为“正在检索个人材料”“已对比两个简历版本”等安全阶段。完整审计只在运行详情或开发诊断中查询。

### 11.4 Tool Audit

Tool Policy Middleware 在执行前后保存：

```text
audit_id
execution_id
tool_call_id
agent_role
tool_name
status: started | completed | failed | denied
resource_scope
input_digest
result_digest
latency_ms
error_code
created_at
finished_at
```

Audit 保存摘要和哈希，不保存敏感 Tool 原始输入输出。

## 12. Session、Execution 与 Checkpoint

| 对象 | Thread ID |
|---|---|
| `profile.manage` 外层 Graph | `<session_id>` |
| `profile_chat` | `<session_id>:profile_chat` |
| `profile_assessment` | `<session_id>:profile_assessment` |
| `profile_action_planner` | `<execution_id>:profile_action_planner` |
| `profile.ingest` | `<material_version_id>` |
| `profile_extraction` | `<material_version_id>:profile_extraction` |

多个兄弟 `profile.manage` Session 共享领域事实但不复制 checkpoint；上传、解析和提取没有用户可见 Session，只使用与材料版本绑定的隐藏 system session 承载 Runtime 事实；Planner 不保留跨 Execution 隐藏计划；删除用户会话不删除领域资产。

第一版所有 role Agent 使用默认 `AgentState`。只有出现同一 Agent loop 内产生、后续步骤消费、必须随 checkpoint 恢复且不属于领域事实的状态时，才新增自定义 `state_schema`。

## 13. 页面与用户流程

### 13.1 个人画像总览

展示主简历/当前版本、画像完整度、待审核/冲突/无证据 Claim、润色建议、知识发布覆盖和最近兄弟会话。

### 13.2 材料与版本管理

支持 PDF、DOCX、Markdown 上传，解析/提取进度，失败重试，版本对比，设置主简历，AI 派生草稿，归档、恢复和永久删除预检。扫描 PDF 无文本时返回明确可恢复错误，不隐式启用 OCR。

### 13.3 Claim 审核工作台

支持查看 Evidence，接受、编辑后接受、拒绝，标记 Evidence 不准确，查看冲突，单项/批量确认，以及从 Claim 发起讨论。批量接受基于显式 Selection Snapshot 和 Diff，部分成功逐项展示。

### 13.4 Agent 会话工作区

支持简历总体评估、项目量化、技术栈一致性等多个兄弟会话。新会话不复制父 checkpoint，通过领域 ID 装配已确认画像和相关 Evidence。

### 13.5 知识发布范围

支持 Claim 级选择、敏感字段排除、发布预览、Knowledge Draft、独立 HITL、发布版本和撤销 Active Knowledge。

## 14. API 设计

### 14.1 材料与版本

```http
POST /api/workspaces/{workspaceId}/profile/materials
GET  /api/workspaces/{workspaceId}/profile/materials
POST /api/profile/materials/{materialId}/versions
GET  /api/profile/materials/{materialId}/versions
GET  /api/profile/material-versions/{versionId}
POST /api/profile/materials/{materialId}/archive
POST /api/profile/materials/{materialId}/restore
POST /api/profile/materials/{materialId}/primary
```

上传返回 `202 Accepted`，包含 materialId、versionId、executionId 和 processingStatus。

### 14.2 Claim 与 Proposal

```http
GET  /api/workspaces/{workspaceId}/profile/claims
GET  /api/profile/claims/{claimId}
GET  /api/profile/claims/{claimId}/versions
POST /api/profile/claim-proposals/{proposalId}/accept
POST /api/profile/claim-proposals/{proposalId}/reject
POST /api/profile/claim-proposals/batch-decide
```

写请求必须携带 `Idempotency-Key` 和目标 `expectedVersion`。版本不一致返回 `409 Conflict` 并重新展示 Diff。

### 14.3 Action Plan

```http
GET  /api/profile/action-plans/{planId}
POST /api/profile/action-plans/{planId}/confirm
POST /api/profile/action-plans/{planId}/cancel
POST /api/profile/action-plans/{planId}/retry
```

确认请求提交计划版本和显式 `selectedItemIds`，不得使用漂移的页面当前选择语义。

### 14.4 删除预检

```http
POST /api/profile/materials/{materialId}/deletion-preview
POST /api/profile/materials/{materialId}/permanent-delete
```

预检返回 deletionPlanId、materialVersion、受影响 Evidence/Claim、将变为 unsupported 的 Claim、Active Publication 和 expiresAt。永久删除必须引用未过期计划并携带精确选择。

## 15. 删除、撤销与隐私语义

归档隐藏默认列表和 Agent 检索，但保留版本、Evidence、Claim 关系和审计；恢复后不重新解析。

永久删除采用：

```text
生成影响计划
→ 展示受影响 Evidence、Claim 和 Active Knowledge
→ 用户明确选择
→ 确定性删除执行器
```

受影响已确认 Claim 可以同时删除、保留但标记 `unsupported`，或取消删除。Active Knowledge 不允许静默保留；用户必须明确撤销受影响发布，或取消永久删除。执行器先撤销 Active 投影，再清理原材料和 Evidence 正文。

普通撤销发布可以保留历史知识版本和 Receipt；隐私性质的永久清除不能保留可恢复敏感正文，只保留无正文 tombstone、哈希和审计事实。

## 16. 幂等、并发与取消

所有领域写操作同时使用 `Idempotency-Key`、`expectedVersion`、不可变输入快照和 Item 级 Receipt。

批量结果区分 `completed`、`conflict`、`failed_retryable`、`failed_terminal` 和 `not_started`。重试只执行 `failed_retryable` 与 `not_started`。

模型等待和只读 Tool 可以尽快取消；单个领域写事务开始后完成当前 Item，取消阻止后续 Item。用户取消落 `cancelled`；无用户取消请求的进程退出落 `interrupted`；恢复或重试复用快照和幂等键，不重放已完成副作用。

## 17. 失败恢复

| 失败位置 | 处理 |
|---|---|
| 文件校验 | 不创建正式版本，返回安全错误 |
| 解析 | 保留版本并标记 `parse_failed`，允许重试 |
| 提取模型 | 保留 Evidence 并标记 `extraction_failed` |
| 提取校验 | 不保存 Claim 候选，Execution 失败 |
| 只读 Tool | 返回稳定错误 ToolMessage，受限重试 |
| Assessment | 不创建正式 Proposal |
| Action Plan Item | 保存逐项 Receipt，只重试未成功项 |
| 服务重启 | Running Execution 进入 `interrupted` |
| Claim 并发变更 | `409 Conflict`，旧计划 `expired` |
| 发布 | 保留 Knowledge Draft，不进入 Active Knowledge |

## 18. 实施切片

### R3.1 材料与 Evidence 基础设施

私有内容寻址存储；Material/Version/Evidence migration 与 repository；PDF、DOCX、Markdown 解析；`profile.ingest`；版本 UI；Evidence 只读 Tool；Tool Event/Audit 扩展。

### R3.2 结构化画像与 Claim 审核

`profile_extraction`；Claim/ClaimVersion/Proposal；Evidence 追溯、冲突和审核；批量确认与删除影响预检；Claim 审核 UI。

### R3.3 评估、润色与连续对话

`profile_assessment`；`profile.manage`；`profile_chat` 只读 Tool loop；`profile_action_planner`；Action Plan、Diff、Receipt、停止与重试；Agent 会话 UI。

### R3.4 知识发布闭环

Claim 级 PublicationSelection；敏感字段排除；既有 Knowledge Draft/HITL 接入；发布状态、撤销和删除协同；R4-R6 已确认画像查询接口。

### R3.5 多来源材料与记忆候选

第一里程碑稳定后按项目文档、博客/研究、GitHub、其他外部材料的顺序扩展。所有来源复用 Material → Version → Evidence → Claim Proposal → User Confirmation。

GitHub 接入另行设计授权、同步游标、速率限制、数据撤销和账号解绑。R3 可生成 `PreferenceCandidate`、`MemoryCandidate`、`TodoCandidate`，但候选不是正式长期记忆；用户确认后才能进入 Store，R3 不执行 Todo 或创建外部提醒。

R3 第一可验收里程碑完成 R3.1-R3.4；R3.5 是第二里程碑。

## 19. 测试策略

### 19.1 领域单元测试

覆盖 Material、Version、Claim、Proposal、Action Plan 状态机，Evidence 引用，删除影响，发布选择，幂等 Receipt，乐观并发和敏感字段过滤。

### 19.2 Agent 契约测试

- Extraction 输出满足 Schema，不合法 Evidence ID 被拒绝；
- Assessment 不能直接生成正式 Claim；
- `profile_chat` 只能看到 allowlist Tool；
- 未授权 Tool 返回 `tool_not_allowed`；
- Tool 次数和重复调用限制生效；
- ToolMessage 正确回送模型；
- Tool 原始参数和结果不进入产品 Event；
- `ToolStrategy` 不计入业务 Tool Audit；
- Planner 只生成计划。

### 19.3 集成测试

覆盖上传到 Claim 候选、migration、幂等、并发、checkpoint、停止、重启、显式重试、批量部分成功、Session 删除解耦、材料删除、Evidence 失效、Active Knowledge 撤销和发布历史隔离。

### 19.4 API 与前端测试

覆盖 `202 Accepted`、Event cursor 重放、刷新恢复、Proposal 编辑确认、Action Plan 过期、删除预检、发布确认、390px 无横向溢出、键盘/Focus/错误/Loading。

任务期间运行针对性测试；跨层集成后按需运行一次全量；最终验收前运行一次全量。

## 20. 浏览器与真实 Provider 验收

第一里程碑至少覆盖：

1. 上传 DOCX 简历，观察解析、提取和 Claim 候选；
2. 上传新版本、比较差异并设置主简历；
3. 查看 Claim Evidence，接受、编辑和拒绝候选；
4. 冲突 Claim 不自动覆盖；
5. 生成 Assessment Proposal；
6. 画像会话跨版本问答，观察安全 Tool 阶段；
7. 多项修改生成 Action Plan，只执行选中项目；
8. 执行停止和刷新恢复；
9. 批量部分失败后只重试未成功项；
10. Claim 级发布、敏感排除和独立 HITL；
11. 撤销后 Active Knowledge 不再可检索；
12. 归档、恢复和永久删除影响预检；
13. 删除 Session 后正式画像和知识仍存在；
14. 桌面和 390px 核心路径无遮挡和横向溢出。

真实 Provider 至少分别验证结构化提取、简历评估、带只读 Tool 的连续对话和结构化 Action Plan。

## 21. 验收标准

- 原始简历、版本、Evidence、Claim、Proposal 和发布版本可追溯；
- 未确认候选和已确认画像严格分离；
- Agent 不能直接修改画像、删除材料或发布知识；
- 正式修改都有 Diff、确认和 Receipt；
- 画像确认与知识发布是两次授权；
- Tool scope 由服务端注入，模型不能扩大权限；
- Tool 有审计，敏感参数和结果不进入 SSE；
- 停止、失败、重启和部分成功可恢复；
- 多个画像会话共享领域事实但不复制 checkpoint；
- 删除 Session 不删除画像；
- 永久删除材料不会静默保留 Active Knowledge；
- 已确认发布画像可供 R4-R6 稳定查询；
- 自动测试、真实 Provider 和浏览器验收均有新鲜证据。

## 22. 产品成熟度边界

R3 第一里程碑完成后，产品具备“有证据、经确认、可发布、可撤销”的个人简历画像闭环，但仍不是任意个人数据自治平台。

它能可靠管理上传简历和由此产生的画像事实；不能代表已经完成所有外部身份源、自动长期记忆、OCR、通用搜索或自主任务执行。R3.5 的多来源能力必须继续遵守相同的 Evidence、确认、权限和删除边界。
