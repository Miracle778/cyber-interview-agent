# Pre-R2 Experience Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persistent, content-first knowledge workspace, disclose human approval only when needed, and improve the review page hierarchy without adding R2 behavior.

**Architecture:** Store uploaded-source metadata in the existing per-workspace Runtime SQLite database and expose it through a workspace-scoped read API. Replace the knowledge card stream with a responsive resource navigator and a safe Markdown read/edit surface; retain the existing publication state machine and make its approval UI conditional. Keep review behavior unchanged while introducing explicit layout regions that can host R2 later.

**Tech Stack:** Python 3, FastAPI, SQLite/aiosqlite, React 19, TypeScript, TanStack Query, `react-markdown`, `remark-gfm`, Vitest, pytest, Playwright, CSS.

## Global Constraints

- Do not implement R2 multi-question selection, review modes, global mastery, or next-question behavior.
- Do not alter knowledge publication transitions, Workspace path policy, or Vault write boundaries.
- Do not implement context compression or token/context metering in this slice.
- Do not modify or commit `docs/my_idea.md`.
- Use targeted tests during Tasks 1–3; run one final backend regression, frontend regression, production build, browser acceptance, and document gate in Task 4.
- Keep one Agent on the slice end-to-end; do not create subagents.
- Use existing semantic colors and Lucide icons; preserve visible focus, 44px targets, reduced-motion support, and a 375px no-overflow layout.

---

## File Map

- `backend/app/db/migrations/runtime/005_knowledge_sources.sql`: persistent source metadata and workspace ordering index.
- `backend/app/knowledge/source_registry.py`: source file + metadata lifecycle and safe workspace-scoped listing.
- `backend/app/knowledge/sources.py`: retain filename/path validation and atomic byte writing primitives.
- `backend/app/schemas/drafts.py`: source and upload API resources.
- `backend/app/api/routes_knowledge.py`: upload orchestration and `GET /api/knowledge/sources`.
- `backend/tests/test_knowledge_routes.py`: persistence, isolation, original filename, path safety, and compensation tests.
- `frontend/src/features/knowledge/knowledgeTypes.ts`: `KnowledgeSource` resource type.
- `frontend/src/features/knowledge/knowledgeApi.ts`: source list query and enriched upload response.
- `frontend/src/features/knowledge/MarkdownView.tsx`: safe read-only Markdown renderer.
- `frontend/src/features/knowledge/MarkdownView.test.tsx`: Markdown semantics and raw-HTML safety.
- `frontend/src/features/knowledge/DraftReview.tsx`: controlled selected draft, read/edit modes, save/cancel/publish actions.
- `frontend/src/features/knowledge/KnowledgePage.tsx`: toolbar, grouped resource navigation, detail surface, and query coordination.
- `frontend/src/features/knowledge/KnowledgePage.test.tsx`: grouped resources and upload refresh.
- `frontend/src/features/knowledge/DraftReview.test.tsx`: read/edit behavior and unsaved-change protection.
- `frontend/src/features/agent/ActionCenter.tsx`: hide-empty behavior for non-diagnostic consumers.
- `frontend/src/features/agent/ActionCenter.test.tsx`: hidden, waiting, pending, and diagnostic states.
- `frontend/src/features/review/ReviewPage.tsx`: semantic review layout only.
- `frontend/src/features/review/ReviewPage.test.tsx`: regression assertions for unchanged behavior and layout regions.
- `frontend/src/app/layout/AppShell.tsx`: remove redundant review wrapping and use page-owned layout regions.
- `frontend/src/app/global.css`: responsive workspace grids, resource list, Markdown typography, review regions, focus, and reduced motion.
- `frontend/package.json`, `frontend/pnpm-lock.yaml`: safe Markdown rendering dependencies.
- `task_plan.md`, `findings.md`, `progress.md`: current stage, discovered decisions, and bounded handoff evidence.
- `docs/verification/pre-r2-experience-stabilization.md`: incremental evidence and final user guide.
- `docs/learning/pre-r2-experience-stabilization/`: seven-file ownership pack generated only after implementation stabilizes.

### Task 1: Persist and list uploaded source documents

**Files:**
- Create: `backend/app/db/migrations/runtime/005_knowledge_sources.sql`
- Create: `backend/app/knowledge/source_registry.py`
- Modify: `backend/app/knowledge/sources.py`
- Modify: `backend/app/schemas/drafts.py`
- Modify: `backend/app/api/routes_knowledge.py`
- Test: `backend/tests/test_knowledge_routes.py`

**Interfaces:**
- Produces: `KnowledgeSourceRecord` plus the `KnowledgeSourceService.create`, `list`, `attach_draft`, and `delete` methods defined below.
- Produces: `GET /api/knowledge/sources?workspaceId=<id> -> KnowledgeSourceResource[]`.
- Produces: `POST /api/knowledge/sources -> { source, draft, question }`.

- [ ] **Step 1: Add failing persistence and workspace-isolation route tests**

Add tests that upload `缓存资料.md`, restart the `TestClient`, then assert:

```python
listed = client.get(
    "/api/knowledge/sources", params={"workspaceId": workspace_id}
)
assert listed.status_code == 200
assert listed.json() == [{
    "id": body["source"]["id"],
    "workspaceId": workspace_id,
    "originalFilename": "缓存资料.md",
    "storedPath": body["source"]["storedPath"],
    "contentType": "text/markdown",
    "sizeBytes": len(content),
    "createdAt": body["source"]["createdAt"],
    "draftId": body["draft"]["id"],
}]
assert not listed.json()[0]["storedPath"].startswith("/")
```

Register a second workspace and assert its list is empty. Add a failure-injection test around draft creation and assert neither a database row nor source file remains after compensation.

- [ ] **Step 2: Run the route tests and verify RED**

Run: `cd backend && pytest -q tests/test_knowledge_routes.py -x --tb=short`

Expected: FAIL because GET is not defined and upload has no `source` resource.

- [ ] **Step 3: Add the Runtime migration and source record service**

Create `005_knowledge_sources.sql` with this schema:

```sql
CREATE TABLE knowledge_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    draft_id TEXT REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, stored_path)
);

CREATE INDEX idx_knowledge_sources_workspace_created
    ON knowledge_sources(workspace_id, created_at DESC, id DESC);
```

Implement the public record and methods with exact fields:

```python
@dataclass(frozen=True, slots=True)
class KnowledgeSourceRecord:
    id: str
    workspace_id: str
    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    draft_id: str | None
    created_at: str

```

Implement `KnowledgeSourceService.create` with keyword-only `original_filename: str`, `content_type: str`, and `content: bytes`, returning `KnowledgeSourceRecord`. Implement `attach_draft(source_id: str, *, draft_id: str) -> KnowledgeSourceRecord`, `list() -> tuple[KnowledgeSourceRecord, ...]`, and `delete(source_id: str) -> None`. `create` must validate the original filename, atomically write bytes under `review.sources`, and insert metadata in one guarded operation. On insert failure, unlink the new file. `delete` must resolve the stored relative path through `WorkspacePathPolicy`, delete only that source, and remove its row.

- [ ] **Step 4: Expose source resources and compensate failed upload orchestration**

Add camel-case Pydantic resources:

```python
class KnowledgeSourceResource(DraftModel):
    id: str
    workspace_id: str
    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    created_at: str
    draft_id: str | None

class UploadSourceResource(DraftModel):
    source: KnowledgeSourceResource
    draft: KnowledgeDraftResource
    question: ReviewQuestion
```

In `upload_source`, create the source first, build the draft from `workspace / source.stored_path`, attach the draft, and return all three resources. If draft creation or attachment fails, call `sources.delete(source.id)` before re-raising. Add:

```python
@router.get("/sources", response_model=list[KnowledgeSourceResource])
async def list_sources(
    workspace_id: str,
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> list[KnowledgeSourceResource]:
    workspace = workspaces.resolve_root(workspace_id)
    records = await KnowledgeSourceService(
        workspace, workspace_id=workspace_id
    ).list()
    return [KnowledgeSourceResource.model_validate(item) for item in records]
```

- [ ] **Step 5: Run targeted backend tests**

Run: `cd backend && pytest -q tests/test_knowledge_routes.py tests/test_knowledge_drafts.py -x --tb=short`

Expected: all selected tests PASS; no absolute workspace path is returned.

- [ ] **Step 6: Commit Task 1**

```bash
git add backend/app/db/migrations/runtime/005_knowledge_sources.sql backend/app/knowledge/source_registry.py backend/app/knowledge/sources.py backend/app/schemas/drafts.py backend/app/api/routes_knowledge.py backend/tests/test_knowledge_routes.py
git commit -m "feat(knowledge): persist uploaded source metadata"
```

### Task 2: Build the grouped knowledge workspace and Markdown read/edit flow

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Modify: `frontend/src/features/knowledge/knowledgeTypes.ts`
- Modify: `frontend/src/features/knowledge/knowledgeApi.ts`
- Create: `frontend/src/features/knowledge/MarkdownView.tsx`
- Create: `frontend/src/features/knowledge/MarkdownView.test.tsx`
- Modify: `frontend/src/features/knowledge/DraftReview.tsx`
- Modify: `frontend/src/features/knowledge/DraftReview.test.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.test.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Consumes: `KnowledgeSourceResource` and enriched `UploadSourceResource` from Task 1.
- Produces: `listSources(workspaceId): Promise<KnowledgeSource[]>`.
- Produces: `<MarkdownView markdown: string />` with raw HTML disabled.
- Produces: `<DraftReview workspaceId selectedId? onSelectedIdChange? onPublicationRequested? />`.

- [ ] **Step 1: Install the Markdown dependencies**

Run: `cd frontend && pnpm add react-markdown remark-gfm`

Expected: `package.json` and `pnpm-lock.yaml` include both direct dependencies.

- [ ] **Step 2: Add failing tests for grouped resources and safe Markdown reading**

Add a `MarkdownView` test:

```tsx
render(<MarkdownView markdown={'# 标题\n\n- 项目\n\n<script>alert(1)</script>'} />);
expect(screen.getByRole('heading', { name: '标题' })).toBeInTheDocument();
expect(screen.getByRole('list')).toBeInTheDocument();
expect(document.querySelector('script')).toBeNull();
```

Also force the renderer child to throw through a test-only failing component and assert the boundary shows the Markdown as plain text. Update `KnowledgePage.test.tsx` to mock `GET /api/knowledge/sources?workspaceId=w1` and drafts, then assert the two group headings, original filename, draft title, and selected detail. Add a rejected source-list request and assert the upload toolbar remains available with a `重试读取资料` action. Update `DraftReview.test.tsx` to assert Markdown is rendered initially, textarea is absent, clicking `编辑` reveals it, `取消编辑` restores server content, and save returns to read mode.

- [ ] **Step 3: Run the frontend tests and verify RED**

Run: `cd frontend && pnpm test -- src/features/knowledge/MarkdownView.test.tsx src/features/knowledge/KnowledgePage.test.tsx src/features/knowledge/DraftReview.test.tsx --reporter=dot`

Expected: FAIL because the renderer, source list, grouped workspace, and explicit edit mode do not exist.

- [ ] **Step 4: Add API types and safe Markdown rendering**

Define:

```ts
export interface KnowledgeSource {
  id: string;
  workspaceId: string;
  originalFilename: string;
  storedPath: string;
  contentType: string;
  sizeBytes: number;
  createdAt: string;
  draftId: string | null;
}

export function listSources(workspaceId: string): Promise<KnowledgeSource[]> {
  const query = new URLSearchParams({ workspaceId });
  return apiGet(`/api/knowledge/sources?${query.toString()}`);
}
```

Implement `MarkdownView` with `ReactMarkdown` and `remarkGfm`; do not add `rehype-raw`. Render links with `target="_blank"` and `rel="noreferrer noopener"` only for external URLs. Wrap output in `<article className="markdown-view">`. Add a focused React error boundary in the same file whose fallback is `<pre className="markdown-view markdown-view--fallback">{markdown}</pre>`; it must never use `dangerouslySetInnerHTML`.

- [ ] **Step 5: Convert DraftReview to controlled selection and explicit read/edit states**

Add optional selection props and local mode:

```ts
interface DraftReviewProps {
  workspaceId: string;
  selectedId?: string | null;
  onSelectedIdChange?: (id: string) => void;
  onPublicationRequested?: (runId: string) => void;
}
const [isEditing, setIsEditing] = useState(false);
const dirty = title !== selected?.title || markdown !== selected?.markdown;
```

Remove the component-owned draft list when it is rendered inside `KnowledgePage`. In read mode show `MarkdownView`, metadata, publication state, target path, and an `编辑` button only for editable statuses. In edit mode show inputs plus `保存草稿` and `取消编辑`; if `dirty`, call `globalThis.confirm("放弃未保存的修改？")` before cancelling or changing selection. Publishing remains available only under the existing status rules.

- [ ] **Step 6: Replace the knowledge card stream with a grouped workspace**

Use one TanStack query for sources and reuse the drafts query key. Keep state as a discriminated selection:

```ts
type ResourceSelection =
  | { kind: "source"; id: string }
  | { kind: "draft"; id: string }
  | null;
```

Render a `knowledge-toolbar` containing the labelled file input, upload button, rescan button, and last indexed count. Follow it with `knowledge-workspace`: a `<nav className="knowledge-resources" aria-label="知识库资源">` containing sections labelled by `source-group-title` and `draft-group-title`, then `<main className="knowledge-detail">` containing either source metadata, `DraftReview`, or the actionable empty state. If the source query fails, keep the toolbar and render the converted actionable error plus a button that calls `sourcesQuery.refetch()`.

On upload success invalidate `knowledge-sources` and `knowledge-drafts`, then select `{ kind: "draft", id: result.draft.id }`. Source detail displays original filename, MIME type, formatted size, created time, safe relative path, and a button to open its linked draft. Remove the duplicated in-memory question card and the misleading global “暂无文档” state.

- [ ] **Step 7: Add responsive and accessible workspace styling**

At desktop widths use `grid-template-columns: minmax(220px, 280px) minmax(0, 1fr)`; cap Markdown text measure at `75ch`. At widths below 768px switch to one column. Resource buttons use at least 44px min-height, visible `:focus-visible`, selected `aria-current`, 150–200ms color/border transitions, and no layout-changing transforms. Add `@media (prefers-reduced-motion: reduce)` to remove non-essential transitions.

- [ ] **Step 8: Run targeted frontend tests and typecheck**

Run: `cd frontend && pnpm test -- src/features/knowledge/MarkdownView.test.tsx src/features/knowledge/KnowledgePage.test.tsx src/features/knowledge/DraftReview.test.tsx --reporter=dot`

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: all selected tests PASS and TypeScript exits 0.

- [ ] **Step 9: Commit Task 2**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/features/knowledge frontend/src/app/global.css
git commit -m "feat(knowledge): add grouped markdown workspace"
```

### Task 3: Disclose approval on demand and improve review layout only

**Files:**
- Modify: `frontend/src/features/agent/ActionCenter.tsx`
- Modify: `frontend/src/features/agent/ActionCenter.test.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.test.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/review/ReviewPage.test.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Produces: `ActionCenter` returns `null` only when `showDiagnostic === false`, loading has completed, no filtered actions exist, no `watchRunId` exists, and there is no local error/message.
- Preserves: settings diagnostics, approval mutations, single-review run/session behavior, and review publication decisions.

- [ ] **Step 1: Add failing conditional-disclosure and layout regression tests**

Add tests for these exact states:

```tsx
const { container } = render(
  <ActionCenter workspaceId="w1" showDiagnostic={false} actionType="knowledge.publish" />,
  { wrapper },
);
await waitFor(() => expect(fetch).toHaveBeenCalled());
expect(container).toBeEmptyDOMElement();
```

Keep the card visible when `watchRunId` is set and assert “正在等待待确认动作…”. Force the watch to time out, assert a `重新检查` button appears, click it, and assert polling restarts. Keep the diagnostic variant visible with “暂无待确认动作”. In `ReviewPage.test.tsx`, assert `复习会话`, `当前练习`, and `复习结果` region labels while retaining all existing API and button assertions.

- [ ] **Step 2: Run affected tests and verify RED**

Run: `cd frontend && pnpm test -- src/features/agent/ActionCenter.test.tsx src/features/knowledge/KnowledgePage.test.tsx src/features/review/ReviewPage.test.tsx --reporter=dot`

Expected: FAIL because the empty non-diagnostic card and new layout regions are not implemented.

- [ ] **Step 3: Implement ActionCenter's explicit visibility predicate**

After hooks and mutations are declared, calculate:

```ts
const waitingForAction = Boolean(watchRunId) && actions.length === 0 && !localError;
const hidden = !showDiagnostic
  && !actionsQuery.isLoading
  && actions.length === 0
  && !waitingForAction
  && !localError;
if (hidden) return null;
```

Render “正在等待待确认动作…” for `waitingForAction`. Add `watchAttempt` state to the watch effect dependency list; a `重新检查` button clears `localError` and increments `watchAttempt`. Do not conditionally skip hooks. After approval/rejection, `onResolved` clears the parent run ID and the panel disappears immediately when the resolved action is removed. The diagnostic variant may continue to show its success message.

- [ ] **Step 4: Restructure review markup without changing behavior**

Move session selection into `<section className="review-session-bar" aria-label="复习会话">`, the question/messages/input into `<section className="review-practice" aria-label="当前练习">`, and the report into `<section className="review-results" aria-label="复习结果">`. Keep pending publication in its own conditional region. In `AppShell`, rename the existing outer `review-workspace` to `review-layout`, its main child to `review-layout__main`, and its `FlowSummary` aside to `review-layout__aside`. `ReviewPage` remains responsible only for the main-column regions; `AppShell` remains the sole owner of `FlowSummary` and its Runtime-derived props.

Do not add new controls, API requests, state transitions, or review modes.

- [ ] **Step 5: Add review and approval responsive styling**

At 1024px and above use a main column plus 300px sticky summary. Below 1024px place the summary after practice/results. Keep approval as the contextual right rail on wide knowledge layouts and as a normal block after detail on small screens. Verify focus order follows DOM order.

- [ ] **Step 6: Run targeted tests and typecheck**

Run: `cd frontend && pnpm test -- src/features/agent/ActionCenter.test.tsx src/features/knowledge/KnowledgePage.test.tsx src/features/review/ReviewPage.test.tsx src/app/App.test.tsx --reporter=dot`

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: all selected tests PASS and TypeScript exits 0.

- [ ] **Step 7: Run the minimal browser happy path before final documentation**

Start the isolated backend/frontend services, then verify: upload → both resource groups update → rendered Markdown → edit/save → request publish → approval appears → approve → approval disappears and published path remains. Record only factual evidence in `docs/verification/pre-r2-experience-stabilization.md`.

- [ ] **Step 8: Commit Task 3**

```bash
git add frontend/src/features/agent frontend/src/features/knowledge frontend/src/features/review frontend/src/app/layout/AppShell.tsx frontend/src/app/global.css docs/verification/pre-r2-experience-stabilization.md
git commit -m "feat(ui): disclose contextual actions on demand"
```

### Task 4: Final acceptance, stage documentation, and handoff

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `docs/verification/pre-r2-experience-stabilization.md`
- Create: `docs/learning/pre-r2-experience-stabilization/README.md`
- Create: `docs/learning/pre-r2-experience-stabilization/architecture.md`
- Create: `docs/learning/pre-r2-experience-stabilization/code-walkthrough.md`
- Create: `docs/learning/pre-r2-experience-stabilization/debugging.md`
- Create: `docs/learning/pre-r2-experience-stabilization/exercises.md`
- Create: `docs/learning/pre-r2-experience-stabilization/interview-questions.md`
- Create: `docs/learning/pre-r2-experience-stabilization/ownership-checklist.md`

**Interfaces:**
- Produces: final user guide evidence, seven-file learning pack, and a clean handoff to the separate R1.2 context-budget slice.

- [ ] **Step 1: Run the only final backend regression**

Run: `cd backend && pytest -q --tb=short`

Expected: all backend tests PASS; record the exact count from this command.

- [ ] **Step 2: Run the only final frontend regression and production build**

Run: `cd frontend && pnpm test -- --reporter=dot`

Run: `cd frontend && pnpm build`

Expected: all frontend tests PASS; TypeScript and Vite production build exit 0. Record exact counts/output summaries.

- [ ] **Step 3: Run one complete browser/restart acceptance pass**

Verify desktop 1440×1000 and mobile 375×812 for grouped resources, upload, rendered/read mode, edit/cancel/save, approval hidden/pending/resolved, refresh, backend restart recovery, keyboard focus, console errors, and horizontal overflow. Re-run only a failed affected scenario after a fix.

- [ ] **Step 4: Finalize verification and the learning pack once**

Reshape verification into the final user guide with prerequisites, startup paths, happy path, recovery steps, known maturity boundary, and exact automated/browser evidence. Generate the seven learning files from the repository templates. Compare both artifacts with the previous stage and remove copied claims that are not supported by this stage's commands.

- [ ] **Step 5: Run the documentation gate and manual evidence check**

Run:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/pre-r2-experience-stabilization.md \
  --learning docs/learning/pre-r2-experience-stabilization/ \
  --plan docs/superpowers/plans/2026-07-12-pre-r2-experience-stabilization.md
```

Expected: PASS. Manually confirm every test count comes from Steps 1–2 and browser claims come from Step 3.

- [ ] **Step 6: Update short state files and commit acceptance evidence**

Set the current task to complete in `task_plan.md`, record only durable architecture findings in `findings.md`, and add a handoff under 10 lines in `progress.md`. Name the next product task “R1.2 context compression and token/context usage foundation”; do not mark that debt complete.

```bash
git add task_plan.md findings.md progress.md docs/superpowers/plans/2026-07-12-pre-r2-experience-stabilization.md
git commit -m "docs: close pre-r2 experience stabilization"
```

- [ ] **Step 7: Final branch review**

Run: `git status --short`, `git diff main...HEAD --stat`, and `git log --oneline main..HEAD`.

Expected: no uncommitted product files, only intentional commits, and no `docs/my_idea.md` change. Report product evidence, maturity boundary, ownership status, next product task, and a non-blocking user exercise separately.
