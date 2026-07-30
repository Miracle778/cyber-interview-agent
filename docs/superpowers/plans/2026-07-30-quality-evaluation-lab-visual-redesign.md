# Quality Evaluation Lab Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/agents/evaluations` as a comparison-centered quality workbench faithful to the approved reference while preserving the existing evaluation APIs and safety boundaries.

**Architecture:** Keep backend evaluation records immutable and unchanged. Add a frontend presentation layer that translates Pack IDs, dimension IDs, statuses, scores, evidence, and feedback into business-facing report semantics; compose the page from a report header, baseline/candidate metric matrix, quality-gate rail, regression-case table, and secondary trends view.

**Tech Stack:** React 19, TypeScript, TanStack Query, React Router, Lucide React, existing design tokens, Vitest, Testing Library, Playwright/Chrome.

## Global Constraints

- The selected target is `docs/superpowers/assets/agent-observability/quality-evaluation-lab-reference.png`.
- Preserve existing API contracts and evaluation immutability; this redesign is frontend-only.
- Use the existing application shell and design tokens. Do not introduce a second palette, gradients, decorative shadows, or a new icon package.
- Treat the page as a desktop workbench: fixed page header, one primary content owner, and no document-level overflow at 1440px.
- Baseline/candidate comparison is the primary task; trends are a secondary view.
- Never invent baseline results, cost, Provider reasoning, business status, or quality-gate outcomes.
- Raw Judge input/output remains behind advanced diagnostics.
- User-facing labels must not expose raw enum values, UUIDs, or internal Pack/dimension IDs as the primary text.
- Validate 390, 768, 1024, and 1440 widths; primary actions remain reachable and targets are at least 44px.

---

### Task 1: Add evaluation presentation semantics

**Files:**
- Create: `frontend/src/features/evaluation/evaluationPresentation.ts`
- Create: `frontend/src/features/evaluation/evaluationPresentation.test.ts`

**Interfaces:**
- Consumes: `EvaluationRun`, `EvaluationDimension`, `EvaluationFeedback`.
- Produces: `evaluationPackLabel(id)`, `dimensionLabel(id)`, `evaluationStatusMeta(status)`, `dimensionOutcome(dimension)`, `summarizeEvaluation(run, feedback)`, and `formatEvaluationVersion(run)`.

- [x] **Step 1: Write failing presentation tests**

Cover:

```ts
expect(evaluationPackLabel("question-curation.v1")).toBe("题目整理质量");
expect(dimensionLabel("source_fidelity")).toBe("来源忠实度");
expect(evaluationStatusMeta("completed").label).toBe("评估完成");
expect(dimensionOutcome(scoredDimension(92)).tone).toBe("success");
expect(dimensionOutcome(scoredDimension(61)).tone).toBe("warning");
expect(dimensionOutcome(failedRule()).tone).toBe("danger");
```

Also assert unknown IDs receive a readable normalized fallback rather than raw snake_case.

- [x] **Step 2: Run the presentation test and verify RED**

Run:

```bash
cd frontend
npx vitest run src/features/evaluation/evaluationPresentation.test.ts
```

Expected: fail because the module does not exist.

- [x] **Step 3: Implement the presentation module**

Use explicit maps for current Eval Packs and dimension IDs. `summarizeEvaluation` returns only derived counts and tones:

```ts
interface EvaluationSummary {
  passed: number;
  attention: number;
  failed: number;
  averageScore: number | null;
  humanVerdict: "accurate" | "incorrect" | "uncertain" | null;
}
```

Score bands are display semantics only: `>= 85 success`, `>= 70 neutral`, `>= 50 warning`, otherwise danger. Deterministic failed/error statuses are always danger. Do not turn these bands into backend quality gates.

- [x] **Step 4: Run tests and TypeScript**

```bash
cd frontend
npx vitest run src/features/evaluation/evaluationPresentation.test.ts
npx tsc --noEmit
```

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/evaluation/evaluationPresentation.ts \
  frontend/src/features/evaluation/evaluationPresentation.test.ts
git commit -m "feat(agent-evaluation): add report presentation semantics"
```

### Task 2: Build the comparison-centered report surface

**Files:**
- Create: `frontend/src/features/evaluation/EvaluationReportHeader.tsx`
- Create: `frontend/src/features/evaluation/EvaluationMetricMatrix.tsx`
- Create: `frontend/src/features/evaluation/EvaluationMetricMatrix.test.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationCompareView.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationCompareView.test.tsx`
- Modify: `frontend/src/features/evaluation/JudgeResultPanel.tsx`

**Interfaces:**
- Consumes: one selected `EvaluationRun`, optional compatible `EvaluationComparison`, optional baseline/candidate selection callbacks.
- Produces: a report header with business label/status/version metadata and a metric matrix with explicit baseline, candidate, delta, trend direction, and expandable evidence detail.

- [x] **Step 1: Write failing metric-matrix tests**

Assert that:

```ts
expect(screen.getByText("来源忠实度")).toBeInTheDocument();
expect(screen.getByText("72")).toBeInTheDocument();
expect(screen.getByText("91")).toBeInTheDocument();
expect(screen.getByText("+19")).toBeInTheDocument();
```

Clicking a metric row must reveal summary, cited event hashes, artifact hashes, confidence, and risks. A single-run report renders a candidate value and a visible “尚未选择兼容基线”, never a fabricated baseline.

- [x] **Step 2: Run RED tests**

```bash
cd frontend
npx vitest run \
  src/features/evaluation/EvaluationMetricMatrix.test.tsx \
  src/features/evaluation/EvaluationCompareView.test.tsx
```

- [x] **Step 3: Implement the report components**

`EvaluationReportHeader` displays Pack business name, status icon/text, case count when known, Beijing timestamp through `shared/time.ts`, and Pack version.

`EvaluationMetricMatrix` uses semantic table markup:

```text
Metric | Baseline | Candidate | Delta
```

Scores include compact progress bars and tabular numerals. Lower-is-better dimensions use a fixed allowlist such as retry/error/duplicate/latency/token; all other scores treat higher as better. If compatibility is unavailable, show the selected run as a single report and keep the baseline selector actionable.

Move verbose Judge summary, evidence and feedback into the selected metric detail/report detail below the matrix. Do not render every dimension as an equal full-width card.

- [x] **Step 4: Run tests and TypeScript**

```bash
cd frontend
npx vitest run \
  src/features/evaluation/EvaluationMetricMatrix.test.tsx \
  src/features/evaluation/EvaluationCompareView.test.tsx \
  src/features/evaluation/EvaluationLabPage.test.tsx
npx tsc --noEmit
```

- [x] **Step 5: Commit**

```bash
git add frontend/src/features/evaluation/EvaluationReportHeader.tsx \
  frontend/src/features/evaluation/EvaluationMetricMatrix.tsx \
  frontend/src/features/evaluation/EvaluationMetricMatrix.test.tsx \
  frontend/src/features/evaluation/EvaluationCompareView.tsx \
  frontend/src/features/evaluation/EvaluationCompareView.test.tsx \
  frontend/src/features/evaluation/JudgeResultPanel.tsx
git commit -m "feat(agent-evaluation): build comparison report surface"
```

### Task 3: Recompose the workbench and quality rail

**Files:**
- Create: `frontend/src/features/evaluation/EvaluationQualityRail.tsx`
- Create: `frontend/src/features/evaluation/EvaluationQualityRail.test.tsx`
- Modify: `frontend/src/features/evaluation/RegressionCasePanel.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationRunList.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationLabPage.tsx`
- Modify: `frontend/src/features/evaluation/EvaluationLabPage.test.tsx`
- Modify: `frontend/src/features/evaluation/evaluation.css`

**Interfaces:**
- Consumes: existing runs, selected run, feedback, regression cases, comparison query, Judge mutation, and trends query.
- Produces: report/trends tabs, explicit baseline and candidate selectors, quality-gate summary rail, evaluation-source strip, regression-case table, and responsive workbench layout.

- [x] **Step 1: Write failing page-composition tests**

The report view must expose:

```ts
screen.getByRole("tab", { name: "评估报告" });
screen.getByRole("tab", { name: "长期趋势" });
screen.getByLabelText("基线评估");
screen.getByLabelText("候选评估");
screen.getByRole("heading", { name: "质量门禁" });
screen.getByRole("heading", { name: "回归案例" });
screen.getByText("确定性规则");
screen.getByText("独立 Judge");
screen.getByText("人工反馈");
```

Assert that trends are absent until the trends tab is selected. Assert that incompatible comparison returns a visible inline explanation while the selected-run report remains usable.

- [x] **Step 2: Run RED tests**

```bash
cd frontend
npx vitest run \
  src/features/evaluation/EvaluationLabPage.test.tsx \
  src/features/evaluation/EvaluationQualityRail.test.tsx
```

- [x] **Step 3: Implement the workbench composition**

Desktop structure:

```text
page header + report/trends tabs
report toolbar: baseline selector | candidate selector | Judge action
main grid:
  report column
    report header
    metric matrix
    evaluation sources
    regression case table
  quality rail
    deterministic gate policy
    Judge advisory policy
    HITL policy
    current result counts
    Pack/model/config summary
```

The run list becomes a compact selector source rather than a permanent third scrolling pane. `RegressionCasePanel` becomes a table/list with source execution, Pack version, privacy state, created time, and row action; its create action remains confirm-gated.

The trends panel renders only in the secondary tab. Preserve Judge launch, feedback submit, raw advanced disclosure and regression-case creation.

- [x] **Step 4: Implement responsive behavior**

- 1440: report + 320px rail, one viewport-height workbench.
- 1024: report + 280px rail; matrix remains readable and secondary summaries compact.
- 768: rail moves below report; report toolbar wraps without hiding selectors.
- 390: one column, selectors and primary action full width, metric matrix becomes stacked metric rows with baseline/candidate/delta labels, no page-level horizontal overflow.

- [x] **Step 5: Run focused frontend validation**

```bash
cd frontend
npx vitest run \
  src/features/evaluation/EvaluationLabPage.test.tsx \
  src/features/evaluation/EvaluationCompareView.test.tsx \
  src/features/evaluation/EvaluationMetricMatrix.test.tsx \
  src/features/evaluation/EvaluationQualityRail.test.tsx \
  src/features/evaluation/EvaluationTrendsPanel.test.tsx
npx tsc --noEmit
npm run build
```

- [x] **Step 6: Commit**

```bash
git add frontend/src/features/evaluation
git commit -m "feat(agent-evaluation): redesign quality evaluation workbench"
```

### Task 4: Visual QA and acceptance

**Files:**
- Update: `design-qa.md`
- Update local only: `docs/verification/agent-observability-and-quality-workbench.md`

**Interfaces:**
- Consumes: approved reference, production page, real development evaluation data.
- Produces: same-state 1440 reference/implementation comparison, four-width overflow evidence, interaction evidence, and a passing design QA report.

- [x] **Step 1: Start the isolated development backend and frontend**

Use the documented development commands and development app-data path. Do not start the main-worktree backend on the feature ports.

- [x] **Step 2: Capture and compare 1440 report state**

Open a real completed evaluation. Compare:

- report hierarchy and whitespace;
- baseline/candidate metric readability;
- quality-gate rail prominence;
- evaluation-source strip;
- regression-case table;
- absence of raw UUIDs as primary labels.

Record P0/P1/P2/P3 findings in `design-qa.md`.

- [x] **Step 3: Fix all P0/P1/P2 findings**

Repeat capture and comparison until `design-qa.md` states:

```text
final result: passed
```

- [x] **Step 4: Verify interactions**

Check baseline/candidate selection, compatible comparison, incompatible comparison explanation, report/trends tabs, Judge launch availability, feedback submit, regression-case confirmation, and advanced raw disclosure.

- [x] **Step 5: Verify 390/768/1024/1440**

For `/agents/evaluations`, record `scrollWidth`, `clientWidth`, primary action reachability, and report/rail order at each width. All widths must have no page-level horizontal overflow.

- [x] **Step 6: Run final affected regression**

```bash
cd frontend
npx vitest run src/features/evaluation
npx tsc --noEmit
npm run build

cd ..
git diff --check
```

- [x] **Step 7: Commit QA corrections**

Commit only tracked product/design files:

```bash
git add frontend/src/features/evaluation design-qa.md \
  docs/superpowers/plans/2026-07-30-quality-evaluation-lab-visual-redesign.md
git commit -m "fix(agent-evaluation): align quality lab with approved design"
```
