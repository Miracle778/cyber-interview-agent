# ADR：Agent 上下文组装与命令解释边界

- 状态：Accepted
- 决定日期：2026-07-15
- 适用阶段：R2 首次落地，R3-R8 按角色采用
- 关联设计：`docs/superpowers/specs/2026-07-15-agent-context-assembly-design.md`

## 背景

R2 题库整理会话需要理解“这题”“刚才那题”“加了备注的重新生成，其他的发布”等跨轮自然语言。临时实现把最近 8 条产品消息和全部候选题全文拼入 `CurationIntentAgent`。该方式缺少稳定 token 预算、领域焦点和资源选择，也使一次结构化分类调用看起来像独立长期 Agent。

需要选择一套既解决当前题库整理问题，又能供个人信息、岗位、复盘、模拟面试和 Channel Agent 复用的上下文架构。

## 选择标准

- 重启后能确定性恢复当前讨论对象；
- 发布、拒绝、删除和重写不会依赖模型猜测；
- 上下文成本随相关信息而非全部历史增长；
- 可以复用通用能力，但不把领域状态塞进万能 Runtime 对象；
- 与 LangGraph checkpoint、官方 AgentMiddleware 和现有领域 Graph 分工一致；
- 允许后续 Agent 按自己的状态所有权逐步采用，而不是一次性重写。

## 候选方案

### 方案 A：通用 ContextAssembler + 领域记忆投影

通用层按 token 预算组装工作状态、历史摘要、最近完整 turn 和相关资源。每个领域拥有自己的焦点、游标和资源 adapter。显式命令由确定性 parser 处理，复杂表达才进入一次结构化模型分类。

优点：领域事实、产品记忆和模型上下文边界清楚；能按需加载资源并控制成本；支持重启、审计、幂等和后续 Agent 复用；不要求一次迁移所有 role Agent。

代价：需要新增 context repository、adapter、预算类型和摘要生命周期；必须维护领域状态与产品 timeline 的一致性；测试范围包含数据库、模型输入和恢复链路。

### 方案 B：完全依赖 LangGraph checkpoint 与 summarization middleware

给命令识别组件增加长期 thread/checkpointer，让消息历史自然累积，并在达到阈值时由 middleware 摘要。

优点：实现代码较少，直接使用框架短期记忆。

拒绝原因：当前讨论对象仍隐藏在消息文本中；产品 timeline、领域事实和内部 checkpoint 形成双重记忆；“这题发布吧”等有副作用操作仍依赖模型从历史猜测；命令识别是一次分类步骤，不需要长期 Agent loop。

### 方案 C：继续在应用服务中拼 prompt

把固定 8 条改为 token 截断，并增加一段摘要，但不建立通用协议和持久领域焦点。

优点：改动最小，能短期降低 prompt 大小。

拒绝原因：每个后续 Agent 会复制自己的上下文拼装代码；摘要与资源优先级缺少统一测试契约；重启恢复和指代安全仍不可靠；无法形成 R3-R8 可复用的 Agent Harness 能力。

## 决定

采用方案 A，并明确以下边界：

1. 建立无领域知识的 `ContextAssembler`，按 token 预算保留完整 turn、结构化摘要和优先资源；
2. 题库整理使用独立 `review_curation_context` 保存焦点、最近意图、最近结果和摘要游标；
3. 将 `CurationIntentAgent` 收敛为 `CurationCommandInterpreter`；它由确定性 parser 和一次性 structured classifier 组成；
4. interpreter 不拥有 checkpoint、工具或副作用权限，模型只输出 `CurationCommandPlan`；现有 `CurationIntentPlan` 同步更名；
5. 明确序号、范围和唯一焦点优先由规则解析，只有复杂或含糊表达才调用模型；
6. 现有 summarization middleware 保留为 role Agent 内部消息的最后保护，不承担领域记忆职责；
7. 本次只迁移题库整理命令链路，其他 R2-R8 Agent 在出现真实需求时通过自己的 adapter 采用。

## 为什么不是“专门的长期 Intent Agent”

意图识别或 routing 是常见步骤，但本场景没有跨领域 Agent 分发、工具循环或长期自主任务。一次输入到严格结构化计划更接近分类节点。把它命名为 Agent 会误导状态所有权，并诱导建立第二份隐藏会话历史。

底层可以继续使用 `create_agent` 获得结构化输出与统一治理，但产品和架构语义把它视为命令解释器。执行名称与模型用途绑定分离：前者描述组件职责，后者选择 Provider/model 配置。

## 结果

正向结果：

- “这题”可以由持久焦点确定性恢复；
- 简单命令不再产生模型调用；
- 大量候选题只发送轻量索引，减少 token、延迟和污染；
- 后续 Agent 获得一致的上下文预算与资源选择协议；
- 领域副作用继续可审计、可验证、可重放。

负向结果与风险：

- 增加一个领域 context projection 和摘要更新的一致性成本；
- token 估算与模型真实计费可能存在差异，必须投影 degraded 状态；
- 摘要丢失细节会影响普通对话，因此必须保留稳定引用、决定和未解决事项；
- 通用 ContextAssembler 若吸收领域查询或副作用会演变为大 Runtime，代码审阅必须阻止该趋势。

## 不适用范围

- 一次性答案评价、题目生成和报告生成不自动继承产品完整对话；
- 知识发布、Vault 写入、索引更新和 Todo 状态机不进入 ContextAssembler；
- 多 Agent supervisor、handoff 和动态 routing 不由本决定引入；
- Langfuse/OTel 只观察运行，不作为记忆或业务事实来源。

## 重新评估条件

满足任一条件时重新评估本决定：

- 出现需要在多个专业 Agent 间动态分发的统一入口；
- 三个以上领域 adapter 出现无法通过窄接口消除的相同持久化逻辑；
- 实际 Provider token 计数与本地预算长期偏差导致频繁超限；
- 领域摘要无法在长会话中保持引用完整性；
- Channel 场景要求跨平台、跨 session 的统一长期记忆；
- LangChain/LangGraph 提供能同时满足领域焦点、资源预算和可审计恢复的稳定官方抽象。
