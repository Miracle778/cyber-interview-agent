# Agent Observability Slice 1 Run Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global Agent Run Center backed by real `agent_runs`, usage projections, and an incrementally rebuilt JSONL trace index, plus a safe read-only execution detail page.

**Architecture:** JSONL remains authoritative for trace events. `TraceLedgerIndexer` incrementally scans each workspace trace directory into metadata-only SQLite tables outside the writer hot path. `ExecutionSummaryAssembler` merges runtime/domain truth with trace aggregates and registry metadata. FastAPI exposes paged queries and SSE snapshot changes; React renders `/agents` and `/agents/executions/:runId`.

**Tech Stack:** FastAPI, Pydantic v2, SQLite/WAL, JSONL, React 19, TypeScript, TanStack Query, SSE, Vitest, Playwright.

## Global Constraints

- Read the umbrella plan, confirmed spec, and ADR before implementation.
- Do not expose complete prompt/message/tool bodies in Slice 1.
- Do not add retry/cancel buttons until their registry capability and backend command are wired.
- Do not synchronously write SQLite from `AgentTraceWriter.append()`.
- Use Asia/Shanghai display formatting.
- Do not run full regression during individual tasks.

---

### Task 1: Freeze registry and public API contracts

**Files:**
- Create: `backend/app/observability/__init__.py`
- Create: `backend/app/observability/registry.py`
- Create: `backend/app/observability/models.py`
- Create: `backend/app/schemas/observability.py`
- Test: `backend/tests/test_agent_observability_registry.py`
- Modify: `backend/app/application/graph_factory.py`

- [x] Write a failing registry test that discovers every production graph ID exposed by `ProductionGraphFactory` and reports unregistered or duplicate IDs.
- [x] Write a failing schema test for `ExecutionSummaryResource`, `OperationSummaryResource`, `TraceHealth`, page cursors, capabilities, and camelCase serialization.
- [x] Implement `AgentObservabilityRegistration`, immutable capability sets, and explicit registrations for question curation, review, profile ingest/assess/manage, job analysis, and project deep dive.
- [x] Make system-only graph IDs register with `route_template=""` and no business navigation capability.
- [x] Add `assert_registry_complete()` and call it during application construction so new business Agents cannot silently disappear from observability.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_observability_registry.py
```

Expected: new tests pass; removing one registration makes the completeness test fail with its graph ID.

- [x] Commit:

```bash
git add backend/app/observability backend/app/schemas/observability.py \
  backend/app/application/graph_factory.py backend/tests/test_agent_observability_registry.py
git commit -m "feat(agent-observability): register business and system agents"
```

### Task 2: Add the rebuildable trace metadata index

**Files:**
- Create: `backend/app/db/migrations/runtime/037_agent_trace_index.sql`
- Create: `backend/app/observability/repository.py`
- Create: `backend/app/observability/indexer.py`
- Create: `backend/tests/test_trace_ledger_indexer.py`
- Modify: `backend/tests/test_runtime_migrations.py`

The migration creates:

- `agent_trace_files(relative_path PRIMARY KEY, scanned_bytes, last_sequence, file_size, file_mtime_ns, health, updated_at)`;
- `agent_trace_executions(run_id PRIMARY KEY, session_id, first_event_at, last_event_at, trace_health, indexed_event_count)`;
- `agent_trace_operations(operation_id PRIMARY KEY, run_id, parent_operation_id, kind, name, agent_role, status, started_at, finished_at, latency_ms, retry_count, error_code)`;
- `agent_trace_events(event_id PRIMARY KEY, run_id, operation_id, event_type, observed_at, relative_path, byte_start, byte_length, payload_sha256, sequence)`.

- [x] Write migration tests for table/index creation and repeated startup.
- [x] Write indexer RED cases for: complete v2 file; v3 parent/child operations; crash-torn final row; malformed completed row; repeated sync; file growth; file deletion; cross-workspace path; rebuild.
- [x] Implement `TraceLedgerIndexer.sync_workspace()` with short per-file transactions and byte offsets.
- [x] For v2 rows, synthesize deterministic operation IDs from `run_id`, `invocation_id`, and event family; for v3, preserve explicit IDs.
- [x] Treat a missing file as `trace_health="missing"` without deleting its business execution.
- [x] Add `rebuild_workspace()` that truncates only the four trace-index tables and replays JSONL.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_runtime_migrations.py \
  tests/test_trace_ledger_indexer.py
```

Expected: all pass; malformed or torn rows never escape as uncaught exceptions.

- [x] Commit:

```bash
git add backend/app/db/migrations/runtime/037_agent_trace_index.sql \
  backend/app/observability/repository.py backend/app/observability/indexer.py \
  backend/tests/test_runtime_migrations.py backend/tests/test_trace_ledger_indexer.py
git commit -m "feat(agent-observability): index trace ledger metadata"
```

### Task 3: Emit hierarchy-capable schema v3 without breaking v2 reads

**Files:**
- Modify: `backend/app/diagnostics/agent_trace.py`
- Modify: `backend/app/middleware/agent_trace_middleware.py`
- Modify: `backend/tests/test_agent_trace_writer.py`
- Modify: `backend/tests/test_agent_trace_middleware.py`
- Modify: `backend/tests/test_trace_ledger_indexer.py`

- [x] Add RED tests proving new rows contain `operation_id`, `parent_operation_id`, and `operation_kind`, and that legacy v2 fixtures still index.
- [x] Extend `TraceIdentity` with explicit execution/parent operation context while preserving existing constructors through named defaults.
- [x] Make middleware allocate one stable operation ID per model/tool invocation and attach the current Agent operation as parent.
- [x] Keep secret filtering, file permissions, fail-open writes, Shanghai timestamp, and terminal fsync behavior unchanged.
- [x] Confirm no field is named or described as hidden model reasoning.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_trace_writer.py \
  tests/test_agent_trace_middleware.py \
  tests/test_trace_ledger_indexer.py
```

- [x] Commit:

```bash
git add backend/app/diagnostics/agent_trace.py \
  backend/app/middleware/agent_trace_middleware.py \
  backend/tests/test_agent_trace_writer.py \
  backend/tests/test_agent_trace_middleware.py \
  backend/tests/test_trace_ledger_indexer.py
git commit -m "feat(agent-observability): emit hierarchical trace operations"
```

### Task 4: Assemble execution summaries from authoritative sources

**Files:**
- Create: `backend/app/observability/summary.py`
- Create: `backend/app/observability/service.py`
- Create: `backend/tests/test_agent_observability_service.py`
- Modify: `backend/app/application/workspace_runtime.py`

- [x] Write RED fixtures covering completed, running, failed, cancelled, trace-missing, and trace-partial executions.
- [x] Assert top-level count equals `agent_runs` count even when a run contains multiple model/tool operations.
- [x] Assert status/progress/artifacts come from runtime/domain data, usage from `model_invocation_usage` and `agent_context_usage`, and trace health/latency/retries from the trace index.
- [x] Implement cursor pagination, keyword/status/agent/time filters, and `includeSystemAgents`.
- [x] Implement capability derivation as registry capabilities intersected with runtime status.
- [x] Add workspace runtime construction for repository/indexer/service and startup recovery sync.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_observability_service.py
```

- [x] Commit:

```bash
git add backend/app/observability/summary.py backend/app/observability/service.py \
  backend/app/application/workspace_runtime.py \
  backend/tests/test_agent_observability_service.py
git commit -m "feat(agent-observability): assemble execution summaries"
```

### Task 5: Expose paged queries, basic detail, and SSE

**Files:**
- Create: `backend/app/api/routes_observability.py`
- Create: `backend/tests/test_agent_observability_routes.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`

Endpoints:

```text
GET /api/agent-observability/executions
GET /api/agent-observability/executions/{run_id}
GET /api/agent-observability/executions/{run_id}/operations
GET /api/agent-observability/events
```

`/events` is SSE with `workspaceId` and optional `afterEventId`; it emits safe `execution.summary.changed` resources, not raw trace bodies.

- [x] Write route RED tests for workspace isolation, not-found hiding, cursor round-trip, filters, system inclusion, trace-missing fallback, and SSE reconnect.
- [x] Implement route dependencies through the selected `WorkspaceRuntime`; never accept filesystem paths from the client.
- [x] Sync the index before list/detail reads with a debounce guard.
- [x] Emit heartbeat comments and monotonic event IDs; disconnect cleanly without holding a write transaction.
- [x] Return the project error envelope for invalid cursor/filter values.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_observability_routes.py \
  tests/test_agent_routes_v2.py
```

- [x] Commit:

```bash
git add backend/app/api/routes_observability.py backend/app/api/dependencies.py \
  backend/app/main.py backend/tests/test_agent_observability_routes.py
git commit -m "feat(agent-observability): expose execution query and event APIs"
```

### Task 6: Add the global Run Center frontend

**Files:**
- Create: `frontend/src/features/observability/observabilityTypes.ts`
- Create: `frontend/src/features/observability/observabilityApi.ts`
- Create: `frontend/src/features/observability/useObservabilityEvents.ts`
- Create: `frontend/src/features/observability/AgentRunCenterPage.tsx`
- Create: `frontend/src/features/observability/ExecutionList.tsx`
- Create: `frontend/src/features/observability/ExecutionPreview.tsx`
- Create: `frontend/src/features/observability/observability.css`
- Create: `frontend/src/features/observability/AgentRunCenterPage.test.tsx`
- Modify: `frontend/src/app/navigation/navigationItems.ts`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/App.test.tsx`

- [x] Write frontend RED tests for the new “Agent 运行中心” first-level navigation item, list filters, system-agent toggle, loading/empty/error states, live summary update, and capability-derived actions.
- [x] Implement typed API parsing; reject malformed payloads instead of rendering misleading zeroes.
- [x] Build the desktop three-region layout and compact 390/768 layouts from the approved reference image.
- [x] Show business executions in the list and system-operation count inside each row.
- [x] Make “打开业务页面” use the registry-provided route and omit the action when unavailable.
- [x] Use shared Beijing time and `k` token/context formatting.
- [x] Run:

```bash
cd frontend
npx vitest run \
  src/app/App.test.tsx \
  src/features/observability/AgentRunCenterPage.test.tsx
npx tsc --noEmit
```

- [x] Commit:

```bash
git add frontend/src/features/observability frontend/src/app/navigation/navigationItems.ts \
  frontend/src/app/layout/AppShell.tsx frontend/src/app/App.test.tsx
git commit -m "feat(agent-observability): add global run center"
```

### Task 7: Add safe read-only execution detail

**Files:**
- Create: `frontend/src/features/observability/ExecutionTracePage.tsx`
- Create: `frontend/src/features/observability/OperationTree.tsx`
- Create: `frontend/src/features/observability/ExecutionTracePage.test.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/features/observability/observability.css`

- [x] Write RED tests for operation hierarchy, v2-linear fallback, missing trace, partial trace, deep-link refresh, mobile accordion, and absence of raw bodies.
- [x] Implement the execution header, summary metrics, operation tree, safe event metadata, result/artifact links, and explicit `完整内容需开启高级诊断` disclosure.
- [x] Add `/agents/executions/:runId` and preserve Run Center filter state on back navigation.
- [x] Ensure no event body, prompt, tool argument, or provider payload is fetched in Slice 1.
- [x] Run:

```bash
cd frontend
npx vitest run \
  src/features/observability/AgentRunCenterPage.test.tsx \
  src/features/observability/ExecutionTracePage.test.tsx
npx tsc --noEmit
```

- [x] Commit:

```bash
git add frontend/src/features/observability frontend/src/app/layout/AppShell.tsx
git commit -m "feat(agent-observability): add read-only execution trace"
```

### Task 8: Slice 1 browser acceptance and verification

**Files:**
- Update local only: `docs/verification/agent-observability-and-quality-workbench.md`
- Update if implementation diverged: confirmed spec/ADR and this plan

- [x] Seed or reuse one completed, one failed, one running, and one trace-missing execution in a disposable workspace.
- [x] Start the isolated test environment using the documented project command.
- [x] Verify `/agents` at 390, 768, 1024, and 1440; assert `scrollWidth === clientWidth`.
- [x] Open one execution; verify operation hierarchy, Beijing time, token/context `k`, trace-health disclosure, business-page return, and SSE update.
- [x] Compare screenshots with `agent-run-center-reference.png` and `execution-trace-explorer-reference.png`; record intentional differences.
- [x] Run final slice gates:

```bash
cd backend
.venv/bin/python -m compileall -q app/observability app/api/routes_observability.py \
  app/diagnostics/agent_trace.py app/middleware/agent_trace_middleware.py

cd ../frontend
npx tsc --noEmit

cd ..
git diff --check
```

- [x] Commit any formal plan/spec corrections separately:

```bash
git add docs/superpowers/plans docs/superpowers/specs \
  docs/superpowers/architecture-decisions
git commit -m "docs(agent-observability): record slice 1 implementation evidence"
```

## Slice 1 completion evidence

- Product commits: `22cb732`, `85f882b`, `3083c04`, `5edb89f`, `63ef960`, `cbf8312`, `0626133`, `6cd194b`.
- Final backend regression: `86 passed`; required Python compileall completed without output.
- Final frontend regression: `26 passed`; TypeScript completed without diagnostics.
- Browser acceptance used an isolated README Demo workspace with completed, failed, running, partial-trace, and trace-missing executions.
- `/agents` and execution detail both satisfied `scrollWidth === clientWidth` at `390 / 768 / 1024 / 1440`.
- SSE status update, Beijing time, compact Token/context values, hierarchy, safe disclosure, filter return, business navigation, and missing-trace fallback passed.
- Acceptance found one mobile reachability defect: the 390px list hid the preview and therefore had no detail entry. Commit `6cd194b` adds a tested mobile row-level detail link.
- Browser console result: no warnings or errors.
