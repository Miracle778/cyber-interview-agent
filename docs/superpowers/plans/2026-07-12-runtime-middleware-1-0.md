# Runtime Middleware 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real middleware pipeline consumed by `review.single`, providing persisted model usage, context compression, automatic titles, loop protection, and a persistent-HITL adapter while defining—but not implementing—Todo candidates.

**Architecture:** Handwritten `StateGraph` workflows keep their domain topology. `RunManager` wraps `GraphBuildContext` model/tool/action ports with Guard → Invocation → Post-processing middleware; an OpenTelemetry `ObservabilitySink` exports safe spans to local Langfuse without coupling business code to the backend.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite/WAL, LangGraph, LangChain `AgentMiddleware`, OpenTelemetry SDK/OTLP HTTP, local Langfuse v3 Docker Compose, React 19, TypeScript, pytest, Vitest, Playwright.

## How to Execute This Plan

This index is the startup input. Detailed TDD code, exact commands, expected failures, and commit scopes live in:

- `docs/superpowers/plans/runtime-middleware-1-0/task-details.md`

At the start of a task, locate only that task with `rg -n '^### Task'` and read from its heading to the next Task heading. Do not read the entire detail file on every resume.

## Global Constraints

- Do not rewrite `review.single`, knowledge publication, or the existing `HitlService` state machine.
- Do not implement R2 multi-question behavior, Todo extraction, Todo Service/persistence/UI, or unrelated candidate middleware.
- Never persist API keys, raw provider errors, full sensitive prompts, or unredacted tool arguments.
- Provider-native usage wins; fallback estimates set `estimated=true`; streams record usage once.
- Title/summary failures are warning events and cannot fail an otherwise successful business run.
- Hard guard codes are limited to `loop_detected`, `no_progress`, `step_budget_exceeded`, `token_budget_exceeded`, `run_timeout`.
- `knowledge.publish` remains an explicit Graph node/handler; HITL middleware handles ordinary tools only.
- Middleware order is Guard → Invocation → Post-processing and each layer is independently switchable.
- Business code depends only on `ObservabilitySink`; local Langfuse/OTLP failures are fail-open.
- Trace content is metadata-only by default; prompts, responses, files and tool arguments require explicit local redacted-content opt-in.
- One Agent owns the slice. Use targeted tests in Tasks 1–3, one cross-layer integration run, one final regression/build, and one complete browser pass.
- Do not modify or commit `docs/my_idea.md`.

## Deliverable Map

| Area | Files | Responsibility |
|---|---|---|
| Persistence | `006_runtime_middleware.sql`, middleware repository | Idempotent usage, guard observations, aggregates |
| Contracts | `middleware/types.py`, `pipeline.py` | Context, config, invocation, usage, TodoCandidate, ordered hooks |
| Observability | `observability.py`, `infra/observability/langfuse/` | No-op/OTel sinks and reproducible local Langfuse |
| Invocation | `telemetry.py`, provider adapters/gateway | Native/estimated token usage, stream finalization, safe errors |
| Context | `context_budget.py`, session repository | Budget, summary, protected/recent messages, hard limit |
| Post-process | `session_title.py` | One-shot title with compare-and-set |
| Guard | `loop_guard.py`, `RunManager` | Repetition, no progress, runtime/token/step budgets, restart recovery |
| HITL | `hitl_adapter.py`, `langchain_adapter.py` | Ordinary tool approval and future official AgentMiddleware bridge |
| Product | Agent schema/service/types, `ReviewPage` | Usage, summary and safe guard state |
| Acceptance | backend integration, Playwright, verification/learning | Prove real `review.single` consumption and preserved publication |

## Task 1: Pipeline contracts and durable records

**Detailed section:** `task-details.md` → `### Task 1`

**Produces:**

- `MiddlewareContext`, `MiddlewareLayer`, `MiddlewareConfig`.
- `ModelInvocation`, `ModelUsage`, `ToolInvocation`, `TodoCandidate`.
- `RuntimeGuardError`, `RuntimeMiddleware`, `RuntimeMiddlewarePipeline`.
- `TraceContext`, `ObservabilitySink`, `NoopObservabilitySink`, local Langfuse Compose.
- `RuntimeMiddlewareRepository` usage/guard APIs.
- Graph-level middleware config with safe defaults.

**Scope:**

- [ ] Add RED migration/repository/pipeline tests.
- [ ] Add migration 006 with unique `(run_id, operation_key)` usage writes and persistent guard sequences.
- [ ] Add ordered, switchable pipeline and stable dataclasses/protocols.
- [ ] Add local-only pinned Langfuse Compose, `.env.example`, health/start/stop documentation.
- [ ] Add No-op sink and trace context; prove observability failure cannot affect business hooks.
- [ ] Add title compare-and-set and session summary repository methods.
- [ ] Run only runtime database/repository/pipeline tests.
- [ ] Commit `feat(runtime): add middleware pipeline foundation`.

**Gate:** Existing graphs compile unchanged; duplicate usage counts once; guard state survives reopening; No-op works without Docker; local Langfuse health is reproducible.

## Task 2: Model telemetry and context budget

**Detailed section:** `task-details.md` → `### Task 2`

**Produces:**

- `ProviderUsage`, `ProviderModelResult[T]`, `ProviderStreamChunk`.
- Provider-native usage extraction for OpenAI/Anthropic-compatible adapters.
- Deterministic `estimated=true` fallback.
- `ModelUsageMiddleware` and `ContextBudgetMiddleware`.
- OTLP/HTTP exporter and model spans visible in local Langfuse.
- `_BoundModelInvoker` routed through the pipeline.

**Scope:**

- [ ] Add RED native/fallback/stream/compaction tests.
- [ ] Preserve raw usage metadata through provider envelopes without exposing raw responses.
- [ ] Record one operation for structured calls and one for a complete stream.
- [ ] Start `agent.run`/model spans and export safe token/model/latency attributes to local Langfuse.
- [ ] Add soft compaction and hard `token_budget_exceeded`; protect system/recent/domain references.
- [ ] Mark summary/title calls with non-business `purpose` to prevent recursive middleware.
- [ ] Run chat gateway, both adapters, RunManager and new middleware tests.
- [ ] Commit `feat(runtime): meter model usage and context budgets`.

**Gate:** Native/estimated usage is distinguishable; streams are not double-counted; two `review.single` model spans appear locally; stopping Langfuse does not fail the Agent.

## Task 3: Titles, loop guard, API and Review UI

**Detailed section:** `task-details.md` → `### Task 3`

**Produces:**

- One-shot `SessionTitleMiddleware` with title CAS.
- Persistent `LoopGuardMiddleware` and safe RunManager failure mapping.
- LangGraph `recursion_limit` mapped to `step_budget_exceeded`.
- Spans for title, compression, loop guard and tools, correlated to the run trace.
- Session `summary`, `usage`, `latestGuardWarning` resources.
- Compact Review UI metadata and guard recovery advice.

**Scope:**

- [ ] Add RED title, guard/restart, API and frontend tests.
- [ ] Generate title only after a persisted user/assistant pair and never overwrite user edits.
- [ ] Persist safe hashes/counters, warn once at soft threshold, fail at hard threshold.
- [ ] Restore counters on resume and enforce maximum graph steps/time/token/model/tool calls.
- [ ] Add safe spans for post-processing/guard/tool hooks without prompt or argument bodies.
- [ ] Extend API/TypeScript resources and render usage/summary/warning without a new page.
- [ ] Run targeted backend/frontend tests and TypeScript.
- [ ] Commit `feat(runtime): add title and loop guard middleware`.

**Gate:** A restart cannot reset guard budgets; warning payloads contain no fingerprints/arguments; title/summary failure leaves the business run successful.

## Task 4: HITL bridge and real-Agent acceptance

**Detailed section:** `task-details.md` → `### Task 4`

**Produces:**

- `ToolApprovalPolicy`, `PersistentHitlMiddleware`.
- `LangChainRuntimeMiddlewareAdapter(AgentMiddleware)` for future `create_agent` workflows.
- HITL/publication spans and linked restart trace segments.
- Real `review.single` integration and browser acceptance.
- Final verification guide and seven-file ownership pack.

**Scope:**

- [ ] Add RED ordinary-tool approval, official adapter and explicit-publication boundary tests.
- [ ] Reuse current action/version/receipt/resume semantics with deterministic tool action keys.
- [ ] Prove `knowledge.publish` still comes from the explicit review Graph.
- [ ] Prove usage while waiting; approve; then prove generated title, publication, restart persistence and middleware-off behavior.
- [ ] Prove HITL/resume/publication spans, restart links by stable run ID, metadata-only defaults and exporter fail-open.
- [ ] Run one cross-layer backend subset.
- [ ] Run one Playwright pass covering desktop/mobile, refresh/restart, loop error and console cleanliness.
- [ ] Run final backend/frontend regression and build once.
- [ ] Finalize verification/learning docs and run `check_stage_docs.py`.
- [ ] Commit `feat(runtime): validate middleware with review agent`.

**Gate:** Browser and local Langfuse evidence exists; exact final test counts come from the last commands; Todo extraction/UI and R2 behavior remain absent.

## Verification Budget

- Backend full regression: at most 2; target 1 final run unless cross-layer risk requires the earlier run.
- Frontend full regression/build: at most 2; target 1 final run.
- Complete browser acceptance: 1; after a fix rerun only the affected spec.
- Agent handoff: 0.
- Same unchanged failure: stop after 2 and diagnose.
- Tool output: default under approximately 4,000 tokens.
- Task handoff: no more than 10 lines.

## Final Commands

```bash
cd backend
python3 -m pytest -q --tb=short
cd ../frontend
./node_modules/.bin/vitest run --reporter=dot
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/vite build
cd ..
python3 scripts/check_stage_docs.py \
  --verification docs/verification/runtime-middleware-1-0.md \
  --learning docs/learning/runtime-middleware-1-0/ \
  --plan docs/superpowers/plans/2026-07-12-runtime-middleware-1-0.md
```

## Completion Boundary

Middleware 1.0 is complete only when `review.single` visibly consumes usage/title/summary/guard state, ordinary tool HITL uses the adapter, explicit knowledge publication is unchanged, restart evidence passes, and local verification/learning documents are synchronized after merge. Completion does not mean R2, Todo extraction, Todo Service, or the full candidate middleware catalog is implemented.
