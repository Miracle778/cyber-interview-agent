# Frontend MVP Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing React pages to the existing FastAPI endpoints so a user can complete the MVP loop in the browser: initialize workspace, test provider config, upload a source, review the generated question, confirm the report, and rescan the Vault.

**Architecture:** Keep the app as a single-page React/Vite UI. Store cross-section MVP state in `AppShell` with React state and pass it down to `SettingsPage`, `KnowledgePage`, and `ReviewPage`. Keep API details inside feature API modules and keep UI components focused on rendering and local form state.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, FastAPI JSON endpoints, FastAPI multipart form endpoints.

## Global Constraints

- Do not touch `docs/my_idea.md`; it is a local untracked idea note.
- Do not add a global store for this stage; use React local state in `AppShell`.
- Do not add real LLM provider calls.
- Do not add API key storage.
- Do not add multi-question review sessions.
- Do not add routing or a wizard.
- Keep frontend copy in Chinese and match the existing MVP language.
- The page order must be Settings, Knowledge, Review.
- Rescan must call the current backend contract: `POST /api/knowledge/rescan` with `workspacePath` in `FormData`.
- Upload must call the current backend contract: `POST /api/knowledge/sources` with `workspacePath` and `file` in `FormData`.
- Confirm report must call the current backend contract: `POST /api/review/reports/confirm` with JSON `{ workspacePath, reportMarkdown }`.

---

## File Structure

Modify these files:

- `frontend/src/app/layout/AppShell.tsx`
  - Owns cross-page MVP state: workspace, draft question, latest report markdown.
  - Renders pages in Settings -> Knowledge -> Review order.

- `frontend/src/features/settings/settingsApi.ts`
  - Already owns `ProviderConfig`, `WorkspaceConfig`, `getWorkspace`, and `initializeWorkspace`.
  - Add `testProviderConnection(provider: ProviderConfig): Promise<ProviderConfig>`.

- `frontend/src/features/settings/SettingsPage.tsx`
  - Turns the static settings form into a working form.
  - Calls `testProviderConnection` and `initializeWorkspace`.
  - Reports success/failure to the user.
  - Sends `WorkspaceConfig` up to `AppShell`.

- `frontend/src/features/knowledge/knowledgeApi.ts`
  - Keeps `uploadSource`.
  - Improves upload error handling through `ApiError`.
  - Adds `rescanVault(workspacePath: string): Promise<{ indexed: number }>`.

- `frontend/src/features/knowledge/KnowledgePage.tsx`
  - Requires a workspace before upload/rescan.
  - Lets user select a file and upload it.
  - Displays the generated question draft.
  - Sends the draft question up to `AppShell`.
  - Displays rescan result.

- `frontend/src/features/review/reviewApi.ts`
  - Replaces `Record<string, unknown>` return with typed review result.
  - Adds `confirmReport(payload): Promise<ConfirmReportResponse>`.

- `frontend/src/features/review/ReviewPage.tsx`
  - Requires a draft question before review.
  - Lets user submit one answer.
  - Displays evaluation and report markdown.
  - Lets user confirm the report when workspace and report markdown exist.

- Existing tests under `frontend/src/**/*.test.tsx` and `frontend/src/shared/api/client.test.ts`
  - Update tests to match interactive behavior.

No backend changes are planned for P0 because the required endpoints already exist.

---

### Task 1: AppShell Owns MVP Flow State

**Files:**
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Test: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes:
  - `WorkspaceConfig` from `frontend/src/features/settings/settingsApi.ts`
  - `ReviewQuestion` from `frontend/src/features/review/reviewTypes.ts`
- Produces:
  - Props for `SettingsPage`, `KnowledgePage`, and `ReviewPage`
  - Page order: Settings -> Knowledge -> Review

- [ ] **Step 1: Update the failing app test**

Replace `frontend/src/app/App.test.tsx` with:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the MVP shell in workflow order", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getByText("复习闭环 MVP")).toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["设置", "知识文档", "复习"]);
  });
});
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx
```

Expected: FAIL because the current order is Settings -> Review -> Knowledge.

- [ ] **Step 3: Implement AppShell state and page order**

Update `frontend/src/app/layout/AppShell.tsx`:

```tsx
import { useState } from "react";
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { ReviewPage } from "../../features/review/ReviewPage";
import type { ReviewQuestion } from "../../features/review/reviewTypes";
import { SettingsPage } from "../../features/settings/SettingsPage";
import type { WorkspaceConfig } from "../../features/settings/settingsApi";

export function AppShell() {
  const [workspace, setWorkspace] = useState<WorkspaceConfig | null>(null);
  const [draftQuestion, setDraftQuestion] = useState<ReviewQuestion | null>(null);
  const [latestReportMarkdown, setLatestReportMarkdown] = useState<string>("");

  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <p>复习闭环 MVP</p>
      <SettingsPage workspace={workspace} onWorkspaceReady={setWorkspace} />
      <KnowledgePage
        workspace={workspace}
        draftQuestion={draftQuestion}
        onDraftQuestionReady={setDraftQuestion}
      />
      <ReviewPage
        workspace={workspace}
        draftQuestion={draftQuestion}
        latestReportMarkdown={latestReportMarkdown}
        onReportMarkdownChange={setLatestReportMarkdown}
      />
    </main>
  );
}
```

- [ ] **Step 4: Temporarily update child component props with minimal no-op compatibility**

Before tests pass, update each child component export signature so TypeScript compiles. Detailed behavior comes in later tasks.

`SettingsPage.tsx` should accept:

```tsx
import type { WorkspaceConfig } from "./settingsApi";

interface SettingsPageProps {
  workspace: WorkspaceConfig | null;
  onWorkspaceReady: (workspace: WorkspaceConfig) => void;
}

export function SettingsPage({ workspace, onWorkspaceReady }: SettingsPageProps) {
  void workspace;
  void onWorkspaceReady;
  // existing JSX for now
}
```

`KnowledgePage.tsx` should accept:

```tsx
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";

interface KnowledgePageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  onDraftQuestionReady: (question: ReviewQuestion) => void;
}

export function KnowledgePage({ workspace, draftQuestion, onDraftQuestionReady }: KnowledgePageProps) {
  void workspace;
  void draftQuestion;
  void onDraftQuestionReady;
  // existing JSX for now
}
```

`ReviewPage.tsx` should accept:

```tsx
import type { WorkspaceConfig } from "../settings/settingsApi";
import type { ReviewQuestion } from "./reviewTypes";

interface ReviewPageProps {
  workspace: WorkspaceConfig | null;
  draftQuestion: ReviewQuestion | null;
  latestReportMarkdown: string;
  onReportMarkdownChange: (markdown: string) => void;
}

export function ReviewPage({
  workspace,
  draftQuestion,
  latestReportMarkdown,
  onReportMarkdownChange,
}: ReviewPageProps) {
  void workspace;
  void draftQuestion;
  void latestReportMarkdown;
  void onReportMarkdownChange;
  // existing JSX for now
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
pnpm --dir frontend test -- App.test.tsx
```

Expected: PASS.

---

### Task 2: Settings Page Calls Provider Test and Workspace Init APIs

**Files:**
- Modify: `frontend/src/features/settings/settingsApi.ts`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`

**Interfaces:**
- Consumes:
  - `apiPost<TRequest, TResponse>(path, payload)` from `frontend/src/shared/api/client.ts`
- Produces:
  - `testProviderConnection(provider: ProviderConfig): Promise<ProviderConfig>`
  - `SettingsPageProps` with `workspace` and `onWorkspaceReady`

- [ ] **Step 1: Update the failing tests**

Replace `frontend/src/features/settings/SettingsPage.test.tsx` with tests that mock `fetch`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "./settingsApi";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("tests provider connectivity", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "local-provider",
          name: "Local Provider",
          apiFormat: "openai-compatible",
          baseUrl: "https://api.example.com/v1",
          modelIds: ["model-a"],
          activeModelId: "model-a",
          connectivityStatus: "ok",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<SettingsPage workspace={null} onWorkspaceReady={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Provider 名称"), { target: { value: "Local Provider" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://api.example.com/v1" } });
    fireEvent.change(screen.getByLabelText("Model ID"), { target: { value: "model-a" } });
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));

    expect(await screen.findByText("Provider 连接状态：ok")).toBeInTheDocument();
  });

  it("initializes workspace and reports it to AppShell", async () => {
    const onWorkspaceReady = vi.fn();
    const workspace: WorkspaceConfig = {
      workspacePath: "/tmp/cyber-demo",
      vaultPath: "/tmp/cyber-demo/knowledge-vault",
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(workspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<SettingsPage workspace={null} onWorkspaceReady={onWorkspaceReady} />);

    fireEvent.change(screen.getByLabelText("Workspace Path"), { target: { value: "/tmp/cyber-demo" } });
    fireEvent.click(screen.getByRole("button", { name: "初始化工作区" }));

    await waitFor(() => expect(onWorkspaceReady).toHaveBeenCalledWith(workspace));
    expect(await screen.findByText("Vault：/tmp/cyber-demo/knowledge-vault")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pnpm --dir frontend test -- SettingsPage.test.tsx
```

Expected: FAIL because `testProviderConnection` and interactive behavior are not implemented.

- [ ] **Step 3: Add provider API function**

Add to `frontend/src/features/settings/settingsApi.ts`:

```ts
export function testProviderConnection(provider: ProviderConfig): Promise<ProviderConfig> {
  return apiPost<ProviderConfig, ProviderConfig>("/api/settings/providers/test", provider);
}
```

- [ ] **Step 4: Implement SettingsPage**

Implement controlled inputs, two independent async actions, and status messages. Use `type="button"` on both buttons so one action does not submit the whole form.

Required behavior:

- Default provider name: `OpenAI Compatible`
- Default base URL: `https://api.example.com/v1`
- Default model ID: `model-a`
- Provider request must use:
  - `id: "local-provider"`
  - `apiFormat: "openai-compatible"`
  - `modelIds: [modelId]`
  - `activeModelId: modelId`
  - `connectivityStatus: "unknown"`
- Workspace init button must trim the workspace path.
- If workspace path is empty, show `请输入 Workspace Path`.
- Show current workspace if `workspace` prop is not null.

- [ ] **Step 5: Run tests**

Run:

```bash
pnpm --dir frontend test -- SettingsPage.test.tsx
```

Expected: PASS.

---

### Task 3: Knowledge Page Uploads Source and Rescans Vault

**Files:**
- Modify: `frontend/src/features/knowledge/knowledgeApi.ts`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Test: `frontend/src/features/knowledge/KnowledgePage.test.tsx`

**Interfaces:**
- Consumes:
  - `WorkspaceConfig`
  - `ReviewQuestion`
- Produces:
  - `rescanVault(workspacePath: string): Promise<{ indexed: number }>`
  - `KnowledgePageProps` with `workspace`, `draftQuestion`, and `onDraftQuestionReady`

- [ ] **Step 1: Update the failing tests**

Replace `frontend/src/features/knowledge/KnowledgePage.test.tsx` with:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReviewQuestion } from "../review/reviewTypes";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { KnowledgePage } from "./KnowledgePage";

const workspace: WorkspaceConfig = {
  workspacePath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
};

const question: ReviewQuestion = {
  id: "q1",
  title: "缓存穿透",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "缓存穿透是请求不存在的数据导致缓存无法命中。",
  topics: ["缓存"],
  difficulty: "medium",
  keyPoints: ["缓存空值", "布隆过滤器"],
  followUps: [],
  mastery: "unknown",
};

describe("KnowledgePage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requires workspace before upload or rescan", () => {
    render(<KnowledgePage workspace={null} draftQuestion={null} onDraftQuestionReady={vi.fn()} />);

    expect(screen.getByText("请先初始化工作区")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新扫描 Vault" })).toBeDisabled();
  });

  it("uploads source and displays the generated draft question", async () => {
    const onDraftQuestionReady = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(question), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<KnowledgePage workspace={workspace} draftQuestion={null} onDraftQuestionReady={onDraftQuestionReady} />);

    const file = new File(["缓存穿透是什么？"], "cache.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("选择资料文件"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传资料" }));

    await waitFor(() => expect(onDraftQuestionReady).toHaveBeenCalledWith(question));
    expect(await screen.findByText("缓存穿透")).toBeInTheDocument();
    expect(screen.getByText("缓存穿透是什么？")).toBeInTheDocument();
    expect(screen.getByText("关键点：缓存空值、布隆过滤器")).toBeInTheDocument();
  });

  it("rescans the vault and displays indexed count", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ indexed: 3 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<KnowledgePage workspace={workspace} draftQuestion={question} onDraftQuestionReady={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "重新扫描 Vault" }));

    expect(await screen.findByText("索引文档数：3")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pnpm --dir frontend test -- KnowledgePage.test.tsx
```

Expected: FAIL because the page is still static.

- [ ] **Step 3: Update knowledge API**

Update `frontend/src/features/knowledge/knowledgeApi.ts`:

```ts
import { ApiError } from "../../shared/api/client";
import type { ReviewQuestion } from "../review/reviewTypes";

export interface RescanVaultResponse {
  indexed: number;
}

async function readError(response: Response, fallback: string): Promise<never> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("api_error", fallback);
  }
  if (typeof body === "object" && body !== null && "message" in body) {
    throw new ApiError("api_error", String((body as { message: unknown }).message));
  }
  if (typeof body === "object" && body !== null && "detail" in body) {
    throw new ApiError("api_error", String((body as { detail: unknown }).detail));
  }
  throw new ApiError("api_error", fallback);
}

export async function uploadSource(workspacePath: string, file: File): Promise<ReviewQuestion> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  form.set("file", file);
  const response = await fetch("/api/knowledge/sources", { method: "POST", body: form });
  if (!response.ok) await readError(response, "上传失败");
  return response.json() as Promise<ReviewQuestion>;
}

export async function rescanVault(workspacePath: string): Promise<RescanVaultResponse> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  const response = await fetch("/api/knowledge/rescan", { method: "POST", body: form });
  if (!response.ok) await readError(response, "重新扫描失败");
  return response.json() as Promise<RescanVaultResponse>;
}
```

- [ ] **Step 4: Implement KnowledgePage**

Required behavior:

- If `workspace` is null:
  - show `请先初始化工作区`
  - disable upload and rescan buttons
- File input label must be `选择资料文件`
- If upload is clicked without a selected file, show `请选择资料文件`
- On successful upload:
  - call `onDraftQuestionReady(question)`
  - display title, question text, reference answer, topics, difficulty, key points, mastery
- On successful rescan:
  - display `索引文档数：${indexed}`
- Show errors in plain text prefixed with `错误：`

- [ ] **Step 5: Run tests**

Run:

```bash
pnpm --dir frontend test -- KnowledgePage.test.tsx
```

Expected: PASS.

---

### Task 4: Review Page Runs Single-Round Review and Confirms Report

**Files:**
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Test: `frontend/src/features/review/ReviewPage.test.tsx`

**Interfaces:**
- Consumes:
  - `WorkspaceConfig`
  - `ReviewQuestion`
  - `runReview(payload)`
- Produces:
  - `ReviewRunResponse`
  - `confirmReport(payload)`
  - `ReviewPageProps`

- [ ] **Step 1: Update the failing tests**

Replace `frontend/src/features/review/ReviewPage.test.tsx` with:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceConfig } from "../settings/settingsApi";
import { ReviewPage } from "./ReviewPage";
import type { ReviewQuestion } from "./reviewTypes";

const workspace: WorkspaceConfig = {
  workspacePath: "/tmp/cyber-demo",
  vaultPath: "/tmp/cyber-demo/knowledge-vault",
};

const question: ReviewQuestion = {
  id: "q1",
  title: "缓存穿透",
  questionText: "缓存穿透是什么？",
  referenceAnswer: "缓存穿透是请求不存在的数据导致缓存无法命中。",
  topics: ["缓存"],
  difficulty: "medium",
  keyPoints: ["缓存空值", "布隆过滤器"],
  followUps: [],
  mastery: "unknown",
};

describe("ReviewPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requires a draft question before review", () => {
    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={null}
        latestReportMarkdown=""
        onReportMarkdownChange={vi.fn()}
      />,
    );

    expect(screen.getByText("请先上传资料生成题库草稿")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送回答" })).toBeDisabled();
  });

  it("runs review and displays evaluation report", async () => {
    const onReportMarkdownChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          selected_question: question,
          evaluation: {
            score: 72,
            missing_key_points: ["布隆过滤器"],
            evidence: ["提到了缓存空值"],
          },
          report_markdown: "# 单轮复习报告\n\n得分：72",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={question}
        latestReportMarkdown=""
        onReportMarkdownChange={onReportMarkdownChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("你的回答"), { target: { value: "可以缓存空值。" } });
    fireEvent.click(screen.getByRole("button", { name: "发送回答" }));

    expect(await screen.findByText("评分：72")).toBeInTheDocument();
    expect(screen.getByText("缺失点：布隆过滤器")).toBeInTheDocument();
    expect(screen.getByText("证据：提到了缓存空值")).toBeInTheDocument();
    await waitFor(() => expect(onReportMarkdownChange).toHaveBeenCalledWith("# 单轮复习报告\n\n得分：72"));
  });

  it("confirms report and displays written paths", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          reportPath: "/tmp/cyber-demo/knowledge-vault/20_review_sessions/session.md",
          masteryPath: "/tmp/cyber-demo/knowledge-vault/30_mastery/global_mastery_review_pending.md",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <ReviewPage
        workspace={workspace}
        draftQuestion={question}
        latestReportMarkdown="# 单轮复习报告"
        onReportMarkdownChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "确认报告" }));

    expect(await screen.findByText("报告：/tmp/cyber-demo/knowledge-vault/20_review_sessions/session.md")).toBeInTheDocument();
    expect(screen.getByText("掌握度：/tmp/cyber-demo/knowledge-vault/30_mastery/global_mastery_review_pending.md")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pnpm --dir frontend test -- ReviewPage.test.tsx
```

Expected: FAIL because ReviewPage is still static.

- [ ] **Step 3: Type the review API**

Update `frontend/src/features/review/reviewApi.ts` to include:

```ts
export interface ReviewRunResponse {
  selected_question: ReviewQuestion;
  evaluation: {
    score: number;
    missing_key_points: string[];
    evidence: string[];
  };
  report_markdown: string;
}

export interface ConfirmReportRequest {
  workspacePath: string;
  reportMarkdown: string;
}

export interface ConfirmReportResponse {
  reportPath: string;
  masteryPath: string;
}

export function runReview(payload: ReviewRunRequest): Promise<ReviewRunResponse> {
  return apiPost<ReviewRunRequest, ReviewRunResponse>("/api/review/run", payload);
}

export function confirmReport(payload: ConfirmReportRequest): Promise<ConfirmReportResponse> {
  return apiPost<ConfirmReportRequest, ConfirmReportResponse>("/api/review/reports/confirm", payload);
}
```

- [ ] **Step 4: Implement ReviewPage**

Required behavior:

- If `draftQuestion` is null:
  - show `请先上传资料生成题库草稿`
  - disable send button
- Show the current question title and question text when present.
- Textarea label must be `你的回答`.
- If send is clicked with empty answer, show `请输入你的回答`.
- `runReview` payload must be:

```ts
{
  questions: [draftQuestion],
  settings: {
    selectedTopics: [],
    questionCount: 1,
    mode: "weak-point",
  },
  userAnswer: answer,
}
```

- On success:
  - display `评分：${score}`
  - display `缺失点：${items.join("、") || "无"}`
  - display `证据：${items.join("、") || "无"}`
  - call `onReportMarkdownChange(response.report_markdown)`
  - show report markdown in a `<pre>`
- Show `确认报告` only when `workspace` and report markdown exist.
- Confirm report payload must be `{ workspacePath: workspace.workspacePath, reportMarkdown }`.
- On confirm success:
  - display `报告：${reportPath}`
  - display `掌握度：${masteryPath}`
- Show errors in plain text prefixed with `错误：`

- [ ] **Step 5: Run tests**

Run:

```bash
pnpm --dir frontend test -- ReviewPage.test.tsx
```

Expected: PASS.

---

### Task 5: End-to-End Browser MVP Smoke Test and Docs Update

**Files:**
- Modify: `tests/e2e/mvp-smoke.spec.ts`
- Modify: `docs/mvp_verification_guide.md`

**Interfaces:**
- Consumes:
  - Completed browser flow from Tasks 1-4
- Produces:
  - A smoke test that proves the UI exposes the new flow
  - Manual verification docs that explain what changed and how to verify it

- [ ] **Step 1: Update E2E smoke test**

Extend `tests/e2e/mvp-smoke.spec.ts` so it asserts:

- The H2 order is 设置, 知识文档, 复习.
- The page has buttons `测试连接`, `初始化工作区`, `上传资料`, `重新扫描 Vault`, `发送回答`.
- Before workspace init, knowledge page shows `请先初始化工作区`.
- Before upload, review page shows `请先上传资料生成题库草稿`.

- [ ] **Step 2: Run E2E test**

Run:

```bash
pnpm --dir frontend e2e
```

Expected: PASS.

- [ ] **Step 3: Update manual verification guide**

Update `docs/mvp_verification_guide.md`:

- Keep the honest warning that the MVP is still rough.
- Add a new section `浏览器验证 MVP 闭环`.
- Explain how to start backend and frontend.
- Explain browser steps:
  1. Open `http://127.0.0.1:5173`.
  2. Fill Workspace Path with a temporary path.
  3. Click `初始化工作区`.
  4. Fill Provider fields and click `测试连接`.
  5. Select a small `.txt` file and click `上传资料`.
  6. Confirm the draft question is visible.
  7. Type an answer and click `发送回答`.
  8. Confirm score, missing points, evidence, and report markdown are visible.
  9. Click `确认报告`.
  10. Confirm report and mastery paths are visible.
  11. Click `重新扫描 Vault`.
- Explain what each step proves in code terms:
  - Settings page proves `settingsApi.ts` and settings endpoints.
  - Knowledge page proves multipart upload, draft question generation, and rescan.
  - Review page proves LangGraph run and report confirmation.

- [ ] **Step 4: Run full frontend verification**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend build
```

Expected: PASS.

- [ ] **Step 5: Run backend verification**

Run:

```bash
cd backend && uv run pytest
```

Expected: PASS.

---

## Self-Review

Spec coverage:

- Workspace init is covered by Task 2.
- Provider test is covered by Task 2.
- Source upload and draft question display are covered by Task 3.
- Vault rescan is covered by Task 3.
- Single-question review is covered by Task 4.
- Report confirmation is covered by Task 4.
- Manual browser verification is covered by Task 5.

Placeholder scan:

- No placeholder markers or unspecified implementation steps are intentionally left in this plan.

Type consistency:

- `WorkspaceConfig` remains imported from `settingsApi.ts`.
- `ReviewQuestion` remains imported from `reviewTypes.ts`.
- `ReviewRunResponse` uses backend snake_case keys because `/api/review/run` currently returns graph state keys directly.
- Confirm report response uses backend camelCase keys already defined in `routes_review.py`.
