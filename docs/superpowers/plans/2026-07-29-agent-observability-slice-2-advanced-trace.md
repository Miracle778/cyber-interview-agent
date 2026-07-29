# Agent Observability Slice 2 Advanced Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a local user deliberately enable advanced diagnostics and inspect the real stored model/tool exchange, copy individual fields with feedback, and export a privacy-labelled execution bundle.

**Architecture:** The advanced switch is stored in the local application database, not in a user or permission model. Trace body APIs resolve event pointers from the workspace index and read exact byte ranges through `WorkspacePathPolicy`. The API never accepts a client filesystem path. Exports are immutable workspace artifacts with a manifest and body-inclusion disclosure.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, workspace path policy, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- Slice 1 must be complete and accepted.
- Advanced mode is a product disclosure boundary, not an authentication system.
- Server enforcement is still required so a stale UI cannot fetch advanced bodies while disabled.
- Secret filtering remains write-time invariant; do not add a “show secrets” switch.
- Do not label any field as model thought unless the Provider explicitly returned that field.
- Body reads are paged/ranged; do not load an unbounded execution into memory.
- No monetary cost display.

---

### Task 1: Persist the local advanced diagnostics preference

**Files:**
- Create: `backend/app/db/migrations/app/007_agent_diagnostics_settings.sql`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/services/workspace_service.py`
- Modify: `backend/app/api/routes_settings.py`
- Create: `backend/tests/test_agent_diagnostics_settings.py`
- Create: `backend/tests/test_app_migrations.py`

The migration creates one local singleton row:

```sql
CREATE TABLE agent_diagnostics_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    advanced_enabled INTEGER NOT NULL DEFAULT 0 CHECK (advanced_enabled IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] Write RED tests for default off, update/read, app restart persistence, and absence of workspace/user ownership fields.
- [ ] Add `GET` and `PUT /api/settings/agent-diagnostics`.
- [ ] Require a boolean body and return the shared settings error envelope.
- [ ] Keep this setting local to the application database; do not add account or permission tables.
- [ ] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_app_migrations.py \
  tests/test_agent_diagnostics_settings.py
```

- [ ] Commit:

```bash
git add backend/app/db/migrations/app/007_agent_diagnostics_settings.sql \
  backend/app/schemas/settings.py backend/app/services/workspace_service.py \
  backend/app/api/routes_settings.py backend/tests/test_app_migrations.py \
  backend/tests/test_agent_diagnostics_settings.py
git commit -m "feat(agent-observability): add local advanced diagnostics setting"
```

### Task 2: Add pointer-based trace body reading

**Files:**
- Create: `backend/app/observability/content_reader.py`
- Modify: `backend/app/observability/repository.py`
- Modify: `backend/app/observability/service.py`
- Modify: `backend/app/schemas/observability.py`
- Modify: `backend/app/api/routes_observability.py`
- Create: `backend/tests/test_trace_content_reader.py`
- Modify: `backend/tests/test_agent_observability_routes.py`

Endpoint:

```text
GET /api/agent-observability/executions/{run_id}/events/{event_id}/content
    ?workspaceId=...&offset=0&limit=65536
```

Response fields include `eventId`, `eventType`, `content`, `contentEncoding`, `offset`, `nextOffset`, `complete`, `sha256`, and `redactionsApplied`.

- [ ] Write RED cases for advanced-off, wrong workspace, missing pointer, symlink/path escape, changed file hash, invalid byte range, UTF-8 boundary, large body pagination, and malformed historical payload.
- [ ] Resolve the event from the index and revalidate `run_id`, workspace, relative path, byte range, row event ID, and payload hash before returning content.
- [ ] Read at most 64 KiB per request and cap total JSON payload display at the product limit in the spec.
- [ ] Return `409 advanced_diagnostics_disabled` when disabled and safe `404` for cross-workspace or missing resources.
- [ ] Surface stored `payload.reasoning` only if present; otherwise return no reasoning field and no placeholder.
- [ ] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_trace_content_reader.py \
  tests/test_agent_observability_routes.py
```

- [ ] Commit:

```bash
git add backend/app/observability/content_reader.py \
  backend/app/observability/repository.py backend/app/observability/service.py \
  backend/app/schemas/observability.py backend/app/api/routes_observability.py \
  backend/tests/test_trace_content_reader.py \
  backend/tests/test_agent_observability_routes.py
git commit -m "feat(agent-observability): expose guarded trace event bodies"
```

### Task 3: Add privacy-labelled export artifacts

**Files:**
- Create: `backend/app/db/migrations/runtime/038_agent_trace_exports.sql`
- Create: `backend/app/observability/export_service.py`
- Modify: `backend/app/observability/repository.py`
- Modify: `backend/app/observability/service.py`
- Modify: `backend/app/schemas/observability.py`
- Modify: `backend/app/api/routes_observability.py`
- Create: `backend/tests/test_agent_trace_export.py`
- Modify: `backend/tests/test_runtime_migrations.py`

Endpoints:

```text
POST /api/agent-observability/executions/{run_id}/exports
GET  /api/agent-observability/exports/{export_id}
```

Request options are `metadataOnly` and `includeStoredBodies`. Bodies require advanced mode. The generated ZIP contains `manifest.json`, `execution.json`, `operations.json`, `events.jsonl`, and optional `bodies/`.

- [ ] Write RED tests for idempotency, advanced-off body export, secret absence, workspace isolation, immutable manifest, and failed partial cleanup.
- [ ] Add `agent_trace_exports` receipt rows with request hash, status, artifact relative path/hash, body inclusion, and error code.
- [ ] Store artifacts under the workspace-controlled diagnostic artifact root with `0600` files and `0700` directories.
- [ ] Manifest must state trace schema versions, generated time, workspace ID, run ID, included/excluded categories, redaction policy, and integrity hashes.
- [ ] Do not include API keys, credentials, application database, runtime database, or unrelated executions.
- [ ] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_runtime_migrations.py \
  tests/test_agent_trace_export.py
```

- [ ] Commit:

```bash
git add backend/app/db/migrations/runtime/038_agent_trace_exports.sql \
  backend/app/observability/export_service.py backend/app/observability \
  backend/app/schemas/observability.py backend/app/api/routes_observability.py \
  backend/tests/test_runtime_migrations.py backend/tests/test_agent_trace_export.py
git commit -m "feat(agent-observability): export trace diagnostic bundles"
```

### Task 4: Add the Settings switch and disclosure

**Files:**
- Create: `frontend/src/features/settings/AgentDiagnosticsSettings.tsx`
- Create: `frontend/src/features/settings/AgentDiagnosticsSettings.test.tsx`
- Modify: `frontend/src/features/settings/settingsApi.ts`
- Modify: `frontend/src/features/settings/SettingsNavigation.tsx`
- Modify: `frontend/src/features/settings/SettingsPage.tsx`

- [ ] Write RED tests for default off, persistence, confirmation disclosure, save failure, and no account/permission wording.
- [ ] Add the switch under existing “诊断” settings, with text explaining that private resume/JD/review content may be shown locally.
- [ ] Require an explicit confirmation before first enable; disabling is immediate.
- [ ] Invalidate observability detail queries after the setting changes.
- [ ] Run:

```bash
cd frontend
npx vitest run \
  src/features/settings/AgentDiagnosticsSettings.test.tsx \
  src/features/settings/SettingsPage.test.tsx
npx tsc --noEmit
```

- [ ] Commit:

```bash
git add frontend/src/features/settings
git commit -m "feat(agent-observability): add advanced diagnostics setting"
```

### Task 5: Build the advanced trace explorer

**Files:**
- Create: `frontend/src/features/observability/TraceEventInspector.tsx`
- Create: `frontend/src/features/observability/TraceJsonViewer.tsx`
- Create: `frontend/src/features/observability/TraceExportDialog.tsx`
- Create: `frontend/src/features/observability/TraceEventInspector.test.tsx`
- Modify: `frontend/src/features/observability/ExecutionTracePage.tsx`
- Modify: `frontend/src/features/observability/observabilityApi.ts`
- Modify: `frontend/src/features/observability/observabilityTypes.ts`
- Modify: `frontend/src/features/observability/observability.css`

- [ ] Write RED tests for disabled disclosure, request/response/tool tabs, paged body loading, copy success/failure toast, JSON parse fallback, reasoning present/absent, export receipt progress, and narrow-screen drawer.
- [ ] Add event selection to the operation tree and lazy-fetch bodies only after user selection.
- [ ] Show request messages, response metadata/structured result/raw payload, tool args/results, model parameters, usage, latency, retry, and errors as separate labelled sections.
- [ ] Reuse the shared copy-feedback behavior; never leave a copy icon without success/failure feedback.
- [ ] Show “Provider 未返回可展示的思维过程” only in the optional reasoning section, not as fabricated content.
- [ ] Render a body-size warning and “继续加载” for paged content.
- [ ] Add export preview showing whether bodies are included and the privacy warning.
- [ ] Run:

```bash
cd frontend
npx vitest run \
  src/features/observability/ExecutionTracePage.test.tsx \
  src/features/observability/TraceEventInspector.test.tsx
npx tsc --noEmit
```

- [ ] Commit:

```bash
git add frontend/src/features/observability
git commit -m "feat(agent-observability): add advanced trace inspection"
```

### Task 6: Slice 2 browser acceptance and verification

**Files:**
- Update local only: `docs/verification/agent-observability-and-quality-workbench.md`

- [ ] With advanced mode off, verify safe metadata remains usable and every body route returns the disabled contract.
- [ ] Enable advanced mode in Settings, reopen one real execution, and inspect one model request, model response, and tool event.
- [ ] Verify copy feedback, paged content, export metadata-only, export with bodies, and ZIP manifest.
- [ ] Verify disabling the switch immediately removes body access without affecting Agent execution.
- [ ] Check 390/768/1024/1440 widths and compare with the advanced trace reference.
- [ ] Run:

```bash
cd backend
.venv/bin/python -m compileall -q app/observability app/api/routes_observability.py \
  app/api/routes_settings.py

cd ../frontend
npx tsc --noEmit

cd ..
git diff --check
```
