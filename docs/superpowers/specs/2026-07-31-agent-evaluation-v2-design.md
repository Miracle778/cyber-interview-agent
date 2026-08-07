# Agent 质量评估 v2 设计

- 日期：2026-07-31
- 状态：Implemented through isolated regression foundations；真实 Provider 浏览器校准与最终阶段门禁待完成
- 适用范围：质量实验室、全部业务 Agent、公共 Runtime 不变量和真实回归案例
- 关联 ADR：`../architecture-decisions/2026-07-31-agent-evaluation-outcome-and-regression-boundaries.md`
- 迁移计划：`../plans/2026-07-31-agent-evaluation-v2-migration.md`

## 1. 当前能力与成熟度边界

### 1.1 v1 已具备

- 从一次真实 Execution 冻结 Trace 与环境摘要；
- 运行只读 Judge，保存维度分数、证据、风险与置信度；
- Judge 失败不修改业务 Execution；
- 记录人工反馈并保存版本化案例；
- 对同一历史业务结果重新运行质检并比较结果。

### 1.2 v1 尚不具备

- 面向最终领域结果的统一业务结果包；
- 真正验证业务不变量的确定性 Rule；
- `not_applicable / insufficient_evidence`；
- 任务级最小 Judge 视图；
- 让候选版本业务 Agent 重新执行的真实回归；
- 可证明低误报的自动阻断门禁。

因此 v1 的正式产品名称为“初版质检 / 历史结果复检”，不能宣传为已经证明 Agent 改版有效。

## 2. 目标

v2 回答五个彼此不同的问题：

1. 这次业务执行是否留下了足够、可信的评估证据？
2. 最终业务结果是否满足结构、来源、状态与权限不变量？
3. 结果的语义质量如何，哪些结论需要人工复核？
4. 用户最终接受、修改还是拒绝了哪些内容？
5. 候选版本在同一批真实输入上是否比基线更可靠？

## 3. 总体流程

```text
Execution + Domain State + User Decision
                │
                ▼
        BusinessOutcomeProjection
                │
                ├─ Evidence Completeness Check
                ├─ Deterministic Business Rules
                └─ Task-specific EvaluationView
                              │
                              ▼
                        Semantic Judge
                              │
                              ▼
                 Rating + Severity + Confidence
                              │
                              ▼
                        Human Feedback
```

历史复检只重新执行右半部分；真实回归先让基线与候选 Agent 分别生成新的 `BusinessOutcomeProjection`。

## 4. 核心数据契约

### 4.1 BusinessOutcomeProjection

```text
identity
  workspaceId / sessionId / executionId / graphId
  domainObjectIds / domainVersions

input
  taskType / sourceRefs / inputHash / requestedScope

result
  normalizedOutcome / persistedOutcome / terminalState
  skippedItems / mergedItems / degradedItems / failedItems

provenance
  field-level supportType / sourceRef / locator / contentHash

userDecision
  pending / accepted / edited / rejected / ignored
  before / after / reason / occurredAt

runtime
  prompt / model / reasoning / tool / schema / context / code versions
  token / latency / retry / cancellation summary
```

Outcome Adapter 从领域表、Receipt 与 Execution 汇总中构建该投影。Trace 只补充运行解释，不覆盖领域状态。

### 4.2 Applicability

```text
applicable
not_applicable
insufficient_evidence
```

代码可以确定时由代码决定；否则 Judge 给出建议并说明依据。`not_applicable` 与 `insufficient_evidence` 均不计入质量等级聚合。

### 4.3 DimensionResult

```text
dimensionId
applicability
rating: meets | usable | needs_review | severe | null
severity: none | low | medium | high | critical | null
confidence: 0..1 | null
source: deterministic | judge | human
summary
evidenceRefs[]
evidenceGaps[]
```

用户界面使用“符合要求 / 基本可用 / 建议复核 / 严重问题 / 证据不足 / 不适用”，不展示跨 Pack 综合百分制。

### 4.4 关系与来源枚举

来源支持类型：

```text
direct | normalized | inferred | user_asserted | unsupported
```

冲突/版本关系：

```text
contradiction | temporal_change | complementary | duplicate | ambiguous | supersedes
```

题目相似关系：

```text
exact_duplicate | same_core_question | parent_child
related_distinct | revision_candidate | unrelated
```

## 5. 公共 Runtime 不变量

公共 Pack 不评价内容好坏，只检查所有 Agent 共用的工程事实：

- 已完成工作单元单调保留，恢复只处理未完成项；
- 同一幂等键不会重复写业务结果；
- 输入、完成、跳过、失败与待处理数量守恒；
- 停止、失败和迟到结果不能越过领域状态机；
- Workspace 与资源归属一致；
- 未授权 Tool、路径和写入不会执行；
- 业务终态、Receipt 和公开 Event 一致；
- 关键来源 ID、版本、hash 和 locator 可验证。

这些规则先以只读告警运行；只有在真实案例上证明误报足够低，并单独完成架构审批后，才允许成为阻断门禁。

## 6. 任务级 Eval Pack

### 6.1 题目整理 `question-curation.v2`

| 维度 | 判定方式 | 核心问题 |
|---|---|---|
| 材料处理完整性 | Rule | 所有处理单元是否有完成、跳过、失败或待处理归属？ |
| 明确题目识别 | Hybrid | 原文明确列出的题目是否被识别？仅可靠分母存在时计算覆盖率。 |
| 候选完整性 | Hybrid | 题干、答案类型、来源与审核状态是否足够进入后续流程？ |
| 题目来源一致性 | Judge | 题干是否忠实表达原材料主题，没有虚构个人事实？ |
| 原文答案忠实度 | Hybrid | 只评价 `sourceAnswer` 中声称来自材料的内容。 |
| 模型补全质量 | Judge | `supplementalAnswer` 是否正确、有用、不过度确定？ |
| 补全透明度 | Rule | 展示和持久化是否明确区分原文答案与模型补充？ |
| 重复项处理 | Hybrid | 算法是否召回疑似项，关系是否分类，来源是否在合并后保留？ |
| 零结果合理性 | Hybrid | 真正无题、需人工复核与处理失败是否正确区分？ |

示例：材料只有“Redis 为什么快？”这一行。系统补充了一份合理答案时，不能因答案不在原文就把“来源忠实度”判低；正确做法是 `sourceAnswer` 为空、`supplementalAnswer` 有内容，“原文答案忠实度”不适用，转而评价“补全质量”和“补全透明度”。

“明确题目识别”只有在存在版本冻结的本地 Gold manifest 时才计算。可靠分母合同为：

- manifest 绑定 source 内容 SHA-256，原文变化后不得继续复用；
- 每个预期题包含 `kind=explicit|implicit`、稳定 `sourceRefs`、`critical` 和人工确认状态；
- `draft_requires_human_review` 只用于预标注诊断，不进入质量趋势、回归结论或发布门禁；
- 当前运行候选与 Gold 的确定性规范化匹配先给出候选对齐，模糊匹配由人工复核，生成模型不能作为唯一 Judge；
- 报告必须同时展示显式/隐式分母、命中数、漏题清单、关键漏题、精确率和重复率，不能只给一个无分母的“覆盖良好”。

首个本地 Gold Set 使用用户授权的 `Java.md`。原文不复制到仓库；只在被 `.gitignore` 排除的 `docs/verification/question-curation-gold/` 保存本地 manifest。正式门槛为显式召回率不低于 99%、隐式召回率不低于 90%、关键题漏题为 0，并要求精确率不显著低于当前基线。

### 6.2 单题改写 `question-revision.v2`

- 改写意图识别；
- 指令遵循；
- 编辑范围控制；
- 题目核心身份保持；
- 来源与补全边界保持；
- 新错误风险；
- 版本和并发安全。

意图包括措辞编辑、答案纠正、答案补充、范围加深、范围迁移、拆分与合并。核心范围迁移应创建新题或子题，不能静默覆盖旧题。

### 6.3 复习评价 `review-round.v2` / `review-single.v2`

- 每个关键点的业务评价是否合理；
- 覆盖状态是否有真实回答证据；
- 必要追问是否存在且准确指向缺口；
- 不必要或重复追问是否受控；
- 反馈是否先承认已覆盖内容，再说明具体缺口和下一步；
- 提示、解释和完整答案的泄露级别是否符合用户意图。

推进守卫不是 Judge 维度，而是确定性状态机规则：只有必答点全部通过或用户显式跳过，才能进入下一题。

### 6.4 深入讨论 `review-discussion.v2`

- 是否直接回答当前问题；
- 技术内容是否准确；
- 是否承接会话上下文；
- 解释深度是否适配用户意图；
- 不确定性和来源边界是否诚实；
- 讨论消息不能改变正式复习进度。

### 6.5 画像提取 `profile-ingest.v2`

- 字段级 Evidence 对齐；
- 直接来源、规范化、推断、本人补充与不支持是否正确区分；
- 冲突是否分类为矛盾、时间变化、互补、重复或模糊；
- 新建议是否覆盖旧值或丢失来源；
- 无冲突时冲突维度为 N/A，不能记 100 分。

### 6.6 画像评估 `profile-assessment.v2`

- 明确本次范围：全画像、选定分类、选定 Claim 或选定材料；
- 区分字段缺失、资料未记录、本次未评估和表达问题；
- Gap、风险和建议必须关联 Claim/字段及判断依据；
- 不使用“画像完整度百分比”；
- 资料未写某项经历不能推断用户没有该经历。

### 6.7 画像助手 `profile-assistant.v2`

- 直接回答、事实依据和上下文连续性；
- Tool 是否确有必要、是否遵守角色 allowlist 与预算；
- Tool 结果是否真正用于回答；
- 多项证据是否批量检索，避免重复调用；
- 待确认 Proposal 不得表述成“已经保存”；
- 隐私与领域范围是否受控。

### 6.8 画像写入边界 `profile-write-boundary.v2`

纯确定性检查：Proposal、领域服务、用户确认、expected version、Receipt、Workspace 与幂等。Judge 只检查面向用户的状态文案是否误导。

### 6.9 岗位要求分析 `job-requirement-analysis.v2`

先按段落分类：公司信息、岗位信息、团队背景、职责、必需要求、加分项、福利、标题、未知。混合段落先拆分。

- 岗位段落分类合理性；
- 输出中不混入团队背景和福利；
- 原子要求不过拆、欠拆，保留限定词、对象与 AND/OR；
- 显式要求与系统推断的准备建议分开；
- `document[start:end] == quote`，必要时服务端反查精确 quote；
- 旧 JD 版本仍能定位旧建议来源。

### 6.10 项目深挖辅导 `project-deep-dive-coaching.v2`

- 下一问是否针对真实信息缺口，而不是单纯追求“难”；
- 是否承接上一轮回答且不重复；
- 是否一次只解决一个重点；
- 用户项目事实、用户当轮陈述、系统推断和通用建议是否分开；
- 对角色、技术方案、指标、因果和时间线等高风险事实是否有依据；
- 建议是否具备 gap、原因、下一步、完成条件、所需证据和优先级；
- Gap 使用稳定 ID，并区分信息、证据、表达、知识、经验与冲突。

### 6.11 项目题生成 `project-question-generation.v2`

- 项目事实依据；
- 面试价值；
- 不直接泄露答案；
- 单题焦点；
- 与目标岗位要求的关联；
- 与题库已有题的关系；
- 保存 `projectFactRefs / deepDiveMessageRefs / targetRequirementRefs / expectedAnswerAreas`。

系统不强制每个项目生成固定六类题，也不能虚构用户没有提供的职责、技术方案或指标。

## 7. 隐私与 Judge 输入

每个 Pack 定义独立 `EvaluationViewBuilder`：

- 只选该任务需要的字段和短摘录；
- 使用稳定引用与 hash，不发送本地路径；
- Secret 永不进入；
- 默认裁剪联系方式、证件、账号等敏感个人信息；
- Judge Provider、模型、发送字段类别和正文范围对用户可见；
- 需要完整私有 Trace 时必须明确授权并记录元数据审计。

## 8. 历史复检

用途：验证 Eval Pack、Judge Prompt 或 Judge 模型变化后，对同一历史结果的判断是否变化。

它不能回答业务 Agent 是否改好。页面必须使用“重新质检历史结果”，并展示：

- 业务结果没有重新生成；
- 使用的 v1/v2 Pack 与 Judge 版本；
- 新旧评估结论差异；
- 证据不足和不适用维度。

## 9. 真实回归

### 9.1 EvalCase

```text
caseId / version / workspaceId
taskType / sanitizedInput / requiredDomainSnapshot
expectedInvariants / privacyManifest
baselineVersions / sourceExecutionId
```

### 9.2 执行

1. 在隔离测试 Workspace 或事务中恢复输入和必要领域状态；
2. 使用基线版本运行一次业务 Agent；
3. 使用候选版本运行一次业务 Agent；
4. 生成两份业务结果投影；
5. 执行确定性规则；
6. Judge 以盲测方式做 pairwise 比较，不显示“基线/候选”标签；
7. 高风险或分歧案例进入人工确认；
8. 保存版本、基础设施失败、质量结论与波动信息。

普通案例默认一次，避免无意义消耗；高风险案例或结果不稳定时运行三次。网络超时、Provider 限流、数据库锁等基础设施错误单列，不直接记作内容质量退化。

## 10. 趋势与展示

首版 v2 趋势只展示同一 Pack/version 内可比较的指标：

- 确定性规则失败率；
- 需要人工复核率与严重问题率；
- Judge–人工一致率；
- 用户编辑、拒绝和撤回率；
- 基础设施失败率；
- 延迟、Token 与上下文变化。

不把不同 Agent、不同 Pack 或 v1/v2 的分数放在一张总榜上。

### 10.1 单次运行质量页的来源和层级

- 从运行中心进入质量页时，页面必须固定到该 `executionId`，并明确展示来源任务、状态和时间；
- 该来源尚无质量报告时展示空状态或检查失败，不得用最新的其他历史报告代替；
- 默认阅读顺序为“本次是否可用 → 优先处理什么 → 具体维度”，检查方法和技术设置折叠到次级区域；
- 历史对比必须由用户显式开启，只允许同一 Eval Pack、Pack version、contract version 和 run kind 的结果进入候选；
- Token、Runtime、内部计数等技术指标默认隐藏，用户主动查看技术指标或开启兼容历史对比后再展示；
- 某个来源 Agent 不支持评估或本次检查失败时，只影响该来源的状态，不污染其他业务 Execution，也不展示不相关报告。

## 11. 验收边界

v2 基础能力完成时，只能声称“评估对象、适用性、分级结论与隐私边界已收敛”。

只有以下条件全部满足，才能声称“可验证 Agent 改版效果”：

- 候选业务 Agent 确实在冻结输入上重新运行；
- 基线与候选版本信息完整；
- 确定性规则基于最终业务结果；
- pairwise Judge 不知道版本身份；
- 基础设施失败与质量失败分离；
- 至少一批真实案例完成人工校准；
- 回归运行不写入正式业务数据。
