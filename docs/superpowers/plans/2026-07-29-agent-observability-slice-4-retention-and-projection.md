# Agent Observability Slice 4 Retention and Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workspace trace retention controls, two-phase cleanup with receipts, safe OpenTelemetry projection, index repair tools, and long-term quality trends.

**Architecture:** Full local bodies and rebuildable metadata have separate retention. Cleanup first records a plan and quarantines eligible body files, then finalizes deletion after verification; metadata can remain. External projection sends only allowlisted metadata through the existing OTel infrastructure. Trend aggregates derive from immutable evaluation results.

**Tech Stack:** FastAPI, SQLite, filesystem quarantine, OpenTelemetry OTLP, React 19, TypeScript, pytest, Vitest, Playwright.

## Global Constraints

- Slices 1–3 must be complete.
- Default policy: full bodies 90 days, metadata retained.
- Workspace options: permanent bodies, 90-day bodies, or metadata-only.
- Cleanup must be resumable, idempotent, and auditable.
- External projection never sends prompt/message/tool/provider bodies by default.
- This slice implements OTel/OTLP projection only; there is no Langfuse dependency in the current project. Langfuse is not advertised as shipped.
- Workspace permanent deletion must remove or finalize all observability/evaluation data belonging to that workspace.
- No cost display.

---

### Task 1: Persist retention policies and cleanup receipts

**Files:**
- Create: `backend/app/db/migrations/runtime/040_agent_trace_retention.sql`
- Create: `backend/app/observability/retention.py`
- Modify: `backend/app/observability/repository.py`
- Create: `backend/tests/test_agent_trace_retention.py`
- Modify: `backend/tests/test_runtime_migrations.py`

Tables:

- `agent_trace_retention_policy(workspace_id PRIMARY KEY, body_policy, body_days, metadata_policy, updated_at)`;
- `agent_trace_cleanup_runs`;
- `agent_trace_cleanup_items`;
- `agent_trace_projection_deliveries`.

- [x] Write RED tests for defaults, each policy, invalid days, idempotent plan, repeated finalization, crash recovery, and multiple workspaces.
- [x] Implement policy resolution and a dry-run plan listing files/events/bytes without deleting.
- [x] Eligibility uses event timestamp and protects active/running executions.
- [x] Metadata-only removes body access while preserving execution/operation/event metadata and hashes.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_runtime_migrations.py \
  tests/test_agent_trace_retention.py
```

- [x] Commit:

```bash
git add backend/app/db/migrations/runtime/040_agent_trace_retention.sql \
  backend/app/observability/retention.py backend/app/observability/repository.py \
  backend/tests/test_runtime_migrations.py backend/tests/test_agent_trace_retention.py
git commit -m "feat(agent-observability): persist trace retention policies"
```

### Task 2: Implement two-phase cleanup and workspace deletion integration

**Files:**
- Create: `backend/app/observability/cleanup.py`
- Create: `backend/tests/test_agent_trace_cleanup.py`
- Modify: `backend/app/services/workspace_service.py`
- Modify: `backend/app/application/workspace_runtime.py`

- [x] Write RED tests for plan → quarantine → verify → finalize, crash after quarantine, hash mismatch, active run, symlink denial, partial failure, and permanent workspace deletion.
- [x] Move eligible body files into a private workspace quarantine directory, record old/new path and hash, then finalize only after the index/receipt transaction commits.
- [x] On restart, resume incomplete cleanup from receipts; never infer completion from file absence alone.
- [x] Update indexed events to `body_state="deleted"` only after finalization; keep timestamp/type/hash.
- [x] Ensure workspace permanent deletion removes trace, quarantine, exports, eval cases/results, and their receipts or reports a safe retryable failure.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_trace_cleanup.py \
  tests/test_agent_trace_retention.py
```

- [x] Commit:

```bash
git add backend/app/observability/cleanup.py \
  backend/app/services/workspace_service.py \
  backend/app/application/workspace_runtime.py \
  backend/tests/test_agent_trace_cleanup.py
git commit -m "feat(agent-observability): clean trace bodies with receipts"
```

### Task 3: Add rebuild and consistency maintenance commands

**Files:**
- Create: `scripts/rebuild_agent_trace_index.py`
- Create: `scripts/check_agent_trace_consistency.py`
- Create: `backend/tests/test_agent_trace_maintenance_scripts.py`
- Modify: `README.md`

- [x] Write RED tests using a disposable workspace for index loss, corrupt row, missing file, stale pointer, and repairable offset.
- [x] `check_agent_trace_consistency.py` is read-only by default and returns non-zero for unreconciled errors.
- [x] `rebuild_agent_trace_index.py` requires explicit workspace root, prints the resolved target, rebuilds only trace-index tables, and reports counts/gaps.
- [x] Neither script accepts `/`, `$HOME`, or an unresolved broad target.
- [x] Document exact commands and recovery boundaries in README diagnostics.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_agent_trace_maintenance_scripts.py
```

- [x] Commit:

```bash
git add scripts/rebuild_agent_trace_index.py \
  scripts/check_agent_trace_consistency.py \
  backend/tests/test_agent_trace_maintenance_scripts.py README.md
git commit -m "feat(agent-observability): add trace consistency maintenance"
```

### Task 4: Add safe OTel/OTLP metadata projection

**Files:**
- Create: `backend/app/observability/projection.py`
- Create: `backend/tests/test_agent_trace_projection.py`
- Modify: `backend/app/infrastructure/observability.py`
- Modify: `backend/app/application/workspace_runtime.py`

Allowlisted projection fields:

- workspace/run/session hashed or configured identifiers;
- graph ID, Agent role, operation kind/name;
- status, start/end/latency, token/context aggregates, retry/error code;
- Eval Pack/result dimension IDs and numeric scores;
- no prompt, message, tool arguments/results, provider raw body, resume/JD/review text, or filesystem paths.

- [x] Write RED tests that place secrets and private bodies in local trace and prove none reach the fake exporter.
- [x] Write retry/idempotency tests using `agent_trace_projection_deliveries`.
- [x] Implement a projection interface and OTel adapter using the existing OTLP dependency/configuration.
- [x] Projection failure is fail-open and recorded; it cannot fail or delay the business execution.
- [x] Do not add a Langfuse SDK or UI claim in this slice.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_trace_projection.py
```

- [x] Commit:

```bash
git add backend/app/observability/projection.py \
  backend/app/infrastructure/observability.py \
  backend/app/application/workspace_runtime.py \
  backend/tests/test_agent_trace_projection.py
git commit -m "feat(agent-observability): project safe trace metadata to otel"
```

### Task 5: Expose retention, cleanup, and trend APIs

**Files:**
- Create: `backend/app/evaluation/trends.py`
- Modify: `backend/app/schemas/observability.py`
- Modify: `backend/app/schemas/evaluation.py`
- Modify: `backend/app/api/routes_observability.py`
- Modify: `backend/app/api/routes_agent_evaluations.py`
- Create: `backend/tests/test_agent_observability_retention_routes.py`
- Create: `backend/tests/test_agent_evaluation_trends.py`

Endpoints:

```text
GET  /api/agent-observability/retention
PUT  /api/agent-observability/retention
POST /api/agent-observability/cleanup-plans
POST /api/agent-observability/cleanup-plans/{cleanup_id}/confirm
GET  /api/agent-observability/cleanup-runs/{cleanup_id}
GET  /api/agent-evaluations/trends
```

- [x] Write RED tests for dry-run counts, confirmation idempotency, active-run exclusion, body-state disclosure, trend filters, pack-version separation, and no-cost response.
- [x] Trend queries aggregate immutable eval dimension results by Agent, pack version, model ID, prompt/schema/tool version, and time bucket.
- [x] Never average incompatible pack versions into one series.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_observability_retention_routes.py \
  tests/test_agent_evaluation_trends.py
```

- [x] Commit:

```bash
git add backend/app/evaluation/trends.py backend/app/schemas \
  backend/app/api/routes_observability.py \
  backend/app/api/routes_agent_evaluations.py \
  backend/tests/test_agent_observability_retention_routes.py \
  backend/tests/test_agent_evaluation_trends.py
git commit -m "feat(agent-observability): expose retention and quality trends"
```

### Task 6: Add retention settings and long-term trends UI

**Files:**
- Create: `frontend/src/features/settings/AgentTraceRetentionSettings.tsx`
- Create: `frontend/src/features/settings/AgentTraceRetentionSettings.test.tsx`
- Create: `frontend/src/features/evaluation/EvaluationTrendsPanel.tsx`
- Create: `frontend/src/features/evaluation/EvaluationTrendsPanel.test.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`
- Modify: `frontend/src/features/settings/settingsApi.ts`
- Modify: `frontend/src/features/evaluation/EvaluationLabPage.tsx`
- Modify: `frontend/src/features/evaluation/evaluationApi.ts`
- Modify: `frontend/src/features/evaluation/evaluationTypes.ts`

- [x] Write RED tests for the three retention choices, dry-run preview, explicit cleanup confirmation, partial failure, body-deleted disclosure, pack-version filters, and no cost.
- [x] Add retention controls under Settings → 诊断 with clear consequences and default 90 days.
- [x] Show cleanup counts/bytes and protected active executions before confirmation.
- [x] Add trend charts/tables for success, deterministic rule failure, Judge score, human-review rate, and latency/token/context; omit price/cost.
- [x] Use accessible table fallback for charts and preserve 390px usability.
- [x] Run:

```bash
cd frontend
npx vitest run \
  src/features/settings/AgentTraceRetentionSettings.test.tsx \
  src/features/evaluation/EvaluationTrendsPanel.test.tsx \
  src/features/evaluation/EvaluationLabPage.test.tsx
npx tsc --noEmit
```

- [x] Commit:

```bash
git add frontend/src/features/settings frontend/src/features/evaluation
git commit -m "feat(agent-observability): add retention controls and trends"
```

### Task 7: Performance, recovery, and final acceptance

**Files:**
- Create: `backend/tests/test_agent_observability_performance.py`
- Update local only: `docs/verification/agent-observability-and-quality-workbench.md`
- Update local only: `docs/learning/agent-observability-and-quality-workbench/`

- [x] Generate a disposable workspace with 10,000 executions and at least 1,000 events in a single execution.
- [x] Verify paged Run Center query and operation tree stay within the spec budgets on the development machine; record measured values, not universal promises.
- [x] Interrupt index sync and cleanup mid-operation, restart, and verify deterministic recovery.
- [x] Run one complete browser acceptance pass across Run Center, advanced trace, manual Judge, regression compare, retention dry-run, and trends.
- [x] Re-run only affected scenarios after fixes.
- [x] Run final gates:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_agent_observability_performance.py
.venv/bin/python -m compileall -q app/observability app/evaluation \
  app/api/routes_observability.py app/api/routes_agent_evaluations.py

cd ../frontend
npx tsc --noEmit

cd ..
git diff --check
python3 scripts/check_stage_docs.py \
  --verification docs/verification/agent-observability-and-quality-workbench.md \
  --learning docs/learning/agent-observability-and-quality-workbench/ \
  --plan docs/superpowers/plans/2026-07-29-agent-observability-and-quality-workbench.md
```

- [x] Commit formal documentation corrections only after final evidence is refreshed:

```bash
git add docs/superpowers/plans docs/superpowers/specs \
  docs/superpowers/architecture-decisions README.md
git commit -m "docs(agent-observability): close quality workbench delivery plan"
```

