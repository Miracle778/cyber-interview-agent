# ADR：领域 Agent 的工具与写入边界

- 状态：Accepted
- 决定日期：2026-07-20
- 适用阶段：R2 现状说明，R3-R8 新增领域 Agent 默认遵守
- 关联设计：`docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- 关联决定：`docs/superpowers/architecture-decisions/2026-07-15-agent-context-assembly.md`

## 背景

R2 已实现题目整理、整理命令解释、单题与轮次评价、轮次报告和深入讨论等多个基于 `create_agent` 的组件。代码保留 `question_tools` 和 `discussion_tools` 注入扩展点，Agent Harness 也具备标准 `BaseTool`、`ToolPolicyMiddleware`、Workspace scope 和工具审计能力，但当前 R2 生产执行把领域所需材料组装为有界输入，所有 Agent 的业务工具与 scope allowlist 均为空。

R3 个人信息 Agent 将面对不同约束：用户会跨多份简历、项目说明、博客和已确认画像探索证据，部分问题需要模型根据中间结果继续检索；同时，画像修改、材料删除和知识发布涉及隐私、版本、证据、幂等和 HITL，不能由模型在自由 ReAct 循环中直接提交。

需要形成一项跨阶段规则，明确何时不给 Agent 工具、何时允许只读工具，以及领域写入如何执行。

## 选择标准

- 已知上下文的任务不增加不必要的模型工具循环、延迟和失败面；
- 探索型任务可以按需定位证据，而不是无界注入全部材料；
- 修改、删除、发布等副作用具有稳定资源 ID、expected version、幂等 receipt 和恢复点；
- 用户确认画像不等于授权知识发布，不得通过一个模糊命令合并两个权限边界；
- Agent 工具只能访问服务端授权的 Workspace、资源和 scope，不能接收任意绝对路径；
- checkpoint、重试和进程恢复不能重复执行已经成功的领域副作用；
- 结构化输出协议与真实业务工具在代码、审计和文档语义上保持区分。

## 候选方案

### 方案 A：所有领域 Agent 都使用自由 ReAct 和统一读写工具集

给题目整理、复习、个人资料和后续 Agent 统一注册搜索、读取、更新、删除和发布工具，由模型决定调用顺序和停止条件。

优点：表面接口统一；复杂自然语言可以由模型动态编排；新能力可能只需新增工具。

拒绝原因：已知输入的评价和报告也会增加无意义的工具调用；模型同时拥有资源选择、写入顺序和停止条件；多工具副作用的部分成功、重试和恢复难以保持单一状态所有者；模糊指代可能直接修改或发布错误资源；工具 schema 和结果会持续扩大上下文。

### 方案 B：所有 Agent 永远无工具，应用层一次性注入全部上下文

所有材料、画像、题库和知识均由应用服务预先读取并拼入 Agent 输入，模型只返回结构化结果或文本。

优点：权限最小；调用路径简单；适合 R2 中题目、回答和 attempts 已确定的任务。

拒绝其作为跨阶段统一规则的原因：R3-R6 的探索问题无法在一次调用前确定全部相关证据；无界注入全部个人资料、JD 或复盘会增加隐私暴露、token 成本和上下文污染；每个应用服务会复制搜索与裁剪策略。

### 方案 C：按任务风险分层，探索只读，写入受控

已知上下文的转换、评价和总结 Agent 默认无业务工具。只有证据位置未知、确需根据中间结果继续探索的 Agent 才获得最小只读工具集。模型输出结构化 proposal，修改、删除和发布由领域服务在用户确认后执行。

优点：保留 R2 的确定性和低成本路径；为 R3-R6 提供真正需要的按需检索；副作用继续拥有稳定版本、幂等、HITL 和恢复边界；可以按 Agent role 精确配置工具与 scope。

代价：需要维护角色级 allowlist、ID 驱动的资源工具和 proposal contract；应用服务必须显式实现 `Validate -> Confirm -> Execute`；只读探索与领域上下文组装需要共同控制 token 预算。

## 决定

采用方案 C，并规定以下边界。

### 1. 已知上下文的 Agent 默认无业务工具

当应用层在调用前已经知道完整、有限且稳定的输入集合时，直接把有界上下文传给 Agent，不注册业务工具。

R2 当前实例包括：

- 题目整理接收已选择并分片的 source excerpts 与相似题摘要；
- 整理命令 classifier、summarizer 和 responder 接收 ContextAssembler 产物；
- 单题与轮次 evaluator 接收冻结题目快照、回答和补充回答；
- reporter 接收结构化 attempts、轮次设置和已确认报告；
- discussion 接收明确题目和 attempt evidence，当前不启用预留的 `discussion_tools`。

这些 Agent 的领域状态推进由 Graph、repository 和 application service 完成。`ToolStrategy` 用于严格结构化输出时可能在 Provider 协议中表现为 tool call，但不视为业务工具，不获得资源访问或副作用权限。

### 2. 探索型 Agent 只获得最小只读工具

仅当用户问题无法在调用前确定全部相关证据、并且模型需要根据一次查询结果继续选择下一步读取时，才启用 ReAct 或多步工具调用。

R3 个人信息 Agent 的候选只读工具包括：

- `list_personal_materials`：列出会话授权的材料与版本元数据；
- `search_personal_materials`：在脱敏文本中检索有界证据片段；
- `read_personal_evidence`：按稳定 evidence ref 读取准确片段；
- `get_profile_claims`：按分类、状态或稳定 claim ID 查询画像；
- `get_profile_claim_evidence`：读取画像来源和冲突；
- `compare_material_versions`：比较明确的两个材料版本；
- `search_active_knowledge`：只读已发布 active scope；
- `get_profile_publication_status`：查询画像的发布投影。

每个 Agent role 单独配置 `allowed_tools`、`allowed_scopes` 和调用上限，不把全部候选工具注册给所有 Agent。资源工具使用服务端稳定 ID 和 evidence ref，不允许模型提供绝对路径、Workspace ID、任意 scope 或未经授权的文件相对路径。工具结果限制条数、字节数和可见字段，并通过现有 ToolPolicy 与工具审计。

### 3. 正式写入不进入自由 ReAct 工具集

以下操作不得作为个人信息 Agent 可自由调用的业务工具：

- 更新、删除或合并正式画像；
- 设置主简历、归档或永久删除材料；
- 覆盖原始简历或创建已生效版本；
- 发布、撤销发布或直接写 active knowledge；
- 创建正式 Todo、长期记忆或跨阶段状态。

模型返回带稳定目标、expected version、建议内容和 evidence refs 的 `ProfileProposal`。应用服务校验资源状态、版本、证据、权限和幂等键，页面展示差异，用户明确确认后才由领域服务创建新的画像版本。知识发布是第二个独立决定：用户选择已确认画像项，系统生成版本化知识草稿，再通过现有 `knowledge.publish` Graph 与 HITL handler 发布。

### 4. 临时草稿由 Graph 或应用服务持久化

模型可以生成简历润色稿、画像建议和发布预览，但不获得任意文件写工具。Graph 节点或应用服务在校验严格输出后创建只读候选或临时草稿，并记录 session、execution、来源、内容哈希和状态。

临时草稿不得自动成为主简历、正式画像或 active knowledge，也不得作为后续 Agent 的已确认事实。用户接受后仍需通过对应领域服务形成新版本。

### 5. 副作用链路固定为受控流程

修改、删除和发布采用：

```text
Agent proposal
  -> Validate stable IDs, version, evidence, permission
  -> Show exact diff and affected scope
  -> Explicit user confirmation
  -> Domain service transaction
  -> Receipt/event/projection
```

明确、可逆且无副作用的查询可以留在 Agent tool loop；跨多个领域副作用的命令必须退出自由 ReAct，由 application service 拆解和执行。确认写入个人画像不得推导为确认发布知识。

## 结果

正向结果：

- R2 保持单次、结构化、可恢复的低成本执行路径；
- R3-R6 可以在证据位置未知时使用真正有价值的多步只读探索；
- 模型误解、重复调用或重启不会直接覆盖正式资料或绕过发布审批；
- 工具权限、Workspace scope、上下文预算和审计可以按 Agent role 验证；
- 领域事实、Agent checkpoint、产品 timeline 与 active knowledge 继续拥有清晰状态所有者。

负向结果与风险：

- R3 需要新增 ID 驱动的个人材料和画像只读工具，不能直接复用面向路径的通用 `read_source`；
- proposal contract 与领域服务之间需要完整版本冲突、幂等和部分失败测试；
- Agent 可能因只读工具过少无法完成探索，需要用真实任务证据扩展 allowlist，不能预先注册万能工具；
- 用户确认步骤增加一次交互，但这是隐私与发布边界的必要成本。

## 不适用范围

- Provider 的结构化输出 ToolStrategy 不属于本 ADR 所称业务工具；
- 数据库迁移、文件解析、脱敏和索引构建是应用基础设施，不作为 Agent 工具；
- 显式 knowledge publication Graph、HITL action handler 和领域 repository 不因本决定改写为 Tool；
- 本决定不禁止只读 ReAct、模型内部推理或未来 supervisor 路由，只限制资源访问和副作用所有权。

## 重新评估条件

满足任一条件时重新评估：

- 某个领域出现大量安全、可逆且无需用户确认的写操作，受控 proposal 流程显著阻碍核心任务；
- 官方 Agent Runtime 提供可持久恢复、逐工具事务化且能证明 exactly-once 的副作用协议；
- 三个以上领域重复实现相同 proposal 校验与确认逻辑，需要提取通用 command envelope；
- R3 真实验收证明只读工具无法在合理调用次数和 token 预算内定位证据；
- 外部 Channel 要求管理员授权的批量操作，需要新增角色权限和批量 selection snapshot。
