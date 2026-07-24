# ADR：求职目标、项目训练与 Agent Runtime 边界

- 状态：Accepted
- 决定日期：2026-07-25
- 适用范围：求职目标、岗位分析、项目深挖、项目经历题训练
- 决策来源：用户通过逐项需求追问确认
- 关联规格：`docs/superpowers/specs/2026-07-25-job-target-and-project-deep-dive-design.md`
- 补充决策：`docs/superpowers/architecture-decisions/2026-07-24-job-target-centered-interview-preparation.md`

## 背景

2026-07-24 的 ADR 已决定以求职目标组织岗位要求、项目深挖和后续训练。继续设计时暴露了几类必须在实现前固定的架构问题：

- 求职目标是否复制简历、画像和项目；
- 岗位分析、项目深挖和项目题训练是否使用同一个开放 Agent；
- 深挖是否需要 Tool、`state_schema`、上下文 Offload、Plan-and-Execute 或 Time Travel；
- 模型失败或用户停止后，一条用户消息如何重试而不污染上下文；
- 通用项目讲解和岗位专项结论由谁拥有；
- 项目题是目标内临时内容，还是题库正式资产；
- 长任务如何恢复而不重新调用已经完成的工作。

这些选择会影响多个阶段的数据所有权、Runtime 接口、删除语义和安全边界，不能留给页面实现临时决定。

## 决策驱动

- 长期个人事实不能因创建或删除求职目标而复制、分叉或丢失；
- 同一组真实项目需要被多个岗位复用；
- 岗位分析失败不能污染项目深挖对话；
- 项目深挖必须可恢复，但不能演变成无限 Planner；
- 模型输出不能直接成为正式画像、讲解或题库内容；
- 重试必须保留审计，同时保证模型上下文中用户输入只出现一次；
- 首版复用统一 Session/Execution/Event/Checkpoint 和现有题库复习能力；
- SQLite 单进程环境下需要明确单写者、短事务和幂等边界。

## 候选方案

### 方案 A：每个求职目标复制一份简历、画像和项目

优点：查询简单，删除目标时容易级联。

拒绝原因：用户的项目通常跨岗位复用；复制后会出现事实冲突、重复确认和跨目标更新困难。

### 方案 B：一个开放 Agent 同时完成岗位分析、资料修改、项目深挖和题目发布

优点：入口少，Prompt 看似统一。

拒绝原因：上下文无限增长，职责和 Tool 权限难以解释，失败状态互相污染，并诱导模型直接写入多个领域。

### 方案 C：按职责拆分执行单元，共享 Runtime 与领域服务

岗位分析作为可恢复后台任务；项目深挖作为持久会话 Agent；项目题训练复用现有复习 Runtime。长期事实仍由画像和题库领域拥有。

优点：状态所有者清晰，失败隔离，能复用现有恢复与审计能力。

代价：需要新增求职目标领域、专用 Graph、结构化契约和跨域 application service。

## 决定

采用方案 C，并规定以下边界。

## 1. 领域所有权

| 状态 | 所有者 | 求职目标删除后的结果 |
|---|---|---|
| 简历、Evidence、画像事实、全局项目 | Profile | 保留 |
| 通用项目讲解及版本 | Profile / Project Narrative | 保留 |
| JD/岗位方向版本、要求、映射、项目优先级、专项问题、风险 | Job Target | 删除 |
| 项目题候选 | Deep-dive Artifact / Job Target | 由用户选择保留草稿或删除 |
| 已确认项目经历题、掌握状态和复习历史 | Question / Review | 保留 |
| Session、Execution、Message、Event | Agent Runtime，受领域引用约束 | 目标会话随目标删除，正式题目历史保留 |

求职目标只保存稳定 ID、版本引用和目标专项状态，不复制画像或项目正文。

## 2. 首版目标与 JD 基数

一个求职目标首版最多拥有一个当前 JD 版本。没有 JD 时拥有一个明确标记的岗位方向参考版本。

每次正文编辑创建不可变新版本。目标元数据编辑不创建 JD 版本。

本条收窄 2026-07-24 ADR 中“一个或多个具体 JD”的长期表述；多 JD 对比不是首版能力。

## 3. Agent 与执行单元

### 3.1 岗位分析任务

- 类型：可恢复后台 Execution；
- 职责：提取原子要求、生成候选画像映射、批量分析项目相关性；
- 会话：使用隐藏或领域可见的 system Session 承载 Runtime，不建立长期聊天；
- 模型用途：`job_analysis`；
- 输出：岗位要求草稿、候选映射、项目排序建议；
- 写入：只写本次任务的私有草稿和工作单元，不确认正式要求。

### 3.2 项目深挖 Agent

- 类型：用户可见的持久 Session；
- 身份：一个 `(job_target_id, project_claim_id)` 一个主要会话；
- 模型用途：`project_deep_dive`；
- 输出：回答评价、讲解草稿增量、差距建议、下一问题；
- 写入：只写未确认 Artifact/Proposal 和运行状态。

### 3.3 项目题训练

- 复用现有 Review Session/Execution、回答接收、失败恢复和掌握度框架；
- 采用项目题专用 Prompt、评价契约和三态掌握结果；
- 不新建第四套 Agent Runtime；
- 项目事实冲突通过结构化冲突处理，不直接修改 Profile。

## 4. 模型用途

新增：

- `job_analysis`；
- `project_deep_dive`。

升级现有 Workspace 时：

- `job_analysis` 初始复制 `profile_assessment` 的绑定；
- `project_deep_dive` 初始复制 `agent_chat` 的绑定。

迁移后两者是独立配置。Execution 继续保存不可变模型绑定快照，运行中修改设置只影响后续 Execution。

## 5. 有界 Plan-and-Execute

项目深挖使用固定阶段和自适应有限追问：

```text
背景与目标
→ 角色与职责
→ 方案与理由
→ 难点与解决
→ 结果
→ 取舍与复盘
→ 岗位专项
```

Graph 决定当前阶段是否完成、是否需要一次补问以及下一阶段，不允许模型自由创建任意步骤或递归委派。

不采用：

- 自由 ReAct 写入；
- 无限 Planner；
- 子 Agent 自由委派；
- 会话 Time Travel 或分叉。

## 6. 显式最小 `state_schema`

项目深挖属于跨多轮、需要暂停恢复且存在显式控制流的 Graph，因此必须传入专用 `state_schema`。

State 只包含：

```text
job_target_id
project_claim_id
session_id
execution_id
current_stage
current_question_id
completed_stage_ids
follow_up_ids
waiting_for_input
pause_requested
end_requested
```

不包含：

- JD 正文；
- Profile Claim 正文；
- 项目讲解正文；
- Evidence 或简历正文；
- 完整消息历史；
- 题目候选正文。

这些内容由领域存储拥有，Graph 每次通过稳定引用重读。

## 7. Context Offload 与压缩

采用两种互补机制：

1. 领域 Offload：JD、要求、Profile、项目讲解、题目和 Artifact 保存在领域表中；
2. 对话 Compaction：长会话把早期消息压缩成可追溯摘要。

每次调用按阶段组装：

- 当前已确认要求；
- 当前项目的相关已确认画像；
- 已确认通用讲解；
- 当前目标专项状态；
- 最近消息和压缩摘要；
- 当前问题。

摘要必须保留用户声明事实、未解决冲突、待处理项、当前阶段和来源消息 ID。原始消息继续持久化，摘要不能覆盖领域事实。

## 8. Tool 与写入边界

### 8.1 允许的 Tool

岗位分析和项目深挖只获得角色级最小只读 Tool：

- `get_job_target_context`；
- `get_confirmed_profile_context`；
- `get_project_context`；
- `get_project_narrative`；
- `list_project_questions`。

所有 Workspace、Target、Project、Session、Execution 和 scope 参数由服务端注入或校验。模型不能自报权限边界。

### 8.2 禁止的 Tool

不向模型暴露：

- 画像更新或删除；
- 岗位要求确认；
- 项目讲解确认；
- 题目发布；
- 任意 SQL、文件路径、网络请求；
- 正式 Todo 创建；
- 任意代码执行。

### 8.3 写入协议

```text
模型结构化输出
→ 服务端 schema 校验
→ 私有 Proposal/Artifact
→ 页面展示 Diff
→ 用户确认
→ 确定性领域服务
→ 乐观锁 + 幂等键
→ Receipt
```

模型没有正式领域写权限。

## 9. Message 与 Execution 的一对多关系

一条用户消息是用户表达的事实；Execution 是一次处理尝试。二者不是一一绑定。

新增稳定关系：

- `agent_runs.input_message_id`；
- `agent_runs.retry_of_execution_id`；
- `agent_messages.replaces_message_id`；
- `agent_messages.resolution_status`，值为 `active`、`unresolved`、`replaced`、`abandoned`。

### 9.1 初次执行

1. 先持久化用户消息 M1；
2. 创建 E1，引用 `input_message_id=M1`；
3. `ExecutionService.prepare(..., project_input_message=False)`，不再次投影消息；
4. 运行 Graph。

### 9.2 原内容重试

1. M1 保留且标记 unresolved；
2. 创建 E2，引用同一个 M1；
3. `retry_of_execution_id=E1`；
4. 活跃模型上下文把 M1 作为当前输入加入一次。

### 9.3 修改后重试

1. 创建新消息 M2；
2. `M2.replaces_message_id=M1`；
3. M1 标记 replaced；
4. 新 Execution 引用 M2；
5. 上下文排除 M1。

### 9.4 放弃

M1 标记 abandoned，不再作为待处理输入或活跃上下文。审计记录保留。

失败、取消和停止的 assistant 半成品、Tool 输出与临时 delta 不投影为正式 assistant Message，也不进入项目讲解或题库。

## 10. 同一会话并发规则

不同求职目标和不同深挖 Session 可以并发。

同一 Session 同一时刻只能有一个活跃 Execution。存在 unresolved 用户消息时，禁止发送无关联的新消息；用户必须先重试、替换或放弃。

共享画像、讲解和题库的写入使用：

- 稳定领域 ID；
- expected version；
- 幂等键；
- 短事务；
- 写入 Receipt。

不以页面级 `busy` 代替领域并发控制。

## 11. 长任务恢复模型

岗位分析和项目映射拆成持久 Work Item：

```text
Analysis Run
├─ requirement_extraction
├─ profile_mapping
├─ project_mapping[project_id]
└─ final_projection
```

每个 Work Item 保存：

- 稳定输入摘要；
- 状态；
- 尝试次数；
- 输出；
- 错误码；
- 更新时间。

恢复时跳过已完成且输入摘要一致的 Work Item。输入版本变化时创建新 Analysis Run，不覆写旧输出。

首版仍是单进程有界调度器和 SQLite 持久恢复，不引入分布式队列。

## 12. SQLite 事务边界

为避免历史上的 `database is locked` 重现：

- Provider 调用期间不得持有 SQLite 事务；
- 每个持久写步骤使用短事务；
- Event、Execution 终态和领域 Artifact 通过同一进程的 Runtime repository 写入；
- 后台 worker 不共享一个长期 cursor 或未提交事务；
- 幂等写在事务内检查 receipt；
- 失败终态写入使用有界 busy timeout 和现有 Runtime 连接策略；
- 不在异常处理链中重复开启相互竞争的写事务。

完整“模型调用 + 多领域写入”不是一个数据库事务；通过私有 Artifact 和后续确认实现最终一致。

## 13. 项目讲解版本

通用项目讲解使用章节级版本：

- 每节有稳定身份和当前已确认版本；
- 深挖草稿引用来源 Session、Message 和 Profile ClaimVersion；
- 确认创建新版本，不覆写历史；
- 目标专项内容单独保存；
- Profile 更新使相关讲解标记可能过期，但不自动重写。

不提供整个项目任意时间点回滚。

## 14. 项目经历题归属

项目经历题是题库正式类型 `project_experience`。

正式题目保存：

- 全局项目 ID；
- 能力维度；
- 来源目标或深挖 Session；
- 题目版本；
- 当前 active 版本。

来源目标删除只移除来源关联，不删除题目。

项目题训练复用题库 Session/Execution，但掌握维度独立于通用技术题：

- 事实一致；
- 细节具体；
- 结构完整；
- 经得住追问。

## 15. 隐私和上下文范围

每个 Execution 保存可展示的 Context Manifest，只含类别、稳定 ID、版本、条数和排除原因，不把完整敏感正文写入 Event 或 Audit。

默认排除：

- 原始简历；
- 联系方式和敏感字段；
- 无关项目；
- 其他目标专项内容；
- pending、rejected、superseded、replaced 和 abandoned 内容。

首次向外部 Provider 发送个人资料前需要用户确认资料类型。此后侧栏持续显示范围、模型、Token 和上下文整理状态。

## 16. 准备状态

准备状态是派生投影，不是用户手工枚举字段：

- 待确认岗位要求；
- 待选择核心项目；
- 项目深挖进行中；
- 有高风险问题待处理；
- 核心准备已完成。

派生逻辑读取已确认要求、项目优先级、讲解章节、风险接受记录和项目题训练结果。不保存单一准备百分比。

## 17. API 与 UI 命名

`R4` 只出现在路线图和内部阶段说明中。

代码和 API 使用领域名称 `job_target`、`job_requirement`、`project_deep_dive`、`project_experience_question`。用户界面和 Git 提交信息使用中文或英文业务语义，不使用“提交类型加阶段编号”或“阶段编号加 Agent”这类孤立命名。

## 18. 对既有 ADR 的细化

本 ADR 保留 2026-07-24 ADR 的产品中心和安全边界，并作以下首版细化：

- 一个目标首版从“可绑定一个或多个 JD”收窄为“最多一个当前 JD”；
- 项目从“目标关联的项目”明确为“统一画像中的全局项目，目标只保存优先级和映射”；
- 项目经历题成为正式题库类型，而不是只作为目标内临时知识缺口；
- 明确一条 Message 可以对应多次 Execution；
- 明确岗位分析、项目深挖和项目题训练的执行单元边界；
- 明确最小 `state_schema`、领域 Offload 和 Context Manifest。

如有冲突，以本 ADR 的首版实现边界为准。

## 结果

正向结果：

- 同一项目可以跨岗位复用，不复制长期事实；
- Agent 失败边界与权限容易解释；
- 重试不再制造重复用户消息或上下文污染；
- 长任务可以基于 Work Item 恢复；
- 项目题进入正式复习闭环；
- 后续面试复盘和模拟面试可以继续挂在求职目标下。

代价：

- 需要新增 Job Target 领域和跨域 application service；
- Runtime schema 需要补 Message/Execution 关联；
- 题库需要正式题型和项目引用；
- Profile 项目讲解需要独立章节版本；
- 设置页需要增加两个模型用途；
- 删除和重新分析需要显式影响预检。

## 重新评估条件

满足任一条件时重新评估：

- 用户普遍需要一个目标同时比较多个 JD；
- 单进程 SQLite 无法满足真实并发，需要引入队列或独立 worker；
- 项目讲解在多个目标间频繁冲突，章节级通用/专项拆分仍不足；
- 项目题训练与通用复习的状态机差异大到无法安全复用；
- 用户明确需要从历史节点分叉训练，并接受新会话语义；
- 外部模块需要跨 Workspace 共享个人资料或项目讲解。
