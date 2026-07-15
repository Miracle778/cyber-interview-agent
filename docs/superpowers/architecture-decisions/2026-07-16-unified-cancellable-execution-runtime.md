# ADR：交互命令统一接入可取消 Execution Runtime

- 状态：Accepted
- 决定日期：2026-07-16
- 适用阶段：R2 首次落地，后续交互式 Agent 按需复用
- 关联设计：`docs/superpowers/specs/2026-07-16-r2-cancellable-streaming-execution-design.md`
- 关联决定：`docs/superpowers/architecture-decisions/2026-07-15-agent-context-assembly.md`

## 背景

R2 题库整理命令目前在 HTTP 请求内同步完成确定性解析、必要的结构化模型分类、发布等业务动作和最终回执。该链路绕过了已有 Agent Execution Runtime，因而不能可靠停止模型调用，不能在刷新或服务重启后恢复真实运行状态，也无法复用现有的可重放 SSE 和 `assistant.delta`。

需要选择一种方案，同时满足单次运行取消、会话继续使用、模型快照、真实流式输出、发布副作用边界和后续 Agent 复用。

## 选择标准

- 取消必须由服务端持久化，不能只终止浏览器请求；
- 取消、完成和发布副作用发生竞争时必须有唯一终态；
- 刷新、SSE 重连和服务重启后能够解释真实运行状态；
- 每次运行固化实际模型配置，便于审计和复现；
- 确定性命令不得被迫增加模型调用；
- 已有 execution、事件流、上下文和幂等能力应保持单一所有权；
- 设计能够供后续交互式 Agent 采用，但不把所有业务强塞入通用 Runtime。

## 候选方案

### 方案 A：在同步命令接口上增加前端取消

浏览器使用 AbortController 中止请求，后端保持当前同步应用服务。

优点：改动范围最小。

拒绝原因：中止 HTTP 连接不等于取消服务端 task 或 Provider 请求；发布动作可能继续；页面刷新后没有可查询的运行实体；无法可靠解决取消与完成竞争，也会形成题库整理专用的假状态。

### 方案 B：交互命令统一接入 Execution Runtime

API 先持久化命令、用户消息和 execution，立即返回 `202`；后台 worker 执行解析、模型调用与业务动作，并通过统一事件流投影增量输出和终态。停止使用通用 execution cancel 入口。

优点：状态、模型快照、SSE、幂等、恢复和可观测性由一个运行时拥有；取消语义可以跨页面刷新和重启；确定性 parser 与结构化 classifier 仍可复用。

代价：需要扩展 execution 状态与配置、把同步应用服务拆成 prepare/run 两段，并补齐命令和批量发布的恢复测试。

### 方案 C：把题库整理重写为长期 ReAct/LangGraph Agent

模型在一个长期 loop 中理解输入并调用发布、拒绝、重写等工具。

优点：开放式任务编排更灵活，天然适合需要多步探索和根据中间结果继续决策的场景。

拒绝其作为当前方案的原因：明确发布命令也会增加模型调用；模型同时拥有目标选择、工具顺序和停止条件，扩大高风险副作用边界；会重写已经验证的 `Plan -> Validate -> Execute` 与上下文架构；取消工具调用后的恢复和幂等反而更复杂。

## 决定

采用方案 B，并规定：

1. 每次整理命令和批量发布都创建独立、持久化 execution；
2. HTTP 接口只完成校验、去重和 prepare，随后立即返回 accepted execution；
3. worker 执行确定性 parser，只有必要时才调用结构化 classifier 或自然语言模型；
4. 模型与思考强度作为会话偏好保存，并在发送时固化到 execution configuration；
5. 自然语言模型输出通过统一 SSE 的 `assistant.delta` 投影，结构化 JSON 不暴露给用户，也不制造伪流式文本；
6. 停止只取消当前 execution，用户消息保留，半成品 assistant 内容不进入正式上下文；
7. 取消请求先持久化，再取消本地 task；worker 在模型边界和每个业务项之间协作检查取消；
8. 单题发布事务一旦开始就完成当前题，取消只阻止后续题，已成功项不回滚；
9. 重启后不自动重复模型和副作用，遗留运行转为 interrupted，持久化取消请求转为 cancelled；
10. 继续复用 AgentExecutionService、ProductEventStream、AgentEventProjector 和现有 session SSE，不创建题库整理专用运行时或第二条流通道。

本决定不改变上一份 ADR 的命令解释边界：模型最多生成结构化计划，application service 继续在冻结的 summary version 上校验并执行副作用。Execution Runtime 负责“这次运行怎样可靠地执行”，ContextAssembler 与领域服务分别负责“模型看到什么”和“业务允许做什么”。

## 结果

正向结果：

- 停止按钮对应真实服务端状态，而不是视觉假状态；
- SSE、刷新恢复、重启中断和模型快照形成统一协议；
- 题库整理和后续交互式 Agent 可以复用相同运行生命周期；
- 简单命令继续零模型调用，高风险发布仍受确定性校验和幂等保护；
- 流式临时消息与正式上下文边界明确。

负向结果与风险：

- execution 状态机增加 accepted/cancelling/interrupted 等恢复路径，测试矩阵扩大；
- Provider 取消通常是 best-effort，已发送 token 可能仍被计费；
- 批量发布需要逐项状态与幂等记录，持久化复杂度提高；
- 通用 Runtime 若吸收候选题选择、发布策略等领域逻辑会失去边界，审阅时必须阻止这一趋势；
- prepare 成功而 worker 未启动的窗口必须由启动恢复和 interrupted 状态覆盖。

## 适用边界

适用于具有用户可见运行周期、需要停止/恢复、模型流或多个安全点的交互任务。不要求短小的同步 CRUD、纯查询和单事务确定性更新都创建 execution。

本决定不授予 Runtime 领域权限，不替代 ContextAssembler、middleware、HITL 或领域 application service，也不引入多 Agent supervisor 和动态 routing。

## 重新评估条件

满足任一条件时重新评估：

- 出现真正需要动态工具探索、根据中间结果多步推理的题库任务；
- LangGraph 提供可直接满足持久取消、逐项副作用幂等和产品事件重放的稳定官方抽象；
- 系统迁移到多进程或分布式 worker，当前进程内 task registry 不再足够；
- 三个以上 Agent 出现相同的 prepare/run/retry 模板，需要进一步抽象 execution handler 协议；
- Provider 普遍支持可恢复 generation，自动恢复中断模型调用变得安全且可验证；
- 实际运行表明 interrupted 后显式重试造成不可接受的用户成本。
