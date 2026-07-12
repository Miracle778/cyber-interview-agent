# Settings Experience Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat settings-card stream with a configuration overview, task-oriented navigation, and progressively disclosed model and diagnostic controls without changing backend behavior.

**Architecture:** Keep `SettingsPage` as the owner of Workspace restoration and page-level navigation. Add small presentational components for navigation, overview status, and disclosure; derive overview status from existing settings and HITL APIs through stable TanStack Query keys. Existing Provider, model-binding, Runtime, security, and approval components retain their business behavior and are mounted only in their selected task domain.

**Tech Stack:** React 19, TypeScript, TanStack Query, Lucide React, Vitest, Testing Library, Playwright, CSS.

## Global Constraints

- Do not add or modify backend APIs, database schema, Provider protocols, model-binding payloads, Runtime graphs, security checks, or HITL transitions.
- Do not implement R1.2 context compression, token/context metering, or R2 behavior.
- Do not modify or commit `docs/my_idea.md`.
- Keep the existing light visual language, semantic tokens, Lucide outline icons, component primitives, and error advice.
- Every navigation item, disclosure trigger, and primary interaction must be at least 44px high and keyboard operable.
- Use text and icons in addition to semantic color; color must not be the only status signal.
- Desktop, tablet, and 375px layouts must not create page-level horizontal scrolling.
- Use 150–200ms color, border, and opacity transitions only; disable non-essential transitions under `prefers-reduced-motion: reduce`.
- Use targeted frontend tests during Tasks 1–3. Run one final frontend regression, production build, browser acceptance, and document gate in Task 4. Do not run backend regression because this slice has no backend changes.
- Keep one Agent on this slice end-to-end; do not create subagents.

---

## File Map

- Create `frontend/src/features/settings/SettingsNavigation.tsx`: four-section accessible page navigation.
- Create `frontend/src/features/settings/SettingsNavigation.test.tsx`: selected, disabled, and keyboard semantics.
- Create `frontend/src/features/settings/SettingsOverview.tsx`: configuration status list and single recommended next action.
- Create `frontend/src/features/settings/SettingsOverview.test.tsx`: status rendering and section routing.
- Create `frontend/src/features/settings/SettingsDisclosure.tsx`: reusable diagnostic disclosure shell.
- Create `frontend/src/features/settings/SettingsDisclosure.test.tsx`: `aria-expanded`, region linkage, and independent expansion.
- Modify `frontend/src/features/settings/SettingsPage.tsx`: summary queries, section state, single content panel, and pending-action expansion.
- Modify `frontend/src/features/settings/SettingsPage.test.tsx`: overview, routing, restoration, and diagnostic disclosure integration.
- Modify `frontend/src/features/settings/ProviderManager.tsx`: collapsed Provider creation form and dirty-close protection.
- Modify `frontend/src/features/settings/ProviderManager.test.tsx`: create-form disclosure and unchanged Provider lifecycle.
- Modify `frontend/src/features/settings/ModelBindings.tsx`: add save notification, stable content anchor, and empty-state guidance.
- Modify `frontend/src/app/global.css`: settings shell, navigation, overview, disclosure, desktop/mobile layout, focus, and reduced motion.
- Create `tests/e2e/settings-experience.spec.ts`: real settings UI navigation and responsive acceptance.
- Modify `task_plan.md`, `findings.md`, `progress.md`: bounded current-slice state and handoff.
- Create `docs/verification/settings-experience-redesign.md`: incremental evidence, then final user guide.
- Create `docs/learning/settings-experience-redesign/`: seven-file ownership pack generated after implementation stabilizes.

### Task 1: Add the settings shell, navigation, and configuration overview

**Files:**
- Create: `frontend/src/features/settings/SettingsNavigation.tsx`
- Create: `frontend/src/features/settings/SettingsNavigation.test.tsx`
- Create: `frontend/src/features/settings/SettingsOverview.tsx`
- Create: `frontend/src/features/settings/SettingsOverview.test.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Produces: `SettingsSection = "overview" | "workspace" | "models" | "diagnostics"`.
- Produces: `<SettingsNavigation current onSelect disabledSections? />`.
- Produces: `SettingsStatusItem` and `<SettingsOverview items recommendedSection onSelect />`.
- Consumes: `listProviders`, `getWorkspaceModelBindings`, and `listActions` with existing response types.

- [ ] **Step 1: Add failing navigation and overview component tests**

Create tests with these exact public contracts:

```tsx
render(<SettingsNavigation current="overview" onSelect={onSelect} />);
expect(screen.getByRole("navigation", { name: "设置分组" })).toBeInTheDocument();
expect(screen.getByRole("button", { name: "配置概览" })).toHaveAttribute("aria-current", "page");
fireEvent.click(screen.getByRole("button", { name: "模型服务" }));
expect(onSelect).toHaveBeenCalledWith("models");
```

```tsx
const items: SettingsStatusItem[] = [
  {
    id: "workspace",
    title: "工作区",
    status: "已就绪",
    description: "/tmp/cyber-demo",
    tone: "success",
    section: "workspace",
  },
  {
    id: "providers",
    title: "Provider",
    status: "待配置",
    description: "尚未添加 Provider",
    tone: "warning",
    section: "models",
  },
];
render(<SettingsOverview items={items} recommendedSection="models" onSelect={onSelect} />);
expect(screen.getByRole("heading", { name: "配置概览" })).toBeInTheDocument();
expect(screen.getByText("尚未添加 Provider")).toBeInTheDocument();
fireEvent.click(screen.getByRole("button", { name: "下一步：配置模型服务" }));
expect(onSelect).toHaveBeenCalledWith("models");
```

- [ ] **Step 2: Run the new component tests and verify RED**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run \
  src/features/settings/SettingsNavigation.test.tsx \
  src/features/settings/SettingsOverview.test.tsx \
  --reporter=dot
```

Expected: FAIL because both modules are missing.

- [ ] **Step 3: Implement the navigation and overview presentational boundaries**

Define in `SettingsNavigation.tsx`:

```tsx
export type SettingsSection = "overview" | "workspace" | "models" | "diagnostics";

interface SettingsNavigationProps {
  current: SettingsSection;
  onSelect: (section: SettingsSection) => void;
  disabledSections?: readonly SettingsSection[];
}
```

Render a `<nav aria-label="设置分组">` with four semantic buttons in this order: 配置概览, 工作区, 模型服务, 运行诊断. Use Lucide `LayoutDashboard`, `FolderCog`, `ServerCog`, and `ShieldCheck`. The selected button must use `aria-current="page"`; disabled items must use the native `disabled` attribute and a visible explanation in their secondary text.

Define in `SettingsOverview.tsx`:

```tsx
export type SettingsStatusTone = "neutral" | "success" | "warning" | "danger";

export interface SettingsStatusItem {
  id: "workspace" | "providers" | "bindings" | "diagnostics";
  title: string;
  status: string;
  description: string;
  tone: SettingsStatusTone;
  section: SettingsSection;
}

interface SettingsOverviewProps {
  items: readonly SettingsStatusItem[];
  recommendedSection: Exclude<SettingsSection, "overview">;
  onSelect: (section: SettingsSection) => void;
}
```

Render one status list with icon, title, textual state, description, and a ghost “查看” button for each item. Render exactly one primary CTA using these labels: 工作区 → `下一步：初始化工作区`, models → `下一步：配置模型服务`, diagnostics → `下一步：运行诊断`.

- [ ] **Step 4: Add failing SettingsPage integration tests for default overview and single-panel routing**

Update `installSettingsFetch` to return:

```tsx
if (url === "/api/agent/actions?workspaceId=w1&status=pending") {
  return Response.json([]);
}
```

Add assertions:

```tsx
renderSettings(workspace);
expect(await screen.findByRole("heading", { name: "配置概览" })).toBeInTheDocument();
expect(screen.queryByText("Provider 管理")).not.toBeInTheDocument();
expect(screen.queryByText("Agent Runtime")).not.toBeInTheDocument();

fireEvent.click(screen.getByRole("button", { name: "模型服务" }));
expect(await screen.findByText("Provider 管理")).toBeInTheDocument();
expect(screen.getByText("模型用途绑定")).toBeInTheDocument();
expect(screen.queryByText("Agent Runtime")).not.toBeInTheDocument();
```

For `workspace=null`, assert the overview CTA is `下一步：初始化工作区`, click it, and assert the Workspace Path field becomes visible.

- [ ] **Step 5: Run SettingsPage tests and verify RED**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run src/features/settings/SettingsPage.test.tsx --reporter=dot
```

Expected: FAIL because SettingsPage still renders the flat stack and has no overview navigation.

- [ ] **Step 6: Implement summary queries and the single content panel**

In `SettingsPage`, add:

```tsx
const [section, setSection] = useState<SettingsSection>("overview");

const providersQuery = useQuery({
  queryKey: ["settings-providers-summary"],
  queryFn: listProviders,
  enabled: Boolean(workspaceId),
});
const bindingsQuery = useQuery({
  queryKey: ["workspace-model-bindings", workspaceId],
  queryFn: () => getWorkspaceModelBindings(workspaceId!),
  enabled: Boolean(workspaceId),
});
const actionsQuery = useQuery({
  queryKey: ["pending-actions", workspaceId],
  queryFn: () => listActions(workspaceId!, { status: "pending" }),
  enabled: Boolean(workspaceId),
});
```

Use one page-level callback so Provider changes update both the detail and overview:

```tsx
function handleProvidersChanged() {
  setProviderRevision((revision) => revision + 1);
  void queryClient.invalidateQueries({ queryKey: ["settings-providers-summary"] });
  if (workspaceId) {
    void queryClient.invalidateQueries({
      queryKey: ["workspace-model-bindings", workspaceId],
    });
  }
}
```

Derive the overview without introducing persisted UI state:

```tsx
const bindingCount = Object.values(bindingsQuery.data?.bindings ?? {})
  .filter(Boolean).length;
const pendingCount = actionsQuery.data?.length ?? 0;
const recommendedSection: Exclude<SettingsSection, "overview"> = !workspaceId
  ? "workspace"
  : (providersQuery.data?.length ?? 0) === 0
    ? "models"
    : bindingCount < 4
      ? "models"
      : "diagnostics";
```

Render `settings-layout` with `SettingsNavigation` and one `settings-content` panel. Mount only the selected section. Keep the existing Workspace form in the workspace section; render `ProviderManager` then `ModelBindings` only in models; diagnostics will be temporarily rendered as its existing stack until Task 3. Disable models and diagnostics navigation while Workspace restoration is incomplete, but keep the overview and workspace available.

- [ ] **Step 7: Add the base settings shell styles**

Add desktop rules:

```css
.settings-layout {
  display: grid;
  grid-template-columns: minmax(220px, 240px) minmax(0, 1fr);
  gap: var(--space-6);
  align-items: start;
}

.settings-navigation {
  position: sticky;
  top: var(--space-5);
}

.settings-nav__item {
  min-height: 44px;
  width: 100%;
}
```

Use existing semantic variables for surfaces, border, text, and focus. At `max-width: 1023px`, change to one column, remove sticky positioning, and render `.settings-nav__list` as a wrapping grid with `grid-template-columns: repeat(2, minmax(0, 1fr))`; at `max-width: 520px`, use one column. Do not use horizontal overflow.

- [ ] **Step 8: Run Task 1 targeted tests and typecheck**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run \
  src/features/settings/SettingsNavigation.test.tsx \
  src/features/settings/SettingsOverview.test.tsx \
  src/features/settings/SettingsPage.test.tsx \
  src/app/App.test.tsx \
  --reporter=dot
./node_modules/.bin/tsc --noEmit
```

Expected: all selected tests PASS and TypeScript exits 0.

- [ ] **Step 9: Record Task 1 evidence and commit**

Append the exact command and count to `docs/verification/settings-experience-redesign.md`, then:

```bash
git add frontend/src/features/settings/SettingsNavigation.tsx \
  frontend/src/features/settings/SettingsNavigation.test.tsx \
  frontend/src/features/settings/SettingsOverview.tsx \
  frontend/src/features/settings/SettingsOverview.test.tsx \
  frontend/src/features/settings/SettingsPage.tsx \
  frontend/src/features/settings/SettingsPage.test.tsx \
  frontend/src/app/global.css
git commit -m "feat(settings): add configuration overview"
```

### Task 2: Disclose Provider creation and clarify model-service order

**Files:**
- Modify: `frontend/src/features/settings/ProviderManager.tsx`
- Modify: `frontend/src/features/settings/ProviderManager.test.tsx`
- Modify: `frontend/src/features/settings/ModelBindings.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Preserves: `<ProviderManager onProvidersChanged? />`.
- Produces: Provider creation trigger `aria-expanded` and controlled region `provider-create-form`.
- Extends: `<ModelBindings workspaceId refreshKey? onBindingsChanged? />`; its four-role save payload remains unchanged.

- [ ] **Step 1: Add failing Provider creation disclosure tests**

Update the existing ProviderManager lifecycle test to assert:

```tsx
render(<ProviderManager />);
const trigger = screen.getByRole("button", { name: "添加 Provider" });
expect(trigger).toHaveAttribute("aria-expanded", "false");
expect(screen.queryByLabelText("Provider 名称")).not.toBeInTheDocument();

fireEvent.click(trigger);
expect(trigger).toHaveAttribute("aria-expanded", "true");
expect(screen.getByLabelText("Provider 名称")).toBeInTheDocument();
```

After filling and submitting with `保存 Provider`, assert the form disappears and the new Provider card remains. Add a dirty-close test that fills the name, clicks `取消添加`, declines `globalThis.confirm("放弃未保存的 Provider 配置？")`, and asserts the form remains open; accepting closes and clears the fields.

- [ ] **Step 2: Run Provider tests and verify RED**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run src/features/settings/ProviderManager.test.tsx --reporter=dot
```

Expected: FAIL because the creation form is always visible and has no disclosure semantics.

- [ ] **Step 3: Implement the Provider creation disclosure**

Add:

```tsx
const [createExpanded, setCreateExpanded] = useState(false);
const createDirty = Boolean(name.trim() || baseUrl.trim() || apiKey.trim());

function closeCreateForm() {
  if (createDirty && !globalThis.confirm("放弃未保存的 Provider 配置？")) return;
  setName("");
  setBaseUrl("");
  setApiKey("");
  setCreateExpanded(false);
}
```

Move the four creation fields and actions into `<div id="provider-create-form">`. Render a secondary `添加 Provider` trigger with `aria-expanded` and `aria-controls`. Inside the region use `保存 Provider` as the only primary action and `取消添加` as a ghost action. On successful create, clear secrets and close the region. Existing Provider cards must remain visible regardless of form state.

- [ ] **Step 4: Add model-binding empty-state guidance**

When no enabled model is available, replace the current single warning line with:

```tsx
<div className="settings-guidance" role="status">
  <p>没有可用于绑定的模型</p>
  <p>请先在上方 Provider 中添加模型并完成连接测试。</p>
</div>
```

Do not add another API call or navigation state to `ModelBindings`.

Add an optional callback to the existing props:

```tsx
interface ModelBindingsProps {
  workspaceId: string;
  refreshKey?: number;
  onBindingsChanged?: () => void;
}
```

Call `onBindingsChanged?.()` only after `replaceWorkspaceModelBindings` succeeds. In `SettingsPage`, pass a callback that invalidates `["workspace-model-bindings", workspaceId]` so returning to overview immediately shows the new binding count. Add a test that saves four roles and asserts the callback fires once.

- [ ] **Step 5: Run model-service tests and typecheck**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run \
  src/features/settings/ProviderManager.test.tsx \
  src/features/settings/ModelBindings.test.tsx \
  src/features/settings/SettingsPage.test.tsx \
  --reporter=dot
./node_modules/.bin/tsc --noEmit
```

Expected: all selected tests PASS and TypeScript exits 0.

- [ ] **Step 6: Record Task 2 evidence and commit**

Append the exact command and count to verification, then:

```bash
git add frontend/src/features/settings/ProviderManager.tsx \
  frontend/src/features/settings/ProviderManager.test.tsx \
  frontend/src/features/settings/ModelBindings.tsx \
  frontend/src/app/global.css
git commit -m "feat(settings): disclose model configuration progressively"
```

### Task 3: Add diagnostic disclosures and finish responsive accessibility

**Files:**
- Create: `frontend/src/features/settings/SettingsDisclosure.tsx`
- Create: `frontend/src/features/settings/SettingsDisclosure.test.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.test.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Produces: `<SettingsDisclosure id title description defaultExpanded? children />`.
- Consumes: pending actions from `actionsQuery` in Task 1.
- Preserves: `RuntimeDiagnostics`, `SecurityDiagnostics`, and diagnostic `ActionCenter` behavior.

- [ ] **Step 1: Add failing disclosure component tests**

Create:

```tsx
render(
  <SettingsDisclosure id="runtime" title="Agent Runtime" description="检查运行链路">
    <p>Runtime detail</p>
  </SettingsDisclosure>,
);
const trigger = screen.getByRole("button", { name: /Agent Runtime/ });
expect(trigger).toHaveAttribute("aria-expanded", "false");
expect(screen.queryByText("Runtime detail")).not.toBeInTheDocument();
fireEvent.click(trigger);
expect(trigger).toHaveAttribute("aria-expanded", "true");
expect(screen.getByRole("region", { name: "Agent Runtime" })).toHaveTextContent("Runtime detail");
```

Render two disclosures and assert expanding one does not collapse the other.

- [ ] **Step 2: Run disclosure tests and verify RED**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run src/features/settings/SettingsDisclosure.test.tsx --reporter=dot
```

Expected: FAIL because `SettingsDisclosure` is missing.

- [ ] **Step 3: Implement `SettingsDisclosure`**

Use internal state initialized from `defaultExpanded`. The trigger must be a native button with `aria-expanded`, `aria-controls="<id>-panel"`, and a Chevron icon that is decorative. Mount children only while expanded so hidden diagnostics do not begin network work. The panel must be:

```tsx
<section id={`${id}-panel`} className="settings-disclosure__panel" aria-label={title}>
  {children}
</section>
```

Add an effect that opens the region if `defaultExpanded` changes from false to true, so a newly observed pending action can reveal approval.

- [ ] **Step 4: Add failing SettingsPage diagnostic integration tests**

Navigate to 运行诊断 and assert:

```tsx
const runtime = screen.getByRole("button", { name: /Agent Runtime/ });
const security = screen.getByRole("button", { name: /工具安全/ });
const approval = screen.getByRole("button", { name: /人工确认/ });
expect(runtime).toHaveAttribute("aria-expanded", "false");
expect(security).toHaveAttribute("aria-expanded", "false");
expect(approval).toHaveAttribute("aria-expanded", "false");
expect(screen.queryByRole("button", { name: "运行自检" })).not.toBeInTheDocument();
fireEvent.click(runtime);
expect(await screen.findByRole("button", { name: "运行自检" })).toBeInTheDocument();
```

Mock one pending action, navigate to diagnostics, and assert the 人工确认 trigger has `aria-expanded="true"` and its approve/reject controls are visible.

- [ ] **Step 5: Integrate independent diagnostic disclosures**

Replace the diagnostic flat stack with three disclosures:

```tsx
<SettingsDisclosure id="runtime" title="Agent Runtime" description="检查会话、事件与恢复链路">
  <RuntimeDiagnostics workspaceId={workspaceId} />
</SettingsDisclosure>
<SettingsDisclosure id="security" title="工具安全" description="检查路径、命令与审计边界">
  <SecurityDiagnostics workspaceId={workspaceId} />
</SettingsDisclosure>
<SettingsDisclosure
  id="approval"
  title="人工确认"
  description={pendingCount > 0 ? `${pendingCount} 个动作等待处理` : "检查 HITL 动作与决定链路"}
  defaultExpanded={pendingCount > 0}
>
  <ActionCenter workspaceId={workspaceId} />
</SettingsDisclosure>
```

Do not alter diagnostic components or ActionCenter props.

- [ ] **Step 6: Finish responsive, focus, and reduced-motion styles**

Add styles for `.settings-overview__item`, `.settings-disclosure__trigger`, and `.settings-disclosure__panel` using existing surface/border tokens. Require `min-height: 44px`, wrapping button rows, `min-width: 0`, and `overflow-wrap: anywhere` for paths and URLs. Use a visible `:focus-visible` ring consistent with existing buttons. Chevron rotation may use a 150ms transform; remove it under reduced motion. Verify no selector animates width, height, top, or left.

- [ ] **Step 7: Run Task 3 targeted tests and typecheck**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run \
  src/features/settings/SettingsDisclosure.test.tsx \
  src/features/settings/SettingsPage.test.tsx \
  src/features/settings/RuntimeDiagnostics.test.tsx \
  src/features/settings/SecurityDiagnostics.test.tsx \
  src/features/agent/ActionCenter.test.tsx \
  src/app/App.test.tsx \
  --reporter=dot
./node_modules/.bin/tsc --noEmit
```

Expected: all selected tests PASS and TypeScript exits 0.

- [ ] **Step 8: Run the minimal browser path before final documentation**

Using isolated services, verify: open settings → default overview → enter Workspace → return to overview → enter Models → open/close Provider creation → enter Diagnostics → expand Runtime and Security. Verify empty approval remains collapsed. Record only factual evidence in `docs/verification/settings-experience-redesign.md`.

- [ ] **Step 9: Record Task 3 evidence and commit**

```bash
git add frontend/src/features/settings/SettingsDisclosure.tsx \
  frontend/src/features/settings/SettingsDisclosure.test.tsx \
  frontend/src/features/settings/SettingsPage.tsx \
  frontend/src/features/settings/SettingsPage.test.tsx \
  frontend/src/app/global.css
git commit -m "feat(settings): organize runtime diagnostics"
```

### Task 4: Final browser acceptance, regression, and stage handoff

**Files:**
- Create: `tests/e2e/settings-experience.spec.ts`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `docs/superpowers/plans/2026-07-12-settings-experience-redesign.md`
- Finalize: `docs/verification/settings-experience-redesign.md`
- Create: `docs/learning/settings-experience-redesign/overview.md`
- Create: `docs/learning/settings-experience-redesign/architecture.md`
- Create: `docs/learning/settings-experience-redesign/code-walkthrough.md`
- Create: `docs/learning/settings-experience-redesign/failure-journal.md`
- Create: `docs/learning/settings-experience-redesign/interview-questions.md`
- Create: `docs/learning/settings-experience-redesign/presentation-script.md`
- Create: `docs/learning/settings-experience-redesign/exercises.md`

**Interfaces:**
- Produces: repeatable 1440×1000 and 375×812 settings acceptance.
- Produces: final user guide and seven-file ownership pack.
- Preserves: next product task `R1.2 context compression and token/context usage foundation`.

- [ ] **Step 1: Add the real browser acceptance test**

Create a Playwright test that registers `/private/tmp/cyber-settings-e2e-workspace`, opens `/settings`, and verifies:

```ts
const workspaceResponse = await request.post(
  "http://127.0.0.1:8017/api/settings/workspaces",
  { data: { rootPath: "/private/tmp/cyber-settings-e2e-workspace" } },
);
expect(workspaceResponse.ok()).toBeTruthy();

await page.setViewportSize({ width: 1440, height: 1000 });
await page.goto("/settings");
await expect(page.getByRole("heading", { name: "配置概览" })).toBeVisible();
await expect(page.getByText("Provider 管理")).toHaveCount(0);

await page.getByRole("button", { name: "模型服务" }).click();
await expect(page.getByText("Provider 管理")).toBeVisible();
const addProvider = page.getByRole("button", { name: "添加 Provider" });
await expect(addProvider).toHaveAttribute("aria-expanded", "false");
await addProvider.click();
await expect(page.getByLabel("Provider 名称")).toBeVisible();

await page.getByRole("button", { name: "运行诊断" }).click();
await page.getByRole("button", { name: /Agent Runtime/ }).click();
await expect(page.getByRole("button", { name: "运行自检" })).toBeVisible();

await page.reload();
await expect(page.getByRole("heading", { name: "配置概览" })).toBeVisible();
const desktopOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
);
expect(desktopOverflow).toBeFalsy();

await page.setViewportSize({ width: 375, height: 812 });
const mobileOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
);
expect(mobileOverflow).toBeFalsy();

await page.getByRole("button", { name: "配置概览" }).focus();
await page.keyboard.press("Tab");
await expect(page.getByRole("button", { name: "工作区" })).toBeFocused();
```

Capture console warning/error messages and assert the list is empty. Focus the 配置概览 navigation button, press Tab, and assert focus advances according to DOM order.

- [ ] **Step 2: Run the only final frontend regression and build**

Run:

```bash
cd frontend
./node_modules/.bin/vitest run --reporter=dot
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/vite build
```

Expected: all frontend tests PASS; TypeScript and Vite build exit 0. Record exact test counts and build summary.

- [ ] **Step 3: Run one complete browser acceptance pass**

Run only the new settings E2E with the repository Playwright config. Verify 1440×1000, 375×812, keyboard order, refresh-to-overview, Provider form disclosure, diagnostic disclosure, console logs, and horizontal overflow. If a scenario fails, re-run only that test after the fix.

- [ ] **Step 4: Finalize verification and learning once**

Reshape verification into the final user guide using `docs/superpowers/templates/stage-verification-template.md`. Generate all seven learning files using `docs/superpowers/templates/stage-learning-pack-template.md`. Record only this slice's actual failures in `failure-journal.md`; do not copy Pre-R2 knowledge-workspace claims.

- [ ] **Step 5: Update the formal checklist and short state**

Mark completed plan checkboxes. Update `task_plan.md` to this slice and its branch/worktree, add only durable settings architecture findings to `findings.md`, and add a handoff under 10 lines to `progress.md`. Keep R1.2 context/token work explicitly pending.

- [ ] **Step 6: Run the document gate**

Run:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/settings-experience-redesign.md \
  --learning docs/learning/settings-experience-redesign/ \
  --plan docs/superpowers/plans/2026-07-12-settings-experience-redesign.md
```

Expected: `Stage documentation gate passed`. Manually verify test counts come from Step 2 and browser claims come from Step 3.

- [ ] **Step 7: Commit acceptance evidence**

Only formal documents and short state are tracked:

```bash
git add task_plan.md findings.md progress.md \
  docs/superpowers/plans/2026-07-12-settings-experience-redesign.md \
  tests/e2e/settings-experience.spec.ts
git commit -m "docs: close settings experience redesign"
```

Keep `docs/verification/` and `docs/learning/` local, then explicitly synchronize them after merge.

- [ ] **Step 8: Final branch review**

Run:

```bash
git status --short
git diff main...HEAD --check
git diff main...HEAD --stat
git log --oneline main..HEAD
git diff --name-only main...HEAD -- docs/my_idea.md
```

Expected: no uncommitted product files, no `docs/my_idea.md` change, no unresolved Critical/Important issue, and only intentional commits. Report product evidence, maturity boundary, ownership status, next product task, and non-blocking exercise separately.
