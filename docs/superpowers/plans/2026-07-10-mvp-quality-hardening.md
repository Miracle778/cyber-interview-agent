# P1 MVP Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the P0 browser loop from “can run once” into a repeatable MVP that shows backend health, restores workspace state, explains workflow progress, gives actionable errors, includes sample input, and produces a local verification guide.

**Architecture:** Keep the existing single-page React/Vite structure. Add small shared frontend helpers for health and error advice, keep cross-step flow state in `AppShell`, and pass explicit callbacks to feature pages. Do not change backend business behavior unless a test proves a tiny compatibility fix is required.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, Playwright, FastAPI, pytest, shell script for local startup guidance.

## Global Constraints

- Do not implement real LLM calls in P1; real LLM is P1.5.
- Do not store API keys.
- Do not add multi-question review sessions.
- Do not add routing, a global store, or a wizard.
- Preserve the existing page order: Settings, Knowledge, Review.
- Preserve existing user-facing Chinese labels used by tests.
- `docs/my_idea.md` must not be modified, staged, or committed.
- `docs/verification/` must be added to `.gitignore`.
- Generated verification files under `docs/verification/` are local artifacts and must not be committed.
- Non-`docs/superpowers/` planning documents are local unless the user explicitly changes the rule.

---

## File Structure

Planned changes:

- Create: `frontend/src/shared/api/health.ts`
  - Owns `/api/health` typing and request.
- Create: `frontend/src/shared/api/errorAdvice.ts`
  - Converts caught errors into consistent Chinese user advice.
- Modify: `frontend/src/app/layout/AppShell.tsx`
  - Loads health and workspace on startup.
  - Owns workflow state: health, workspace, draft question, report markdown, report confirmation, indexed count.
  - Renders the flow status panel.
- Modify: `frontend/src/app/App.test.tsx`
  - Verifies health/workspace restoration states.
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
  - Reports rescan count to `AppShell`.
  - Uses shared error advice.
- Modify: `frontend/src/features/knowledge/KnowledgePage.test.tsx`
  - Verifies rescan callback and actionable error text.
- Modify: `frontend/src/features/review/ReviewPage.tsx`
  - Reports confirmation to `AppShell`.
  - Uses shared error advice.
- Modify: `frontend/src/features/review/ReviewPage.test.tsx`
  - Verifies report confirmation callback and actionable error text.
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
  - Uses shared error advice.
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`
  - Verifies workspace empty path and provider failure advice.
- Create: `examples/cache_question.txt`
  - Stable sample file for manual verification.
- Create: `scripts/dev.sh`
  - Local startup guide or helper script.
- Modify: `tests/e2e/mvp-smoke.spec.ts`
  - Verifies health/flow status panel and existing entry points.
- Modify: `.gitignore`
  - Adds `docs/verification/`.
- Create locally after implementation: `docs/verification/p1_mvp_quality_hardening.md`
  - Must explain changed files, manual verification, code map, and remaining rough edges.

---

### Task 1: Health Check and Workspace Restore

**Files:**
- Create: `frontend/src/shared/api/health.ts`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes:
  - `getWorkspace(): Promise<WorkspaceConfig | null>` from `frontend/src/features/settings/settingsApi.ts`
- Produces:
  - `getHealth(): Promise<{ status: "ok" }>`
  - App-level health state: `checking | connected | disconnected`

- [ ] **Step 1: Add failing tests**

Add tests in `frontend/src/app/App.test.tsx` that mock `fetch`:

```tsx
it("shows backend connected and restores workspace", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ workspacePath: "/tmp/cyber-demo", vaultPath: "/tmp/cyber-demo/knowledge-vault" }), { status: 200, headers: { "Content-Type": "application/json" } }));

  render(<App />);

  expect(await screen.findByText("后端已连接")).toBeInTheDocument();
  expect(await screen.findByText("Workspace：/tmp/cyber-demo")).toBeInTheDocument();
});

it("shows backend disconnected advice when health fails", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

  render(<App />);

  expect(await screen.findByText("后端未连接，请确认 FastAPI 服务已启动")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run failing test**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx
```

Expected: tests fail because health restore is not implemented.

- [ ] **Step 3: Implement health API**

Create `frontend/src/shared/api/health.ts`:

```ts
import { apiGet } from "./client";

export interface HealthStatus {
  status: "ok";
}

export function getHealth(): Promise<HealthStatus> {
  return apiGet<HealthStatus>("/api/health");
}
```

- [ ] **Step 4: Implement AppShell startup restore**

Update `frontend/src/app/layout/AppShell.tsx`:

- Import `useEffect`.
- Import `getHealth`.
- Import and call `getWorkspace`.
- Add health state:

```ts
type HealthState = {
  status: "checking" | "connected" | "disconnected";
  message: string;
};
```

- On mount:
  - set checking.
  - call `getHealth()`.
  - on success, set connected and call `getWorkspace()`.
  - if workspace returned, call `setWorkspace`.
  - on failure, set disconnected with message `后端未连接，请确认 FastAPI 服务已启动`.

- Render a visible status text:
  - connected: `后端已连接`
  - disconnected: `后端未连接，请确认 FastAPI 服务已启动`
  - checking: `正在检查后端连接`

- [ ] **Step 5: Run verification**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx
```

Expected: PASS.

---

### Task 2: Workflow Status Panel and Cross-Step Callbacks

**Files:**
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.test.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/review/ReviewPage.test.tsx`

**Interfaces:**
- Consumes:
  - `ReviewQuestion`
  - `WorkspaceConfig`
- Produces:
  - `KnowledgePage` prop `onVaultRescanned(indexedCount: number): void`
  - `ReviewPage` prop `onReportConfirmed(): void`
  - App flow status panel text

- [ ] **Step 1: Add failing tests**

In `KnowledgePage.test.tsx`, add an assertion that rescan calls:

```tsx
const onVaultRescanned = vi.fn();
render(<KnowledgePage workspace={workspace} draftQuestion={question} onDraftQuestionReady={vi.fn()} onVaultRescanned={onVaultRescanned} />);
fireEvent.click(screen.getByRole("button", { name: "重新扫描 Vault" }));
await waitFor(() => expect(onVaultRescanned).toHaveBeenCalledWith(3));
```

In `ReviewPage.test.tsx`, add:

```tsx
const onReportConfirmed = vi.fn();
render(<ReviewPage workspace={workspace} draftQuestion={question} latestReportMarkdown="# 单轮复习报告" onReportMarkdownChange={vi.fn()} onReportConfirmed={onReportConfirmed} />);
fireEvent.click(screen.getByRole("button", { name: "确认报告" }));
await waitFor(() => expect(onReportConfirmed).toHaveBeenCalled());
```

In `App.test.tsx`, add status panel assertions:

```tsx
expect(await screen.findByText("后端连接：已连接")).toBeInTheDocument();
expect(screen.getByText("Workspace：待初始化")).toBeInTheDocument();
expect(screen.getByText("题库草稿：待生成")).toBeInTheDocument();
expect(screen.getByText("复习报告：待生成")).toBeInTheDocument();
expect(screen.getByText("Vault 索引：待扫描")).toBeInTheDocument();
expect(screen.getByText("下一步：初始化工作区")).toBeInTheDocument();
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx KnowledgePage.test.tsx ReviewPage.test.tsx
```

Expected: tests fail because callbacks/status panel are missing.

- [ ] **Step 3: Implement callbacks**

Update `KnowledgePageProps`:

```ts
onVaultRescanned: (indexedCount: number) => void;
```

After successful `rescanVault`, call:

```ts
onVaultRescanned(result.indexed);
```

Update `ReviewPageProps`:

```ts
onReportConfirmed: () => void;
```

After successful `confirmReport`, call:

```ts
onReportConfirmed();
```

- [ ] **Step 4: Implement flow status panel**

In `AppShell`, add:

```ts
const [reportConfirmed, setReportConfirmed] = useState(false);
const [indexedCount, setIndexedCount] = useState<number | null>(null);
```

Pass callbacks:

```tsx
<KnowledgePage ... onVaultRescanned={setIndexedCount} />
<ReviewPage ... onReportConfirmed={() => setReportConfirmed(true)} />
```

Render a panel with exact text:

```text
后端连接：已连接
Workspace：待初始化
题库草稿：待生成
复习报告：待生成
Vault 索引：待扫描
下一步：初始化工作区
```

Use derived text when state changes:

- workspace exists: `Workspace：已初始化`
- draft exists: `题库草稿：已生成`
- report markdown exists but not confirmed: `复习报告：待确认`
- confirmed: `复习报告：已确认`
- indexed count exists: `Vault 索引：已扫描 ${indexedCount} 个文档`

- [ ] **Step 5: Run verification**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx KnowledgePage.test.tsx ReviewPage.test.tsx
```

Expected: PASS.

---

### Task 3: Actionable Error Advice

**Files:**
- Create: `frontend/src/shared/api/errorAdvice.ts`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify tests for all three feature pages.

**Interfaces:**
- Produces:
  - `toActionableError(caught: unknown, fallback: string): string`

- [ ] **Step 1: Add failing tests**

Add tests verifying exact advice text:

Settings:

```tsx
fireEvent.click(screen.getByRole("button", { name: "初始化工作区" }));
expect(screen.getByText("错误：请输入 Workspace Path")).toBeInTheDocument();
expect(screen.getByText("下一步：填写本地 workspace 路径")).toBeInTheDocument();
```

Knowledge:

```tsx
fireEvent.click(screen.getByRole("button", { name: "上传资料" }));
expect(screen.getByText("错误：请选择资料文件")).toBeInTheDocument();
expect(screen.getByText("下一步：选择一份 txt、Markdown 或 PDF 资料")).toBeInTheDocument();
```

Review:

```tsx
fireEvent.click(screen.getByRole("button", { name: "发送回答" }));
expect(screen.getByText("错误：请输入你的回答")).toBeInTheDocument();
expect(screen.getByText("下一步：根据当前题目输入一段回答")).toBeInTheDocument();
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
pnpm --dir frontend test -- SettingsPage.test.tsx KnowledgePage.test.tsx ReviewPage.test.tsx
```

Expected: tests fail because next-step advice is missing.

- [ ] **Step 3: Implement error advice helper**

Create `frontend/src/shared/api/errorAdvice.ts`:

```ts
export interface ActionableError {
  message: string;
  advice: string;
}

export function toActionableError(caught: unknown, fallback: string): ActionableError {
  const message = caught instanceof Error ? caught.message : fallback;
  if (message.includes("Workspace Path")) return { message, advice: "下一步：填写本地 workspace 路径" };
  if (message.includes("请选择资料文件")) return { message, advice: "下一步：选择一份 txt、Markdown 或 PDF 资料" };
  if (message.includes("请输入你的回答")) return { message, advice: "下一步：根据当前题目输入一段回答" };
  if (message.includes("Failed to fetch")) return { message: "后端未连接，请确认 FastAPI 服务已启动", advice: "下一步：运行 cd backend && uv run fastapi dev app/main.py" };
  if (message.includes("重新扫描")) return { message, advice: "下一步：确认 workspace 有效后重新扫描" };
  if (message.includes("确认报告")) return { message, advice: "下一步：先发送回答生成报告" };
  return { message, advice: "下一步：检查当前步骤输入后重试" };
}
```

- [ ] **Step 4: Use helper in feature pages**

Replace string-only error state with:

```ts
const [error, setError] = useState<ActionableError | null>(null);
```

Render:

```tsx
{error ? (
  <div className="error-banner" role="alert" aria-live="polite">
    <AlertCircle size={16} aria-hidden="true" />
    <span>错误：{error.message}</span>
    <span>{error.advice}</span>
  </div>
) : null}
```

For local validation errors, set the exact message through helper:

```ts
setError(toActionableError(new Error("请输入 Workspace Path"), "初始化工作区失败"));
```

- [ ] **Step 5: Run verification**

Run:

```bash
pnpm --dir frontend test -- SettingsPage.test.tsx KnowledgePage.test.tsx ReviewPage.test.tsx
```

Expected: PASS.

---

### Task 4: Sample Input and Local Startup Guide

**Files:**
- Create: `examples/cache_question.txt`
- Create: `scripts/dev.sh`
- Modify: `docs/superpowers/specs/2026-07-10-mvp-quality-hardening-design.md` only if implementation reveals a small correction.

**Interfaces:**
- Produces:
  - stable sample source file
  - local startup helper script

- [ ] **Step 1: Create example source**

Create `examples/cache_question.txt`:

```text
缓存穿透是什么？
用户请求不存在的数据时，缓存无法命中，请求会持续打到数据库。常见防护是缓存空值或使用布隆过滤器。
```

- [ ] **Step 2: Create startup guide script**

Create `scripts/dev.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Cyber Interview Agent local development"
echo ""
echo "1. Start backend:"
echo "   cd \"$ROOT_DIR/backend\" && uv run fastapi dev app/main.py"
echo ""
echo "2. Start frontend in another terminal:"
echo "   pnpm --dir \"$ROOT_DIR/frontend\" dev"
echo ""
echo "3. Open:"
echo "   http://127.0.0.1:5173"
echo ""
echo "4. Sample file:"
echo "   $ROOT_DIR/examples/cache_question.txt"
```

- [ ] **Step 3: Make script executable**

Run:

```bash
chmod +x scripts/dev.sh
```

- [ ] **Step 4: Verify script output**

Run:

```bash
scripts/dev.sh
```

Expected: output shows backend command, frontend command, app URL, and sample file path.

---

### Task 5: Verification Folder, E2E, and Final Verification Document

**Files:**
- Modify: `.gitignore`
- Modify: `tests/e2e/mvp-smoke.spec.ts`
- Create local ignored artifact: `docs/verification/p1_mvp_quality_hardening.md`

**Interfaces:**
- Produces:
  - ignored local verification folder
  - P1 manual verification document

- [ ] **Step 1: Ignore verification folder**

Add to `.gitignore`:

```gitignore
docs/verification/
```

- [ ] **Step 2: Update E2E smoke test**

Update `tests/e2e/mvp-smoke.spec.ts` to assert:

```ts
await expect(page.getByText("正在检查后端连接").or(page.getByText("后端已连接")).or(page.getByText("后端未连接，请确认 FastAPI 服务已启动"))).toBeVisible();
await expect(page.getByText("Workspace：待初始化")).toBeVisible();
await expect(page.getByText("题库草稿：待生成")).toBeVisible();
await expect(page.getByText("复习报告：待生成")).toBeVisible();
await expect(page.getByText("Vault 索引：待扫描")).toBeVisible();
```

Keep existing assertions for:

- `Cyber Interview Agent`
- `设置`, `知识文档`, `复习`
- buttons: `测试连接`, `初始化工作区`, `上传资料`, `重新扫描 Vault`, `发送回答`
- precondition text: `请先初始化工作区`, `请先上传资料生成题库草稿`

- [ ] **Step 3: Create verification artifact**

Create `docs/verification/p1_mvp_quality_hardening.md` with these sections:

```markdown
# P1 MVP 质量补强验证说明

## 这次改了什么

## 每一步对应的代码

## 人工验证步骤

## 自动验证命令

## 仍然粗糙的地方
```

The document must mention:

- health check and backend status.
- workspace refresh restore.
- workflow status panel.
- actionable errors.
- sample file path `examples/cache_question.txt`.
- startup helper `scripts/dev.sh`.
- exact manual browser steps.

- [ ] **Step 4: Run full verification**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend && uv run pytest
pnpm --dir frontend e2e
```

Expected:

- frontend tests pass.
- frontend build succeeds.
- backend tests pass.
- Playwright smoke test passes.

- [ ] **Step 5: Verify ignored artifact behavior**

Run:

```bash
git status --short
```

Expected:

- `docs/verification/p1_mvp_quality_hardening.md` does not appear.
- `docs/my_idea.md` does not appear.

---

## Self-Review

Spec coverage:

- Startup guide is covered by Task 4.
- Backend health is covered by Task 1.
- Workspace restore is covered by Task 1.
- Flow status panel is covered by Task 2.
- Error advice is covered by Task 3.
- Sample data is covered by Task 4.
- Automated verification and ignored local verification docs are covered by Task 5.

Type consistency:

- `getHealth` returns `{ status: "ok" }`.
- `onVaultRescanned` accepts `number`.
- `onReportConfirmed` takes no arguments.
- `toActionableError` returns `{ message, advice }`.

Execution note:

- Claude execution should use `claude -p --model opus` with sandbox escalation, because sandboxed Claude calls hang in this environment.
- Claude must implement one task at a time.
- Codex must review diff and run the task verification after every Claude task.
