# Agent 质量中心与面试复盘评估实施计划

> 对应设计：`../specs/2026-08-04-agent-quality-center-and-retrospective-evaluation-design.md`

**目标：** 补齐面试复盘的 v2 质量评估能力，建立注册中心的评估能力不变量，并将质量页面重构为“质量检查 / 回归实验 / 质量趋势”三个清晰入口。

**实施策略：** 保留现有 Evaluation Run、Rating、Regression Case、Trend 和历史路由契约；新增一个 `interview-retrospective.v2` Pack，通过 Outcome Adapter 和适用性视图覆盖复盘不同模式。前端复用现有报告、案例和趋势组件，只重组入口、主流程和支持状态，避免重写已验证能力。

**技术栈：** Python、Pydantic、SQLite、pytest、React、TypeScript、TanStack Query、Vitest、Testing Library。

---

## Task 1：锁定 Agent 注册与评估能力契约

**文件：**

- 修改：`backend/tests/test_agent_observability_registry.py`
- 修改：`backend/tests/test_agent_eval_pack_registry.py`
- 修改：`backend/app/agents/definition_registry.py`
- 修改：`backend/app/evaluation/registry.py`
- 修改：`backend/app/evaluation/service.py`

### 1.1 先写失败测试

- 构造声明 `manual_judge` 但没有 `eval_pack_id` 的 Agent Definition，断言注册失败；
- 构造绑定未知 Pack 的生产注册表引用，断言注册表一致性测试失败；
- 断言 `interview.retrospective` 绑定 `interview-retrospective.v2`；
- 断言该 Pack 在兼容映射中可被复盘 Execution 使用。

### 1.2 运行 RED

```bash
cd backend
uv run pytest -q tests/test_agent_observability_registry.py tests/test_agent_eval_pack_registry.py
```

预期：新不变量和复盘 Pack 断言失败。

### 1.3 最小实现

- `AgentDefinitionRegistry` 校验 `manual_judge` 与 `eval_pack_id` 双向一致；
- 为 `interview.retrospective` 绑定新 Pack；
- 在 Pack Registry 与兼容映射中登记新 Pack；
- 保持历史快照冻结语义，不修改既有数据库记录。

### 1.4 运行 GREEN

执行 1.2 的同一组测试并确认通过。

## Task 2：实现面试复盘 Outcome Adapter 与适用性视图

**文件：**

- 修改：`backend/app/evaluation/packs/v2_tasks.py`
- 修改：`backend/app/evaluation/outcome_adapters/domain.py`
- 修改：`backend/app/evaluation/views.py`
- 修改：`backend/app/evaluation/business_rules.py`
- 新增或修改：`backend/tests/test_interview_retrospective_evaluation.py`
- 修改：`backend/tests/test_business_evaluation_rules.py`

### 2.1 先写失败测试

覆盖四类真实结果投影：

- 整理：已确认文字、待确认修订、来源范围和用户决策；
- 分析：明确题、推断题、证据定位、逐题结论与改进建议；
- 讨论：用户消息、助手消息、工具调用结果与正式结果隔离；
- 历史检索：检索集、命中来源、总结和报告引用。

断言：

- 不同模式只启用适用维度；
- 没有证据时返回 `insufficient_evidence`，不是低分；
- 推断题未经确认时触发确定性关注项；
- 讨论消息不能被投影成正式逐题分析；
- 历史总结中的来源必须落在检索命中集合中。

### 2.2 运行 RED

```bash
cd backend
uv run pytest -q tests/test_interview_retrospective_evaluation.py tests/test_business_evaluation_rules.py
```

### 2.3 最小实现

- 新增 `INTERVIEW_RETROSPECTIVE_V2_PACK`；
- `SqliteOutcomeAdapter` 新增 `interview_retrospective` 分支；
- 根据 Execution/session/domain refs 识别 cleanup、analysis、chat、history 模式；
- 只读取评估所需字段，限制长文本和列表数量；
- 新增复盘专用适用性规则，通用 Judge View 继续负责脱敏与大小限制；
- 增加推断题确认边界、讨论写入隔离和历史来源覆盖的确定性规则。

### 2.4 运行 GREEN

执行 2.2 的同一组测试并确认通过。

## Task 3：重构质量中心顶层信息架构

**文件：**

- 修改：`frontend/src/features/evaluation/EvaluationLabPage.test.tsx`
- 修改：`frontend/src/features/evaluation/EvaluationLabPage.tsx`
- 修改：`frontend/src/features/evaluation/EvaluationOverview.tsx`
- 修改：`frontend/src/features/evaluation/evaluation.css`
- 修改：`frontend/src/features/evaluation/evaluationPresentation.ts`

### 3.1 先写失败测试

断言默认页面：

- 标题为“Agent 质量中心”，说明质量检查用途；
- 顶层存在“质量检查 / 回归实验 / 质量趋势”；
- 默认质量检查按“选择运行 / 查看结果 / 人工确认”组织；
- 同一层级不再出现“高级评估”和重复“运行中心”；
- 未含 `manual_judge` 的 Execution 显示“暂不支持检查”，且没有可提交的开始按钮；
- 支持的未检查运行可以进入检查流程；
- 历史 `view=overview/tools` 参数仍能映射到新入口。

### 3.2 运行 RED

```bash
cd frontend
npm test -- --run src/features/evaluation/EvaluationLabPage.test.tsx
```

### 3.3 最小实现

- 将顶层 surface 改为 `check | regression | trends`；
- 质量检查复用 Overview 与现有 Report，但采用单一主流程；
- 回归实验承载 Compare 与 Regression Case；
- 趋势入口只承载趋势组件；
- `EvaluationOverview` 从 Execution capabilities 判断支持状态；
- 添加 `interview-retrospective.v2` 和新维度中文标签；
- 保留报告深链和对应运行入口。

### 3.4 运行 GREEN

执行 3.2 的同一组测试并确认通过。

## Task 4：重排报告与人工确认区

**文件：**

- 修改：`frontend/src/features/evaluation/JudgeResultPanel.tsx`
- 修改：`frontend/src/features/evaluation/RegressionCasePanel.tsx`
- 修改：`frontend/src/features/evaluation/EvaluationTrendsPanel.tsx`
- 修改：`frontend/src/features/evaluation/evaluation.css`
- 修改或新增相应组件测试。

### 4.1 先写失败测试

- 首屏只显示总结、1～3 个重点问题、来源标签和推荐动作；
- 人工判断提供“确认无问题 / 确认有问题 / 暂不判断”；
- 保存回归案例是可选后续动作；
- 技术指标、完整维度和原始结果默认折叠；
- 趋势空状态说明需要先完成质量检查；
- 状态同时有文字和图标，不只依赖颜色。

### 4.2 实现与样式

- 保持现有接口，不改变反馈 verdict 和案例数据结构；
- 减少同时可见的技术面板；
- 桌面端详情优先阅读宽度，窄屏改为列表到详情；
- 交互目标至少 44px，聚焦样式可见；
- 只使用现有设计 Token。

## Task 5：回归、浏览器验收与验证记录

**文件：**

- 更新本地：`docs/verification/interview-retrospective-agent.md`
- 如现有质量评估验证文档有独立文件，则同步补充质量中心验收证据。

### 5.1 后端定向回归

```bash
cd backend
uv run pytest -q \
  tests/test_agent_observability_registry.py \
  tests/test_agent_eval_pack_registry.py \
  tests/test_interview_retrospective_evaluation.py \
  tests/test_agent_evaluation_v2_contracts.py \
  tests/test_business_evaluation_rules.py \
  tests/test_agent_evaluation_routes.py
```

### 5.2 前端定向回归

```bash
cd frontend
npm test -- --run \
  src/features/evaluation/EvaluationLabPage.test.tsx \
  src/features/evaluation/EvaluationQualityRail.test.tsx \
  src/features/evaluation/EvaluationTrendsPanel.test.tsx \
  src/features/evaluation/RegressionCasePanel.test.tsx
npm run build
```

### 5.3 浏览器验收

在本地真实页面检查：

1. 支持评估的面试复盘运行能开始检查；
2. 不支持评估的历史运行展示明确原因且不能误提交；
3. 三个入口切换后状态和深链正确；
4. 人工判断和回归案例保存正常；
5. 1440、1024、768、390px 无整页横向滚动；
6. 键盘可访问顶层导航、运行列表、展开区和判断操作。

### 5.4 收尾

- 运行 `git diff --check`；
- 汇总产品状态、成熟度边界和未覆盖风险；
- 更新验证记录，不提交 `docs/verification/`；
- 实现代码与正式文档按范围创建本地提交。

