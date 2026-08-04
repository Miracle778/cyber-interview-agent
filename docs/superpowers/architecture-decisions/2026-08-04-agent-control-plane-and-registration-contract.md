# ADR：Agent Control Plane 与强制注册契约

- 状态：Accepted
- 决定日期：2026-08-04
- 适用范围：全部业务 Agent、影响业务结果的系统 Agent、Graph Builder、Session / Execution 创建入口、运行中心与质量评估
- 关联设计：`../specs/2026-07-29-agent-observability-and-quality-workbench-design.md`
- 关联决定：`2026-07-29-agent-trace-ledger-and-evaluation-boundaries.md`

## 背景

项目已经包含题库整理、题目重写、复习、深入讨论、画像管理、岗位分析、项目深挖、面试复盘等业务 Agent，以及抽取、评估、总结、发布和诊断等系统组件。现有实现已经具备：

- 代码级 `Agent Observability Registry`，声明顶层 `graph_id`、展示名、业务入口、控制能力、Eval Pack、系统组件和运行中心可见性；
- `PRODUCTION_GRAPH_KINDS` 与 Registry 的集合一致性检查；
- Session / Execution、统一 Runtime、Trace Middleware、Trace Ledger 和运行中心；
- 运行中心按 Execution 的 `graph_id` 解析注册元数据，未注册或明确隐藏的 Graph 不进入普通列表；
- Eval Pack 引用完整性契约测试。

当前边界仍不完整：

1. `POST /api/agent/sessions` 的 `kind` 仍是任意字符串，创建前没有统一 Registry 校验；未知类型可能先写入 Session，再在执行阶段失败。
2. `ProductionGraphFactory` 的 Builder 分支、`PRODUCTION_GRAPH_KINDS` 和 Observability Registry 是并行维护的多份事实源。
3. `AgentFactory.create()` 只校验组件名非空和模型绑定，不校验该组件是否属于当前顶层 Agent。
4. `system_components` 目前是展示元数据，不是可执行的组件准入契约。
5. 直接调用底层模型且影响业务结果的代码，可以绕过 AgentFactory、Trace Middleware 和注册检查。
6. Registry 只描述当前版本；Execution 没有冻结完整 Agent Definition，历史运行难以证明当时使用的 Builder、Prompt Schema、Tool 集和评估契约。

随着 Agent 数量增长，这些缺口会造成：运行中心漏记录、控制按钮与真实状态机不一致、内部组件和业务任务混淆、历史 Trace 无法复现、Eval Pack 绑定漂移，以及新增 Agent 依赖开发者记忆完成多处接线。

## 决策驱动因素

- 新增 Agent 必须默认获得 Session / Execution、Trace、运行中心、运行控制和质量评估能力，而不是由每个业务模块重复接线。
- 未注册 Agent 应在写入数据库或调用 Provider 前失败。
- 业务 Agent 与内部子 Agent 必须分层，避免一个业务任务在运行中心展开成数百条顶层记录。
- Agent 身份、Builder、Schema、Tool 权限和评估契约需要保持一致并进入 Git、代码评审和 CI。
- 历史 Execution 必须可解释，Registry 后续升级不能改写历史事实。
- 当前产品是本地优先、随代码发布的单体应用，不需要引入网络服务发现或独立配置中心。

## 候选方案

### 方案 A：继续维护前端 Agent 名单和后端 `if kind == ...`

拒绝。多份名单会持续漂移，只能控制展示，不能约束创建、权限、Tool、Trace 和 Eval；漏接通常要到用户发现运行中心没有记录时才暴露。

### 方案 B：只把 Agent ID 改成语言枚举

拒绝作为完整方案。枚举可以减少拼写错误，但不能表达 Builder、输入输出 Schema、子组件、控制能力、Tool Scope、Prompt 版本、敏感级别和 Eval Pack，也不能成为运行中心与质量评估的共同控制面。

### 方案 C：使用数据库动态 Registry 或外部服务发现

当前拒绝。

- Agent 与 Python Builder、Pydantic Schema、Graph 和 Tool 实现强绑定，不能仅靠数据库配置热加载；
- 运行时配置和代码版本可能漂移；
- 增加启动顺序、迁移、权限和故障面；
- 本地单机产品没有跨服务发现需求。

如果未来支持第三方插件，再设计受签名、版本和权限校验的 Plugin Manifest，不提前引入动态服务发现。

### 方案 D：Git 版本化的静态 Agent Control Plane

采用。建立单一、不可变、代码级 `AgentDefinitionRegistry`。注册项同时拥有身份、Builder、Schema、策略、产品元数据、可观测契约和评估绑定；Session / Execution、GraphFactory、AgentFactory、运行中心和 Eval Engine 都从该 Registry 解析，不再维护平行名单。

## 决定

### 1. Registry 定位

本项目的 Registry 是 **Agent Control Plane / Agent Catalog**，不是 Consul 一类网络服务发现。

- 控制面回答：Agent 是谁、当前哪一版、谁能创建、允许做什么、如何构建、如何观测和如何评估。
- 执行面继续由现有 Session、Execution、Graph、Checkpoint、Work Item 和领域状态承担。
- 运行中心是 Registry 元数据、Execution 业务事实和 Trace 运行事实的只读投影，不建立第二套运行状态机。

### 2. 单一 Agent Definition

目标注册契约至少包含：

```text
agent_id
definition_version
display_name
component_type: business | system
lifecycle: active | deprecated | disabled

builder
input_schema
output_schema
user_creatable
parent_agent_id
child_components
model_roles

allowed_tools
required_scopes
context_policy_id
retry_policy_id
sensitivity

capabilities: cancel | resume | retry | manual_judge | export_trace
business_route
run_center_visible
trace_policy_id
eval_pack_id

prompt_schema_versions
aliases
```

`agent_id` 是跨版本稳定身份；`definition_version` 标识可执行契约版本。展示名、路由和产品文案可以演进，但不得改变历史 Execution 的冻结定义。

### 3. 顶层业务 Agent 与内部组件分层

- 顶层业务 Agent 对应用户能理解的一次业务任务，在运行中心形成一个顶层 Execution。
- 内部模型 Agent、Tool 和 Workflow 作为 Operation / Event 进入执行树，不默认形成独立顶层任务。
- 需要单独恢复、单独授权或可被其他业务复用的系统组件，可以注册为 system Agent；否则只作为父 Agent 的 `child_components`。
- `run_center_visible = false` 只影响普通列表展示，不免除 Trace、权限、Schema 和注册约束。

例如一次面试复盘只显示一条“面试复盘”任务，内部 Cleanup、问题提取、逐题分析、忠实度检查和讨论在高级运行详情中展开。

### 4. Registry 成为 Builder 的唯一入口

- `ProductionGraphFactory` 不再维护独立 `PRODUCTION_GRAPH_KINDS` 和分散的类型分支作为第二事实源。
- Registry 的 Definition 直接引用或延迟解析对应 Builder。
- Runtime 只能通过 `registry.resolve(agent_id, definition_version)` 获得 Builder。
- 重复 `agent_id + definition_version`、缺失 Builder、无效 Schema、失效 Eval Pack 或未知能力在应用启动时 fail-fast。

### 5. Session / Execution 接口 fail-closed

创建 Session 时必须先完成：

```text
解析 agent_id / definition_version
  → Registry 存在性与生命周期检查
  → user_creatable 与 Workspace 权限检查
  → 输入 Schema 与能力检查
  → 创建 Session
  → 冻结 Definition Snapshot
  → 创建 Execution
```

- 未注册、disabled 或不允许用户创建的 Agent 在数据库写入前返回稳定 `422` 错误。
- API 不再把任意字符串直接作为持久化 `graph_id`。
- 领域内部创建 system Session 也必须走受信 Factory，并显式携带父业务资源和 Workspace。

### 6. AgentFactory 强制父子组件归属

`AgentFactory.create()` 必须接收当前顶层 `agent_id`、`definition_version` 和 `component_id`：

- `component_id` 必须在父 Definition 的 `child_components` 中声明；
- AgentSpec 使用的 model role、Tool 和 Scope 必须是父 Definition 允许集合的子集；
- Trace Middleware 自动写入顶层 Agent 身份、组件身份和 Definition 版本；
- 产品代码不得绕过该入口直接调用底层 ChatModelResolver。

少数基础设施用途如果必须直接调用模型，需要在 Registry 注册为明确 system component，并通过专用受审 Factory 创建。

### 7. Execution 冻结定义快照

每次 Execution 至少冻结：

```text
agent_id
agent_definition_version
graph_version
prompt_schema_versions
input_schema_version
output_schema_version
toolset_digest
model_binding_digest
context_policy_id
retry_policy_id
trace_policy_id
eval_pack_id + eval_pack_version
```

Registry 表示“当前可以创建什么”；Execution Snapshot 表示“当时实际运行了什么”。Registry 更新不能重写历史 Snapshot。

### 8. 运行中心、控制与质量评估共同消费 Registry

- 运行中心从 Registry 读取展示名、业务入口、业务/系统类型和可见性；从 Execution/领域表读取业务状态；从 Trace/Usage 读取模型、Tool、Token、上下文和耗时。
- 停止、恢复和重试按钮只有在 Definition 声明且当前 Execution 状态机允许时出现。
- Eval Engine 从 Execution Snapshot 读取冻结的 Eval Pack，不用当前 Registry 猜测历史运行应采用的评估标准。
- 前端不得维护 Agent 名单或根据 Event 数量推导业务状态。

### 9. 生命周期和历史兼容

- `active`：允许创建新 Session / Execution。
- `deprecated`：不再作为默认入口，但允许受控恢复已有 Session；创建新任务时返回替代 Agent 提示。
- `disabled`：禁止新建和恢复，只允许查看历史。
- `aliases` 只用于解析稳定的历史 ID，不能创建第二套身份。
- 历史数据遇到 Registry 已删除或插件不可用时，使用只读“历史 Agent / 定义不可用”投影；不得从运行中心消失，也不得重新执行。

因此，新任务创建 fail-closed，历史读取 fail-open。

### 10. 启动和 CI 门禁

启动校验和契约测试至少覆盖：

1. Agent ID、Definition 版本和别名无冲突；
2. 每个 active Definition 有可构建 Builder；
3. 每个 AgentFactory 组件都属于一个父 Definition；
4. model role、Tool 和 Scope 不超过声明范围；
5. 业务 Agent 具有合法业务入口；
6. 声明的运行控制能力有对应 Runtime 命令和状态机测试；
7. Eval Pack、Prompt Schema 和 Trace Policy 引用可解析；
8. 可见业务 Agent 可以生成 ExecutionSummary 并进入运行中心；
9. 产品代码不存在未经批准的底层模型直调；
10. 未注册 Agent 的 API 请求不会生成 Session、Execution 或 Provider 调用。

## 分阶段迁移

### Phase 1：接口门禁与兼容加固

- 在现有 Registry 上增加统一 `require_registration()`；
- Session 创建前拒绝未知、隐藏 system-only 和 disabled Agent；
- 为历史未知 Graph 增加只读兼容投影；
- 增加 API 与零脏数据契约测试。

### Phase 2：收敛单一 Definition 与 Builder

- 引入 `AgentDefinitionRegistry`；
- 把现有 Registration、生产 Graph 集合和 Builder 映射合并；
- 保持现有 `graph_id` 兼容，不进行业务数据重命名；
- 运行中心和 Eval Engine 改读统一 Definition。

### Phase 3：子组件、Tool 与模型调用门禁

- AgentFactory 增加父 Agent / 组件身份；
- 声明 child component、model role、Tool 和 Scope；
- 增加静态扫描或 import 边界，禁止产品代码直调底层模型；
- 补齐 Trace 中 Definition 与组件版本。

### Phase 4：Execution Definition Snapshot

- 增加不可变 Snapshot 持久化和迁移；
- 新 Execution 冻结完整摘要；
- 历史 Execution 使用明确的 legacy snapshot，不反推不存在的版本；
- Eval 与高级运行详情展示冻结版本。

每个 Phase 必须保持旧 Execution 可读，不要求一次性迁移或重跑历史 Agent。

## 结果

正向结果：

- 新 Agent 只完成一次声明即可接入 Runtime、Trace、运行中心、控制和质量评估；
- 未注册 Agent 在调用 Provider 和写入持久状态前失败；
- 业务任务和内部组件层级清晰，运行中心不会被内部步骤淹没；
- Tool、Scope、模型用途和上下文/重试策略成为可审查契约；
- 历史 Execution 可以解释当时实际使用的 Agent 定义；
- 前后端不再依赖分散名单，新增 Agent 的遗漏可以由启动和 CI 发现。

代价与风险：

- 新增 Agent 需要维护更完整的 Definition；
- Registry 会成为关键控制面，需要避免演变为包含全部业务逻辑的巨型模块；
- Builder、Schema 和策略迁移需要分阶段兼容现有 Graph ID；
- 静态扫描不能完全替代运行时校验，两者都需要保留；
- Execution Snapshot 增加少量存储和版本治理成本。

## 不变量

1. 未注册 Agent 不得创建新的 Session、Execution 或 Provider 调用。
2. 影响业务结果的模型调用必须属于已注册业务 Agent 或 system component。
3. Registry 不拥有业务状态，运行中心不得用注册元数据替代领域事实。
4. 一个业务任务默认只有一个顶层 Execution；内部组件进入执行树。
5. Registry 更新不得改写历史 Execution Snapshot。
6. 声明控制能力不等于拥有控制能力；Registry 与 Runtime 状态机必须同时允许。
7. Tool 与 Scope 采用最小权限，运行时实际集合不得超过 Definition 声明。
8. 未注册历史记录不得消失，只能降级为不可恢复的只读记录。
9. Trace 与 Eval 失败继续 fail-open，不得阻塞业务主流程；注册和权限校验在新任务创建时 fail-closed。
10. Registry 属于代码和 Git 管理的发布契约，不由前端或运行数据库任意修改。

## 重新评估条件

- 产品支持第三方 Agent 插件或用户自定义 Agent；
- Agent Builder 可以脱离主应用独立部署；
- 多进程或多节点 Runtime 需要网络服务发现；
- 组织级权限要求动态启用/禁用 Agent；
- Registry 规模或启动校验成本显著影响开发与启动；
- 需要灰度发布同一 Agent 的多个 Definition 版本；
- 外部 Agent 平台成为正式执行面而不再只是 Provider。

## 面试讲述口径

项目早期 Agent 数量少，Graph 选择、业务入口、运行控制和评估绑定散落在不同模块。Agent 增多后，单靠枚举或前端名单无法保证新 Agent 一定进入运行中心，也无法约束内部模型调用、Tool 权限和历史版本。

最终把系统拆成控制面与执行面：Git 版本化的 Agent Registry 统一声明身份、Builder、Schema、子组件、Tool/Scope、运行能力、Trace 和 Eval Pack；Session 创建先解析 Registry，未注册 Agent 在写库和调用 Provider 前失败；Execution 冻结 Agent Definition，使历史运行可复现。顶层业务 Agent 对应运行中心的一条任务，内部子 Agent 只进入 Operation 树。没有引入数据库动态注册或 Consul，因为 Agent 与代码和 Schema 强绑定，静态 Manifest 更容易审查、测试和随版本发布。
