# 前端 MVP 复习闭环产品设计

## 1. 背景

当前项目已经完成了前后端技术骨架和一组可测试的后端能力：

- 初始化 workspace 和 Obsidian-compatible Vault。
- 测试 Provider 配置形态。
- 上传资料并生成题库草稿。
- 扫描 Vault Markdown 并写入 SQLite FTS 索引。
- 调用 LangGraph 复习 agent 生成回答评估和单轮报告草稿。
- 确认报告并写入 session report 和 mastery update draft。

但这些能力主要通过后端测试或 `curl` 验证，前端页面仍是静态占位。用户在浏览器里无法走完整个流程，因此产品体感像空架子。

本 spec 的目标是把已有后端能力串成一个可以手动操作的浏览器 MVP demo。

## 2. 目标

用户可以在一个浏览器页面中完成最小复习闭环：

1. 输入 workspace path，初始化 Vault。
2. 输入 Provider 基础信息，执行连接测试。
3. 上传一份资料，看到生成的题库草稿。
4. 用题库草稿开始一次复习。
5. 输入回答，调用复习 agent，看到评分、缺失点和报告草稿。
6. 确认报告，看到 session report 和 mastery report 的写入路径。
7. 手动触发 Vault rescan，看到索引文档数量。

这个目标完成后，用户能直观看到“这个项目现在到底能跑什么”。

## 3. 非目标

本阶段不做：

- 真实 LLM Provider 调用。
- API key 加密存储。
- 多题批量复习。
- 会话持久化列表。
- 知识文档完整列表。
- Obsidian 图谱或关系图 UI。
- 文件拖拽、多文件批量上传。
- Provider 多配置保存和切换。
- 样式系统和复杂布局打磨。

## 4. 推荐方案

### 方案 A：单页串联式 MVP Demo

在当前 `AppShell` 的三个 section 内，把表单和后端 API 接起来。页面仍然是简单纵向结构，但每一步都有状态和结果。

优点：

- 改动最少。
- 最快获得可操作闭环。
- 便于用现有测试覆盖。

缺点：

- UI 不够精致。
- 页面状态会集中在前端内存里，刷新后丢失。

### 方案 B：Wizard 流程

把流程改成步骤式：设置 -> 上传 -> 复习 -> 确认报告。

优点：

- 用户路径更清晰。
- 更符合 onboarding 体验。

缺点：

- 会引入路由或步骤状态管理。
- 当前基础能力还粗糙，过早做流程包装容易遮住真实能力边界。

### 方案 C：后端优先继续增强

继续补真实 Provider、LLM 题库生成、持久化会话，再接前端。

优点：

- 后端能力更扎实。

缺点：

- 用户仍然只能用 `curl` 感受产品。
- 不能解决“看起来像空架子”的核心问题。

推荐采用 **方案 A：单页串联式 MVP Demo**。它最适合当前阶段：先把已有能力露出来，形成真实可操作的最小闭环。

## 5. 页面设计

### 5.1 AppShell

保留现有页面结构：

- 标题：`Cyber Interview Agent`
- 说明：`复习闭环 MVP`
- `SettingsPage`
- `ReviewPage`
- `KnowledgePage`

为了让流程更自然，页面展示顺序调整为：

1. `SettingsPage`
2. `KnowledgePage`
3. `ReviewPage`

理由：用户必须先初始化 workspace，再上传资料，最后复习。

### 5.2 SettingsPage

当前设置页是静态表单。本阶段把它变成可操作表单。

字段：

- Provider 名称。
- Base URL。
- Model ID。
- Workspace Path。

操作：

- `测试连接`
  - 调用 `POST /api/settings/providers/test`。
  - 显示 `ok` 或 `failed`。
  - 当前只验证配置形态，不做真实模型请求。

- `初始化工作区`
  - 调用 `POST /api/settings/workspace`。
  - 成功后显示 workspace path 和 vault path。
  - 将 workspace config 保存在前端内存状态，供知识页和复习页使用。

状态展示：

- 未配置。
- 初始化中。
- 初始化成功。
- 初始化失败，显示错误消息。

### 5.3 KnowledgePage

当前知识页只有两个按钮。本阶段增加文件上传、题库草稿展示和 rescan 结果。

前置条件：

- 必须已有 workspace。
- 如果没有 workspace，页面显示“请先初始化工作区”，上传和 rescan 按钮禁用。

操作：

- 选择文件。
- 点击 `上传资料`。
  - 调用 `POST /api/knowledge/sources`。
  - 成功后展示返回的题库草稿。
  - 将题库草稿保存到前端内存状态，供 ReviewPage 使用。

- 点击 `重新扫描 Vault`。
  - 调用 `POST /api/knowledge/rescan`。
  - 显示 `indexed` 数量。

题库草稿展示字段：

- title。
- questionText。
- referenceAnswer，允许折叠或以 `<pre>` 展示。
- topics。
- difficulty。
- keyPoints。
- mastery。

### 5.4 ReviewPage

当前复习页由会话列表、对话区、设置区组成。本阶段只做单题单轮复习。

前置条件：

- 必须已有题库草稿。
- 如果没有题库草稿，显示“请先上传资料生成题库草稿”。

复习设置：

- questionCount 固定默认 1。
- mode 默认 `weak-point`。
- selectedTopics 默认空数组。

对话区：

- 展示当前题目。
- 用户输入回答。
- 点击 `发送回答`。
  - 调用 `POST /api/review/run`。
  - 展示 evaluation：
    - score。
    - missingKeyPoints。
    - evidence。
  - 展示 reportMarkdown。

报告确认：

- 当 reportMarkdown 存在时显示 `确认报告`。
- 点击后调用 `POST /api/review/reports/confirm`。
- 成功后展示：
  - reportPath。
  - masteryPath。

会话列表：

- 本阶段保持简单。
- 如果已运行过一次复习，显示一个静态会话项：`本轮复习`。
- 不做多会话持久化。

## 6. 前端状态设计

为了保持本阶段简单，使用 React 本地状态即可，不引入全局 store。

`AppShell` 持有跨页面状态：

```ts
interface MvpFlowState {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string | null;
}
```

传给子组件：

- `SettingsPage` 负责设置 `workspace`。
- `KnowledgePage` 消费 `workspace`，设置 `draftQuestion`。
- `ReviewPage` 消费 `workspace` 和 `draftQuestion`，设置 `latestReportMarkdown`。

理由：

- 当前只有一个单页 demo。
- 状态关系很少。
- 避免过早引入 Zustand 或复杂上下文。

如果后续要做会话列表、持久化、跨页面路由，再升级为 TanStack Query + store。

## 7. API 对接

### 7.1 Settings

已有 API 封装：

- `getWorkspace()`
- `initializeWorkspace(workspacePath)`

需要新增：

- `testProviderConnection(provider)`

调用：

```http
POST /api/settings/providers/test
```

### 7.2 Knowledge

已有 API 封装：

- `uploadSource(workspacePath, file)`

需要新增：

- `rescanVault(workspacePath)`

调用：

```http
POST /api/knowledge/rescan
```

### 7.3 Review

已有 API 封装：

- `runReview(payload)`

需要新增：

- `confirmReport(workspacePath, reportMarkdown)`

调用：

```http
POST /api/review/reports/confirm
```

## 8. 错误处理

所有前端 API 调用都需要显示错误消息。

最小规则：

- 请求开始时禁用按钮。
- 成功后显示结果。
- 失败后显示错误文本，不清空用户已输入内容。
- 没有 workspace 时禁用依赖 workspace 的动作。
- 没有 draft question 时禁用复习动作。
- 没有 reportMarkdown 时禁用确认报告。

前端错误消息使用普通文本即可，不做 toast 系统。

## 9. 测试策略

### 9.1 前端单元测试

新增或更新：

- `SettingsPage.test.tsx`
  - 输入 workspace path。
  - 点击初始化按钮。
  - mock API 成功后展示 vault path。

- `KnowledgePage.test.tsx`
  - 无 workspace 时按钮禁用。
  - 有 workspace 时上传成功后展示 draft question。
  - rescan 成功后展示 indexed 数量。

- `ReviewPage.test.tsx`
  - 无 draft question 时提示先上传。
  - 有 draft question 时输入回答，展示 score 和 missing key points。
  - 确认报告后展示 reportPath 和 masteryPath。

### 9.2 后端测试

本 spec 不要求新增后端能力。已有测试必须继续通过：

```bash
cd backend && uv run pytest
```

### 9.3 E2E 测试

更新 `tests/e2e/mvp-smoke.spec.ts`，从“看到三个 heading”升级为“页面能展示主要操作入口”。

不强制在 E2E 中上传真实文件和调用后端，因为当前 Playwright 只启动前端 dev server，不启动后端。完整端到端走通可以放到下一阶段增加。

## 10. 验收标准

完成后必须满足：

1. 用户打开前端页面，能看到设置、知识文档、复习三个区域。
2. 设置页可以输入 workspace path，并展示初始化成功结果。
3. 设置页可以测试 Provider，并展示连接状态。
4. 知识页可以上传资料，并展示题库草稿。
5. 知识页可以触发 rescan，并展示 indexed 数量。
6. 复习页可以基于题库草稿提交回答，并展示 evaluation 和 reportMarkdown。
7. 复习页可以确认报告，并展示 reportPath 和 masteryPath。
8. 刷新页面后状态可以丢失，本阶段允许。
9. `pnpm --dir frontend test` 通过。
10. `pnpm --dir frontend build` 通过。
11. `cd backend && uv run pytest` 通过。
12. `pnpm --dir frontend e2e` 通过。

## 11. 当前刻意保留的粗糙点

- Provider 测试仍不是真实模型请求。
- 题库草稿生成仍然是首行和全文片段规则。
- 复习评估仍然是关键词匹配。
- 只支持一个 draft question。
- 不做跨刷新持久化。
- 不做多会话、多轮、多题。
- 不做正式 UI 样式系统。

这些限制需要在页面上用结果状态体现，而不是假装已经完成完整产品能力。

## 12. 后续计划

本 spec 完成后，下一步再拆实现计划，建议任务顺序：

1. 重构 AppShell 状态，把 workspace/draft/report 串起来。
2. SettingsPage 接 API。
3. KnowledgePage 接上传和 rescan。
4. ReviewPage 接 runReview 和 confirmReport。
5. 更新前端测试和 E2E。
6. 写一版手动验证说明，更新 `docs/mvp_verification_guide.md`。
