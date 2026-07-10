# P1 MVP 质量补强产品设计

## 1. 背景

P0 已经完成浏览器中的最小复习闭环，并由用户手动验证过：

1. 初始化 workspace。
2. 测试 Provider 配置。
3. 上传资料并生成题库草稿。
4. 输入回答并运行复习评估。
5. 确认报告并写入 Vault。
6. 重新扫描 Vault 索引。

但 P0 的目标是“能跑通”，不是“稳定好用”。当前仍存在这些问题：

- 启动前后端需要用户记住多条命令。
- 前端刷新后跨页面状态会丢失。
- 页面不知道后端是否启动，API 失败时用户不容易判断原因。
- workspace 虽然后端有 `GET /api/settings/workspace`，但前端没有在启动时恢复。
- 错误提示仍偏技术化，缺少“下一步该怎么办”。
- 没有内置示例资料，用户第一次验证需要自己准备文件。
- 文档与实际当前 UI、成熟度状态容易不同步。

P1 的目标不是新增大业务能力，而是把 P0 打磨成可以反复手动试用、失败时能排查的 MVP。

## 2. 目标

P1 完成后，用户应该能更稳定地完成以下事情：

1. 用清晰入口启动前端和后端。
2. 打开页面后知道后端是否可用。
3. 刷新页面后能恢复已初始化的 workspace。
4. 页面能清楚展示当前流程进度和下一步动作。
5. 出错时看到“发生了什么”和“下一步怎么处理”。
6. 使用仓库内示例资料完成一次完整手动验证。
7. 在 `docs/verification/` 下看到本次改动说明和人工验证指南。

## 3. 非目标

P1 不做：

- 真实 LLM Provider 调用。真实 LLM 已单独规划为 P1.5。
- API key 存储或加密。
- 多题复习。
- 会话历史持久化。
- 题库管理 CRUD。
- 完整知识库文档列表。
- Obsidian 图谱。
- 桌面端、移动端或账号系统。
- 大规模后端重构。

## 4. 推荐方案

### 方案 A：质量补强层

在现有 P0 单页闭环上增加“质量补强层”：

- 增加后端健康检查 API 封装。
- `AppShell` 页面加载时恢复 workspace。
- `AppShell` 持有更明确的流程状态。
- 三个页面统一错误呈现方式。
- 仓库内提供示例资料和验证说明。
- 增加更具体的单测/E2E。

优点：

- 改动集中，风险小。
- 不改变 P0 架构。
- 适合 Claude 分 task 实现。

缺点：

- 仍然是单页本地 MVP，不解决长期架构问题。
- workspace 只恢复后端内存中的当前配置，后端重启后仍需重新初始化。

推荐采用方案 A。

### 方案 B：提前引入全局状态和路由

引入 React Router、TanStack Query、全局 store，把流程拆成多个页面。

优点：

- 更接近未来产品架构。

缺点：

- P1 阶段过重。
- 会把质量补强和架构迁移混在一起。
- 容易影响已验证的 P0 流程。

不推荐 P1 使用。

### 方案 C：先接真实 LLM

直接进入 P1.5，先提高题库生成和评估质量。

优点：

- 结果质量改善明显。

缺点：

- 如果基础运行、错误提示、状态恢复还不稳定，LLM 错误会让排查更困难。

不推荐跳过 P1。

## 5. 功能设计

### 5.1 启动入口

新增本地启动脚本：

- `scripts/dev.sh`

职责：

- 从仓库根目录启动。
- 检查 `backend` 和 `frontend` 目录是否存在。
- 提示需要分别启动的服务。
- 第一版可以不做进程管理，只提供明确命令和健康检查提示。

如果实现成本合适，可以支持：

- 启动 FastAPI 后端。
- 启动 Vite 前端。
- 打印访问地址。

验收：

- 用户不用翻文档，也能知道该运行哪些命令。
- 脚本失败时能输出清楚原因。

### 5.2 后端健康检查

新增前端 API：

- `frontend/src/shared/api/health.ts`

接口：

```ts
export interface HealthStatus {
  status: "ok";
}

export function getHealth(): Promise<HealthStatus>;
```

页面行为：

- App 启动时请求 `/api/health`。
- 成功显示“后端已连接”。
- 失败显示“后端未连接，请确认 FastAPI 服务已启动”。
- 健康检查失败不阻塞页面渲染，但禁用依赖后端的主要操作，或在操作时明确提示。

验收：

- 后端运行时显示 connected。
- 后端未运行时显示 disconnected 和处理建议。

### 5.3 Workspace 恢复

现有后端已有：

- `GET /api/settings/workspace`

P1 前端要在 App 启动时调用它：

- 如果返回 workspace，则恢复到 `AppShell` 状态。
- 页面展示当前 workspace 和 vault path。
- 如果返回 `null`，保持未初始化状态。
- 如果请求失败，展示后端连接错误。

限制：

- 当前后端 workspace 存在内存变量中。
- 后端重启后仍会丢失，需要用户重新初始化。
- P1 只恢复“当前后端进程中保存的 workspace”，不做磁盘持久化。

验收：

- 初始化 workspace 后刷新页面，前端仍能显示 workspace。
- 重启后端后页面明确提示需要重新初始化。

### 5.4 流程状态面板

在现有进度条基础上增加更明确的流程状态说明。

状态项：

- 后端连接。
- Workspace。
- 题库草稿。
- 复习报告。
- Vault 索引。

每项展示：

- 当前状态：未开始 / 进行中 / 已完成 / 失败。
- 下一步建议。

示例：

```text
后端连接：已连接
Workspace：已初始化
题库草稿：已生成
复习报告：待确认
Vault 索引：待重新扫描
```

验收：

- 用户不用猜下一步该点哪个按钮。
- 状态会随着操作变化。

### 5.5 错误提示统一

定义前端错误呈现规则：

- 所有页面错误统一以 `错误：...` 开头。
- 同时提供下一步建议。
- 后端错误要尽可能保留原始 message/detail。
- 网络失败要解释“可能是后端未启动”。

典型错误：

| 场景 | 页面提示 |
|---|---|
| 后端未启动 | 错误：后端未连接，请先启动 FastAPI 服务 |
| workspace path 为空 | 错误：请输入 Workspace Path |
| 上传时未选择文件 | 错误：请选择资料文件 |
| review 时回答为空 | 错误：请输入你的回答 |
| confirm 时没有报告 | 错误：请先生成报告 |
| rescan 失败 | 错误：重新扫描失败，确认 workspace 是否有效 |

验收：

- 用户能知道失败在哪一步。
- 用户能知道下一步该怎么做。

### 5.6 示例资料

新增示例资料：

- `examples/cache_question.txt`

内容围绕一个简单技术面试问题，适合跑完整闭环。

要求：

- 文件内容稳定。
- 不包含隐私信息。
- 文档中引用这个文件作为默认验证资料。

验收：

- 用户可以直接上传该文件跑完整流程。

### 5.7 自动验证补强

更新测试覆盖：

- 前端单测：
  - App 启动健康检查。
  - workspace 恢复。
  - 后端失败提示。
  - 流程状态变化。
  - 错误提示中的下一步建议。
- E2E：
  - 继续验证首屏流程入口。
  - 增加健康状态和流程状态面板断言。

限制：

- E2E 不必真实跑完整后端上传和 review。
- 后端 happy path 已由 pytest 覆盖。

验收：

- `pnpm --dir frontend test` 通过。
- `pnpm --dir frontend build` 通过。
- `cd backend && uv run pytest` 通过。
- `pnpm --dir frontend e2e` 通过。

### 5.8 验证文档输出

用户要求 P1 完成后，在 `docs` 下建立 verification 文件夹，并加入 gitignore。

要求：

- 新增目录：
  - `docs/verification/`
- `.gitignore` 添加：
  - `docs/verification/`
- P1 完成后生成：
  - `docs/verification/p1_mvp_quality_hardening.md`

该文件不提交，用作本地验收记录。

内容必须包括：

- 这次改动了哪些文件。
- 每个改动解决了什么问题。
- 如何人工验证。
- 每一步对应的代码位置。
- 运行哪些自动验证命令。
- 当前仍然粗糙的地方。

验收：

- `docs/verification/` 不出现在 git status 的未跟踪文件中。
- 本地存在 `docs/verification/p1_mvp_quality_hardening.md`。
- 文档能让用户理解每一步做了什么。

## 6. 数据与状态设计

### 6.1 AppShell 状态

P1 后 `AppShell` 至少持有：

```ts
interface AppHealthState {
  status: "checking" | "connected" | "disconnected";
  message: string;
}

interface FlowStatusState {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  reportConfirmed: boolean;
  indexedCount: number | null;
}
```

实现上不要求真的建立这两个 interface 文件，但 UI 状态应表达这些概念。

### 6.2 子组件事件

`KnowledgePage` 除了 `onDraftQuestionReady`，还需要能把 rescan 结果传给 AppShell：

```ts
onVaultRescanned: (indexedCount: number) => void;
```

`ReviewPage` 除了 `onReportMarkdownChange`，还需要能通知报告已确认：

```ts
onReportConfirmed: () => void;
```

### 6.3 Workspace 恢复

AppShell 初始化：

1. 请求 `/api/health`。
2. 如果 health 成功，再请求 `/api/settings/workspace`。
3. 如果 workspace 存在，设置当前 workspace。
4. 如果任一步失败，记录错误状态，但不 crash 页面。

## 7. 文案设计

关键文案保持中文。

必须保留现有测试依赖的文字：

- `Cyber Interview Agent`
- `复习闭环 MVP`
- `设置`
- `知识文档`
- `复习`
- `测试连接`
- `初始化工作区`
- `上传资料`
- `重新扫描 Vault`
- `发送回答`
- `请先初始化工作区`
- `请先上传资料生成题库草稿`

新增建议文案：

- `后端已连接`
- `后端未连接，请确认 FastAPI 服务已启动`
- `下一步：初始化工作区`
- `下一步：上传资料生成题库草稿`
- `下一步：输入回答并发送`
- `下一步：确认报告`
- `下一步：重新扫描 Vault`

## 8. 测试策略

### 8.1 前端单测

覆盖：

- health connected/disconnected。
- workspace restore success/null/failure。
- flow status panel。
- settings error advice。
- knowledge rescan 回传 indexed count。
- review confirm 回传 confirmed 状态。

### 8.2 后端测试

P1 不修改后端业务逻辑时，只需跑全量 pytest。

如果新增后端 helper 或脚本，不影响 API 合约。

### 8.3 E2E

继续保持轻量：

- 页面能打开。
- 主流程入口存在。
- health / flow status 可见。
- 前置条件提示可见。

不在 P1 E2E 中依赖真实文件上传和完整 review 后端流程。

## 9. 验收标准

P1 完成必须满足：

1. 用户手动验证时，页面能告诉用户当前状态和下一步。
2. 刷新页面后能恢复当前后端进程内的 workspace。
3. 后端未启动时页面有明确提示。
4. 示例资料可用于完整流程验证。
5. `docs/verification/` 已加入 `.gitignore`。
6. 本地生成 `docs/verification/p1_mvp_quality_hardening.md`。
7. 自动验证通过：
   - `pnpm --dir frontend test`
   - `pnpm --dir frontend build`
   - `cd backend && uv run pytest`
   - `pnpm --dir frontend e2e`

## 10. 当前不解决的问题

- 后端重启后 workspace 仍丢失。
- 题库生成仍是规则/占位逻辑。
- 复习评估仍是规则/占位逻辑。
- 没有真实 LLM。
- 没有会话历史。
- 没有正式题库审核流。

这些问题分别进入 P1.5、P2、P3、P4 后续阶段。
