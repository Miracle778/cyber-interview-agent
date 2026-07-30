# ADR：本地 Trace Ledger 与独立质量评估边界

- 状态：Accepted
- 决定日期：2026-07-29
- 适用范围：项目内全部 Runtime Agent、模型调用、Tool 调用和领域 Graph
- 关联设计：`../specs/2026-07-29-agent-observability-and-quality-workbench-design.md`

## 背景

项目已经具备：

- per-Execution 本地 JSONL 完整诊断轨迹；
- 产品安全事件和 SSE；
- Token 与上下文 Usage 投影；
- 可选 OTel 元数据投影；
- Session、Execution、Checkpoint 与领域状态。

这些能力分别服务诊断、产品 UI、计量、远程监控和恢复，但缺少统一查询入口、保留策略和质量评估闭环。直接用 UUID 文件名查 JSONL 只适合临时排障，不能成为产品能力；把完整正文默认发送到外部系统又不符合本地优先和隐私边界。

## 决策驱动因素

- 用户需要查看整个项目全部 Agent，而不是某个业务页面的局部运行。
- 普通用户需要透明进度，高级用户需要完整 Trace，两者披露级别不同。
- Agent 质量不能只靠一次人工体验或测试是否通过。
- Trace 失败不能影响业务，评估失败不能改变业务结果。
- 高风险领域写入必须继续受领域服务与 HITL 控制。

## 候选方案

### 方案 A：只增加 JSONL 文件浏览器

拒绝。

- UUID 难以查找；
- 无法高效跨 Agent 查询；
- 不支持实时汇总、保留策略和评估关联；
- 容易把敏感正文直接暴露给普通用户；
- 无法形成可重复的质量回归。

### 方案 B：以 Langfuse 或 OTel 后端为权威

拒绝作为权威来源。

- 需要额外服务、网络和配置；
- 远程服务不可用时不应损失本地诊断；
- 完整 Prompt、简历、JD 和回答存在隐私风险；
- 外部产品的数据模型不能替代本项目的领域身份、Workspace 归属和安全边界。

保留它们作为用户主动配置的可选投影。

### 方案 C：新建独立 Observability Gateway

拒绝。

- 会复制 Runtime、身份、事件和安全边界；
- 目前单机本地产品没有独立服务的必要；
- 增加部署与一致性成本。

### 方案 D：本地 Trace Ledger + 独立 Eval Engine

采用。

- 保留 JSONL 完整正文；
- 增加 SQLite 可重建索引；
- 通过统一只读 API 服务三层产品页面；
- Eval Engine 消费冻结案例和 Trace，不参与业务状态机；
- OTel / Langfuse 只接收安全投影。

## 决定

### 1. 权威来源

- 业务事实：领域表与 Session / Execution；
- 运行恢复：LangGraph checkpoint 与领域状态；
- 普通 UI：Product Event 安全投影；
- 完整诊断正文：本地 JSONL；
- Trace 查询：可从 JSONL 重建的 SQLite 索引；
- 质量结论：版本化 Eval Pack 产生的 Eval Result。

任何一层都不得反向替代另一层。

### 2. Trace Ledger

- JSONL 保持 append-only 和 per-Execution；
- SQLite 保存身份、层级、状态、时间、用量、版本、错误摘要和正文定位；
- 大型正文保存为 Workspace 内受控 Artifact；
- API 不暴露本机路径；
- Trace、索引和 Artifact 全部受 Workspace 所有权校验；
- Trace 捕获和索引失败均 fail-open。

当前生产写入 Trace v2，Reader 兼容可能存在的 v1 历史记录；完整 Operation 父子树通过下一版 Schema 增量实现。历史记录不得被重写，也不得推测缺失父子关系。Eval 依赖字段不足时必须返回“证据不足”。

### 3. 产品披露

- 普通查看只显示公开业务阶段和安全摘要；
- 当前产品没有用户或权限系统；高级正文通过本地“高级诊断模式”开关读取；
- 本地开关只控制产品披露，不替代 Workspace、资源归属和路径校验；
- secret 永不保存；
- Provider thinking/reasoning 只在真实返回时展示，不能推测；
- 查看、复制和导出完整正文需要审计。

### 4. 保留策略

- 元数据默认长期保留；
- 完整正文默认保留 90 天；
- Workspace 可配置永久、定期清理或不保存正文；
- 清理后保留 hash、大小、时间和原因；
- Workspace 删除覆盖普通保留策略。

### 5. 质量评估

- 使用“共用质量内核 + 角色专用、版本化 Eval Pack”；
- 每个业务 Agent 绑定自身 Pack；系统组件只有在失败、降级或采样命中时使用对应 Pack；
- 评估 Invocation、Trajectory、Outcome 和 Longitudinal 四层；
- 确定性规则可以阻断发布；
- LLM Judge 主观评分不能自动阻断，只能提示或要求人工复核；
- 高风险操作继续由领域规则和 HITL 决定；
- Eval 失败为未评估，业务 fail-open；
- Judge 调用自身也必须记录 Trace。

自动 Judge 只覆盖失败、部分成功、降级、用户拒绝或大幅修改结果，以及普通成功的默认 5% 样本；每 Workspace 默认每日最多 20 次自动 Judge。用户可人工触发 Judge，该操作只消费冻结 Execution，不重跑业务 Agent。

首版 Eval Pack 在代码/Git 中定义并版本化；UI 只读展示 Pack，只允许配置启用、采样率、每日上限和 Judge 模型，不提供任意 Prompt 编辑器。

Eval Engine 使用隔离的只读快照和安全 Tool Adapter，不能写入正式候选、画像、知识、求职目标或业务 Receipt；Judge 结果与人工反馈并存，不能被覆盖修改。

### 6. 回归案例

- 真实失败可冻结为版本化回归案例；
- 案例保存必要的脱敏输入、期望不变量、来源 Trace 和环境摘要；
- 基线与候选使用相同案例、工具和参数比较；
- 优先展示分项证据和 pairwise 结论，不依赖单一总分；
- 用户对结果的修改、接受和拒绝可以形成反馈，但不能直接充当绝对正确标签。
- 自动 Judge 不永久冻结完整私有正文；加入回归集前由用户预览最小脱敏快照；
- 回归案例独立于 90 天 Trace 保留期，直到用户删除或 Workspace 删除；
- 修改与再次脱敏创建新版本，不重写历史；
- 外部投影默认不发送回归案例正文。

### 7. 外部投影

- OTel / Langfuse 默认仅投影元数据、耗时、状态、用量和安全分数；
- 完整正文需要用户显式配置和隐私提示；
- 外部系统不可成为恢复、Workspace 校验或业务写入依赖；
- 外部投影失败只产生 warning。

### 8. Registry 与统计口径

- 所有业务 Agent 和影响产品结果的系统模型组件都必须进入 `Agent Observability Registry`；
- Registry 声明稳定名称、展示名、业务入口、业务/系统类型、可用控制能力、Prompt/Schema 版本、Eval Pack 和敏感级别；
- 默认产品列表只显示顶层业务 Execution；内部 Agent 和系统组件在执行树中展示；
- 用户打开“包含系统 Agent”后才把系统组件纳入筛选；
- 业务状态、阶段、进度和产物数量以 Execution 与领域汇总为准；
- Token、上下文、模型/Tool 调用和耗时以 Trace/Usage 为准；
- 前端不得累加 Event 推导业务完成状态。

### 9. 运行控制与 Workspace

- 停止、暂停、恢复和重试只在 Registry 声明且原 Execution 状态机支持时出现；
- 控制动作复用原命令、幂等键和 Receipt，不建立第二控制平面；
- 默认只查看当前 Workspace；
- “全部 Workspace”只提供安全汇总，不能直接读取正文或执行控制；
- Workspace 删除同时清理 Trace、索引、Artifact 和回归案例。

### 10. 指标边界

产品展示 Token、上下文、首 Token 耗时、总耗时、模型调用数和 Tool 调用数，不展示费用，也不维护 Provider 价格表。

## 结果

正向结果：

- 全项目 Agent 可以统一查看和筛选；
- 临时排障能力演进为稳定产品能力；
- 真实失败可转为持续回归资产；
- 本地隐私与外部生态兼容；
- 业务、诊断、评估和远程监控边界清晰。

代价：

- 需要维护 JSONL 与索引的一致定位和重建工具；
- 完整正文有磁盘与隐私成本；
- Eval Pack 需要按 Agent 角色持续演进；
- 高级页面需要处理大量、长文本和不完整 Trace；
- Judge 仍有模型偏差，必须保留人工与确定性证据。

## 不变量

1. Trace 不是业务真相。
2. Eval Result 不直接执行领域写入。
3. Judge 不拥有高风险门禁最终决定权。
4. secret 永不进入 Trace。
5. 普通 UI 不暴露完整私有正文。
6. Trace 与 Eval 失败不影响业务主流程。
7. 所有资源都必须校验 Workspace 所有权。
8. 用户可见时间统一为北京时间。
9. Trace 解释业务运行，但不决定业务状态。
10. 评估运行不得写入正式业务数据。

## 重新评估条件

- 产品进入多用户或远程部署；
- 单 Workspace Trace 规模超过本地 SQLite / JSONL 的合理上限；
- 多进程写入使当前 append 与索引策略不足；
- 需要组织级权限、集中审计或跨设备同步；
- 外部 observability 被明确选为部署必需组件；
- Judge 的稳定性足以承担新的、经过正式决策的门禁职责。
