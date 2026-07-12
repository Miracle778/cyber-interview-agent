# Product Layout Redesign Implementation Plan

**Goal:** Replace the single stacked MVP page with routed, responsive product navigation while preserving every existing Settings, Knowledge, and Review workflow.

**Architecture:** React Router owns three real routes inside one stateful `AppShell`. A shared navigation definition renders as a persistent desktop sidebar and an accessible mobile drawer; route pages consume the existing top-level Workspace, question, report, and index state through explicit props. Page-level layout classes prepare Review for the future session/conversation/context workspace without implementing R1.2 behavior.

**Tech Stack:** React 19, TypeScript 5.7, React Router 7, TanStack Query 5, Lucide React, CSS, Vitest, Testing Library, Playwright.

## Global Constraints

- Work on branch `codex/product-layout-redesign` in the current repository; do not create a worktree.
- Only `/review`, `/knowledge`, and `/settings` are visible navigation destinations.
- `/` and unknown paths redirect to `/review`.
- Do not add backend APIs or future-feature placeholder pages.
- Preserve Workspace restore and the cross-route Workspace, draft question, report, and index state.
- Desktop navigation is persistent at widths greater than or equal to 1024px; smaller widths use a modal drawer.
- All navigation and icon controls have visible focus states and at least 44px interaction height.
- Use Lucide icons and semantic color tokens; do not use emoji or decorative gradients.
- Verify at 375, 768, 1024, and 1440px with no horizontal overflow.

---

### Task 1: Routed Application State Container

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Create: `frontend/src/app/layout/AppShell.test.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Produces: `AppShell` rendering route-aware page content inside `BrowserRouter`.
- Produces: paths `/review`, `/knowledge`, `/settings`, with `/` and `*` redirects to `/review`.
- Preserves: existing `WorkspaceConfig | null`, `ReviewQuestion | null`, report Markdown, report confirmation, and index count state.

- [ ] **Step 1: Write failing route tests**

Add tests that set `window.history` before rendering and assert only the selected page heading exists:

```tsx
it.each([
  ["/review", "复习"],
  ["/knowledge", "知识库"],
  ["/settings", "设置"],
])("renders %s as an independent page", async (path, heading) => {
  window.history.replaceState({}, "", path);
  mockDisconnectedBackend();
  render(<App />);
  expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { level: 1, name: "Cyber Interview Agent" })).not.toBeInTheDocument();
});

it.each(["/", "/unknown"])("redirects %s to review", async (path) => {
  window.history.replaceState({}, "", path);
  mockDisconnectedBackend();
  render(<App />);
  expect(await screen.findByRole("heading", { level: 1, name: "复习" })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/review");
});
```

- [ ] **Step 2: Run the route tests and verify RED**

Run: `pnpm --dir frontend test -- src/app/App.test.tsx`

Expected: FAIL because the application has no route-specific page heading and still renders all three sections together.

- [ ] **Step 3: Move BrowserRouter to App and declare routes in AppShell**

Wrap `AppShell` with `BrowserRouter` in `App.tsx`. Keep health restoration and shared workflow state in `AppShell`, but replace simultaneous page rendering with `Routes`, `Route`, and `Navigate`. Pass existing props unchanged to each feature page. Add a `pageTitle` prop to feature pages in Task 3 rather than duplicating headings here.

- [ ] **Step 4: Run route tests and full frontend tests**

Run: `pnpm --dir frontend test -- src/app/App.test.tsx`

Expected: PASS for direct paths and redirects.

Run: `pnpm --dir frontend test`

Expected: existing component tests may fail only where old global heading/order assertions must be replaced by routed assertions; no business interaction test may regress.

- [ ] **Step 5: Commit the routed state container**

```bash
git add frontend/src/app/App.tsx frontend/src/app/App.test.tsx frontend/src/app/layout/AppShell.tsx frontend/src/app/layout/AppShell.test.tsx
git commit -m "feat(ui): route product workspaces"
```

---

### Task 2: Shared Desktop and Mobile Navigation

**Files:**
- Create: `frontend/src/app/navigation/navigationItems.ts`
- Create: `frontend/src/app/navigation/PrimaryNavigation.tsx`
- Create: `frontend/src/app/navigation/PrimaryNavigation.test.tsx`
- Create: `frontend/src/app/navigation/MobileNavigation.tsx`
- Create: `frontend/src/app/navigation/MobileNavigation.test.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`

**Interfaces:**
- Produces: `NAVIGATION_GROUPS`, containing only Review, Knowledge, and Settings destinations.
- Produces: `PrimaryNavigation({ onNavigate? })` using `NavLink` and `aria-current`.
- Produces: `MobileNavigation()` with menu button, modal drawer, Escape dismissal, route-change dismissal, and focus return.
- Consumes: current React Router location.

- [ ] **Step 1: Write failing navigation tests**

Cover shared items, active state, drawer controls, and keyboard dismissal:

```tsx
it("marks the current destination and exposes only implemented pages", () => {
  renderNavigationAt("/knowledge");
  expect(screen.getByRole("link", { name: "知识库" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("link", { name: "复习" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "设置" })).toBeInTheDocument();
  expect(screen.queryByText("模拟面试")).not.toBeInTheDocument();
});

it("opens and closes the mobile drawer with Escape", async () => {
  const user = userEvent.setup();
  renderMobileNavigationAt("/review");
  const trigger = screen.getByRole("button", { name: "打开导航" });
  await user.click(trigger);
  expect(screen.getByRole("dialog", { name: "主导航" })).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "主导航" })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});
```

- [ ] **Step 2: Run navigation tests and verify RED**

Run: `pnpm --dir frontend test -- src/app/navigation`

Expected: FAIL because the navigation modules do not exist.

- [ ] **Step 3: Implement the shared navigation definition and renderers**

Use one typed config:

```ts
export interface NavigationItem {
  label: string;
  to: "/review" | "/knowledge" | "/settings";
  icon: LucideIcon;
}

export const NAVIGATION_GROUPS = [
  { label: "工作台", items: reviewAndKnowledgeItems },
  { label: "系统", items: settingsItems },
] as const;
```

`PrimaryNavigation` renders semantic groups and closes the drawer through `onNavigate`. `MobileNavigation` stores open state, listens for Escape only while open, focuses the close button on open, restores focus to the trigger on close, applies a backdrop button, and closes after a navigation selection.

- [ ] **Step 4: Run navigation and frontend tests**

Run: `pnpm --dir frontend test -- src/app/navigation`

Expected: PASS.

Run: `pnpm --dir frontend test`

Expected: PASS with no unhandled React warnings.

- [ ] **Step 5: Commit navigation behavior**

```bash
git add frontend/src/app/navigation frontend/src/app/layout/AppShell.tsx
git commit -m "feat(ui): add adaptive product navigation"
```

---

### Task 3: Page Headers and Workflow-Aware Page Layouts

**Files:**
- Create: `frontend/src/app/layout/PageHeader.tsx`
- Create: `frontend/src/app/layout/PageHeader.test.tsx`
- Create: `frontend/src/features/review/FlowSummary.tsx`
- Create: `frontend/src/features/review/FlowSummary.test.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/review/ReviewPage.test.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.test.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`

**Interfaces:**
- Produces: `PageHeader({ title, description, health, workspace })` with one page-level `h1`.
- Produces: `FlowSummary({ healthStatus, workspace, draftQuestion, latestReportMarkdown, reportConfirmed, indexedCount })`.
- Adds: optional navigation actions in Review and Knowledge empty states through `Link`.
- Removes: old global progress strip and global flow status panel.

- [ ] **Step 1: Write failing page composition tests**

Assert semantic page heading, concise description, global status, and contextual recovery actions:

```tsx
it("shows review as a workspace with a knowledge recovery action", () => {
  renderReviewRoute({ workspace: readyWorkspace, draftQuestion: null });
  expect(screen.getByRole("heading", { level: 1, name: "复习" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "前往知识库" })).toHaveAttribute("href", "/knowledge");
  expect(screen.getByText("下一步：上传资料生成题库草稿")).toBeInTheDocument();
});

it("sends users without a workspace to settings", () => {
  renderKnowledgeRoute({ workspace: null });
  expect(screen.getByRole("link", { name: "前往设置" })).toHaveAttribute("href", "/settings");
});
```

- [ ] **Step 2: Run page tests and verify RED**

Run: `pnpm --dir frontend test -- src/features/review src/features/knowledge src/features/settings src/app/layout/PageHeader.test.tsx`

Expected: FAIL because page-level headers, links, and `FlowSummary` do not exist.

- [ ] **Step 3: Implement page headers and move flow state into Review**

Render `PageHeader` above the active route. Use these exact descriptions:

- Review: `围绕题库持续练习，形成可追踪的掌握度。`
- Knowledge: `管理 Agent 可引用的资料、草稿与 Vault 索引。`
- Settings: `配置工作区、模型服务与不同任务的模型用途。`

Move `getNextStepText` and the five workflow states from `AppShell` into `FlowSummary`. Render it in Review's context column. Add `Link` actions to the Review and Knowledge empty states. Keep all existing form labels, button names, API calls, and callback contracts unchanged.

- [ ] **Step 4: Run page tests and full frontend tests**

Run: `pnpm --dir frontend test -- src/features/review src/features/knowledge src/features/settings src/app/layout`

Expected: PASS.

Run: `pnpm --dir frontend test`

Expected: PASS.

- [ ] **Step 5: Commit page composition**

```bash
git add frontend/src/app/layout frontend/src/features/review frontend/src/features/knowledge frontend/src/features/settings
git commit -m "feat(ui): compose routed product pages"
```

---

### Task 4: Product Visual System and Responsive Layout

**Files:**
- Modify: `frontend/src/app/global.css`
- Modify: `frontend/src/shared/ui/Card.tsx`
- Modify: `frontend/src/shared/ui/Button.tsx`
- Modify: `frontend/src/shared/ui/Badge.tsx`
- Modify: `frontend/src/shared/ui/Field.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `tests/e2e/mvp-smoke.spec.ts`

**Interfaces:**
- Consumes: semantic class names from Tasks 1-3.
- Produces: responsive desktop sidebar, mobile top bar/drawer, page header, Review two-column workspace, and single-column mobile layouts.
- Preserves: shared component public props and accessible names.

- [ ] **Step 1: Add failing structural and E2E assertions**

Update the shell test to assert `navigation` and `main` landmarks and the E2E test to navigate across all three routes:

```ts
await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
await page.getByRole("link", { name: "知识库" }).click();
await expect(page).toHaveURL(/\/knowledge$/);
await expect(page.getByRole("heading", { level: 1, name: "知识库" })).toBeVisible();
await page.getByRole("link", { name: "设置" }).click();
await expect(page).toHaveURL(/\/settings$/);
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pnpm --dir frontend test -- src/app/App.test.tsx`

Expected: FAIL until the final landmarks and responsive shell composition are present.

- [ ] **Step 3: Replace MVP visual tokens and layout CSS**

Define neutral semantic tokens for canvas, surfaces, text, muted text, border, indigo primary, success, warning, danger, focus, z-index, sidebar width, and content widths. Implement:

- `.app-shell`, `.desktop-sidebar`, `.mobile-header`, `.mobile-drawer`, `.page-shell`.
- `.page-header`, `.page-content`, `.review-workspace`, `.review-workspace__main`, `.review-workspace__aside`.
- 1024px desktop breakpoint and mobile-first base layout.
- 8px maximum card radius, subtle border and shadow, no gradient or decorative blobs.
- 44px minimum navigation and button targets.
- overflow wrapping for paths, model IDs, report paths, and code blocks.
- `prefers-reduced-motion` overrides.

Remove obsolete `.progress-strip` and single-column global flow styles after confirming no component references remain.

- [ ] **Step 4: Run all frontend verification**

Run: `pnpm --dir frontend test`

Expected: all Vitest tests PASS.

Run: `pnpm --dir frontend build`

Expected: TypeScript and Vite build exit 0.

Run: `pnpm --dir frontend e2e`

Expected: Playwright smoke tests PASS when backend and frontend fixtures are available.

- [ ] **Step 5: Commit visual and responsive implementation**

```bash
git add frontend/src/app/global.css frontend/src/shared/ui frontend/src/app/App.test.tsx tests/e2e/mvp-smoke.spec.ts
git commit -m "feat(ui): finish responsive product workspace"
```

---

### Task 5: Browser QA and Development Documentation

**Files:**
- Create: `docs/verification/2026-07-11-product-layout-redesign.md` (local ignored guide)
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Produces: exact startup and manual verification steps for the user.
- Produces: current roadmap status and design findings in tracked planning files.

- [ ] **Step 1: Start the application and inspect real routes**

Run backend and frontend using the repository's documented commands. Open `/review`, `/knowledge`, and `/settings` in the browser. Verify navigation, active state, Workspace restoration, and no console errors.

- [ ] **Step 2: Verify responsive layouts**

Capture and inspect 1440x1000, 1024x768, 768x1024, and 375x812 viewports. At each viewport verify no horizontal overflow, no clipped actions, no overlapping fixed UI, and readable wrapped paths. On mobile verify menu open, backdrop close, Escape close, route selection close, and focus return.

- [ ] **Step 3: Run final automated verification**

Run: `pnpm --dir frontend test && pnpm --dir frontend build`

Expected: all tests pass and build exits 0.

Run the repository backend test command recorded in the existing verification guide.

Expected: no backend regression from the frontend-only change.

- [ ] **Step 4: Write manual verification and update planning files**

The local verification guide must explain startup, each route, the end-to-end Workspace/upload/review flow, responsive checks, important source files, and known R1.2 boundaries. Update `task_plan.md`, `findings.md`, and `progress.md` with actual commit IDs and fresh test counts, not planned results.

- [ ] **Step 5: Commit tracked documentation**

```bash
git add task_plan.md findings.md progress.md
git commit -m "docs: record product layout verification"
```

The ignored `docs/verification/2026-07-11-product-layout-redesign.md` remains local and must not be force-added.
