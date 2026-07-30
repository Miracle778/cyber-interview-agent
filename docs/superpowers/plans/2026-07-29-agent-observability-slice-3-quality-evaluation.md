# Agent Observability Slice 3 Quality Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned role-specific Eval Packs, isolated manual/automatic Judge runs, human feedback, reusable regression cases, and version comparison without allowing evaluation to mutate product data.

**Architecture:** Eval Packs live in code/Git and declare dimensions, deterministic rules, Judge prompt/contract, and version. An `EvaluationRuntime` receives a frozen execution snapshot and exposes no domain write tools. Deterministic checks may block a regression gate; LLM Judge results remain advisory and can request human review. Evaluation records live in dedicated runtime tables and reference trace/event hashes.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, existing model registry/resolver, LangChain ToolStrategy, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- Slices 1 and 2 must be complete.
- The Judge is not the business Agent and does not perform free-form self-reflection.
- Judge output cannot update questions, profile, knowledge, job targets, review mastery, or business execution status.
- Normal mode may manually trigger Judge and see summary; advanced mode is required for raw Judge input/output.
- Evaluation uses frozen trace/artifact hashes, not mutable live domain reconstruction.
- No arbitrary Prompt editor in v1.
- No cost display.

---

### Task 1: Define Eval Pack and Judge result contracts

**Files:**
- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/contracts.py`
- Create: `backend/app/evaluation/registry.py`
- Create: `backend/app/evaluation/packs/question_curation.py`
- Create: `backend/app/evaluation/packs/review.py`
- Create: `backend/app/evaluation/packs/profile.py`
- Create: `backend/app/evaluation/packs/job_analysis.py`
- Create: `backend/app/evaluation/packs/project_deep_dive.py`
- Create: `backend/tests/test_agent_eval_pack_registry.py`

- [x] Write RED tests for unique pack IDs/versions, all registry `eval_pack_id` references resolving, immutable dimension IDs, and strict Judge output.
- [x] Define `EvalPack`, `EvalDimension`, `DeterministicRule`, `JudgeContract`, and `EvaluationTriggerPolicy`.
- [x] Each pack declares 3–7 user-visible dimensions, required evidence event types, deterministic checks, and a versioned Judge prompt ID.
- [x] `JudgeResult` must contain dimension scores, cited event/artifact hashes, confidence, summary, risks, and `human_review_required`; unknown fields fail.
- [x] Do not include hidden chain-of-thought requirements in any prompt.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_agent_eval_pack_registry.py
```

- [x] Commit:

```bash
git add backend/app/evaluation backend/tests/test_agent_eval_pack_registry.py
git commit -m "feat(agent-evaluation): define versioned role eval packs"
```

### Task 2: Add evaluation persistence and Judge settings

**Files:**
- Create: `backend/app/db/migrations/runtime/039_agent_evaluation.sql`
- Create: `backend/app/db/migrations/app/008_agent_quality_eval_settings.sql`
- Create: `backend/app/evaluation/repository.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/services/workspace_service.py`
- Modify: `backend/app/api/routes_settings.py`
- Create: `backend/tests/test_agent_evaluation_repository.py`
- Create: `backend/tests/test_agent_quality_eval_settings.py`
- Modify: `backend/tests/test_runtime_migrations.py`
- Modify: `backend/tests/test_app_migrations.py`

Runtime tables:

- `agent_eval_runs`;
- `agent_eval_dimension_results`;
- `agent_eval_human_feedback`;
- `agent_eval_regression_cases`;
- `agent_eval_daily_counters`.

App setting fields:

- `enabled`;
- `automatic_sample_percent` default `5`;
- `automatic_daily_cap` default `20`;
- optional `judge_provider_model_id`, falling back to the existing answer-evaluation binding.

- [x] Write migration/repository RED tests for idempotency, frozen hashes, workspace isolation, feedback versioning, case privacy, and daily cap concurrency.
- [x] Write settings RED tests for defaults, bounds, nullable model, restart persistence, and invalid model ID.
- [x] Implement repositories with explicit transactions and immutable completed eval input hashes.
- [x] Do not add a ninth required model role.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_runtime_migrations.py \
  tests/test_app_migrations.py \
  tests/test_agent_evaluation_repository.py \
  tests/test_agent_quality_eval_settings.py
```

- [x] Commit:

```bash
git add backend/app/db/migrations/runtime/039_agent_evaluation.sql \
  backend/app/db/migrations/app/008_agent_quality_eval_settings.sql \
  backend/app/evaluation/repository.py backend/app/schemas/settings.py \
  backend/app/services/workspace_service.py backend/app/api/routes_settings.py \
  backend/tests/test_agent_evaluation_repository.py \
  backend/tests/test_agent_quality_eval_settings.py \
  backend/tests/test_runtime_migrations.py backend/tests/test_app_migrations.py
git commit -m "feat(agent-evaluation): persist eval runs and settings"
```

### Task 3: Build frozen snapshots and isolated Evaluation Runtime

**Files:**
- Create: `backend/app/evaluation/snapshot.py`
- Create: `backend/app/evaluation/runtime.py`
- Create: `backend/app/evaluation/rules.py`
- Create: `backend/tests/test_agent_evaluation_runtime.py`
- Modify: `backend/app/observability/service.py`

- [x] Write RED tests that freeze execution metadata, selected trace events, referenced artifacts, schema/model/tool versions, and hashes.
- [x] Prove a later domain edit does not change an existing snapshot.
- [x] Prove the Evaluation Runtime has no domain service, no write tool, and no generic path/tool access.
- [x] Implement deterministic rules before the model call and record pass/fail evidence.
- [x] Make missing/corrupt trace produce `inconclusive` with explicit evidence gaps, not a false score or business failure.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_agent_evaluation_runtime.py
```

- [x] Commit:

```bash
git add backend/app/evaluation/snapshot.py backend/app/evaluation/runtime.py \
  backend/app/evaluation/rules.py backend/app/observability/service.py \
  backend/tests/test_agent_evaluation_runtime.py
git commit -m "feat(agent-evaluation): isolate frozen execution evaluation"
```

### Task 4: Implement manual and automatic Judge orchestration

**Files:**
- Create: `backend/app/evaluation/judge_agent.py`
- Create: `backend/app/evaluation/service.py`
- Create: `backend/app/evaluation/sampling.py`
- Create: `backend/tests/test_agent_judge_service.py`
- Modify: `backend/app/application/event_projector.py`
- Modify: `backend/app/application/workspace_runtime.py`

- [x] Write RED tests for manual Judge, failed/partial/degraded/rejected/heavily-edited automatic triggers, 5% successful sampling, 20/day cap, duplicate terminal events, cancellation, Provider failure, and no recursive evaluation.
- [x] Resolve Judge model from eval settings, with explicit fallback to answer-evaluation binding.
- [x] Use ToolStrategy/strict structured response and store raw model trace through the existing Trace Writer under a system evaluation operation.
- [x] Run deterministic rules even when Judge Provider fails; mark the Judge portion failed without changing the business run.
- [x] Emit only evaluation-domain events; do not append business messages or update `agent_runs.status`.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_judge_service.py \
  tests/test_agent_evaluation_runtime.py
```

- [x] Commit:

```bash
git add backend/app/evaluation backend/app/application/event_projector.py \
  backend/app/application/workspace_runtime.py \
  backend/tests/test_agent_judge_service.py \
  backend/tests/test_agent_evaluation_runtime.py
git commit -m "feat(agent-evaluation): orchestrate manual and sampled judge runs"
```

### Task 5: Expose evaluation, feedback, and regression APIs

**Files:**
- Create: `backend/app/schemas/evaluation.py`
- Create: `backend/app/api/routes_agent_evaluations.py`
- Create: `backend/tests/test_agent_evaluation_routes.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`

Endpoints:

```text
POST /api/agent-evaluations/runs
GET  /api/agent-evaluations/runs
GET  /api/agent-evaluations/runs/{eval_run_id}
POST /api/agent-evaluations/runs/{eval_run_id}/feedback
POST /api/agent-evaluations/regression-cases
GET  /api/agent-evaluations/regression-cases
POST /api/agent-evaluations/regression-runs
GET  /api/agent-evaluations/comparisons
```

- [x] Write RED tests for workspace isolation, unsupported Agent pack, manual run idempotency, advanced/raw disclosure, feedback history, case redaction, version comparison, and evaluation SSE/status polling.
- [x] Return safe dimension summaries in normal mode and raw Judge trace links only in advanced mode.
- [x] Regression case creation shows exactly which execution fields/bodies will be frozen and requires explicit confirmation.
- [x] Comparison rejects incompatible dimension IDs rather than silently averaging unrelated packs.
- [x] Run:

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_agent_evaluation_routes.py \
  tests/test_agent_judge_service.py
```

- [x] Commit:

```bash
git add backend/app/schemas/evaluation.py \
  backend/app/api/routes_agent_evaluations.py backend/app/api/dependencies.py \
  backend/app/main.py backend/tests/test_agent_evaluation_routes.py
git commit -m "feat(agent-evaluation): expose judge and regression APIs"
```

### Task 6: Build the Quality Evaluation Lab

**Files:**
- Create: `frontend/src/features/evaluation/evaluationTypes.ts`
- Create: `frontend/src/features/evaluation/evaluationApi.ts`
- Create: `frontend/src/features/evaluation/EvaluationLabPage.tsx`
- Create: `frontend/src/features/evaluation/EvaluationRunList.tsx`
- Create: `frontend/src/features/evaluation/JudgeResultPanel.tsx`
- Create: `frontend/src/features/evaluation/RegressionCasePanel.tsx`
- Create: `frontend/src/features/evaluation/EvaluationCompareView.tsx`
- Create: `frontend/src/features/evaluation/evaluation.css`
- Create: `frontend/src/features/evaluation/EvaluationLabPage.test.tsx`
- Create: `frontend/src/features/evaluation/EvaluationCompareView.test.tsx`
- Modify: `frontend/src/features/observability/AgentRunCenterPage.tsx`
- Modify: `frontend/src/features/observability/ExecutionTracePage.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`

- [x] Write RED tests for manual Judge launch, unsupported pack, pending/progress/failure, dimension evidence, human feedback, regression case confirmation, pack version filtering, and comparison incompatibility.
- [x] Add `/agents/evaluations` as a tab within the global Agent area, not a review child page.
- [x] Add “发起 Judge” only when registry/status allow it.
- [x] Build the frozen-case list, dimension score/evidence panel, compare columns, and regression controls from the approved reference.
- [x] Keep raw Judge input/output behind advanced mode; normal users still see score evidence and uncertainty.
- [x] Display no cost field.
- [x] Run:

```bash
cd frontend
npx vitest run \
  src/features/evaluation/EvaluationLabPage.test.tsx \
  src/features/evaluation/EvaluationCompareView.test.tsx \
  src/features/observability/ExecutionTracePage.test.tsx
npx tsc --noEmit
```

- [x] Commit:

```bash
git add frontend/src/features/evaluation \
  frontend/src/features/observability/AgentRunCenterPage.tsx \
  frontend/src/features/observability/ExecutionTracePage.tsx \
  frontend/src/app/layout/AppShell.tsx
git commit -m "feat(agent-evaluation): add quality evaluation lab"
```

### Task 7: Slice 3 browser acceptance and verification

**Files:**
- Update local only: `docs/verification/agent-observability-and-quality-workbench.md`

- [x] Use a disposable workspace with one successful and one failed execution.
- [x] Manually trigger Judge for both; verify failure does not alter the business status.
- [x] Confirm one execution as a regression case, run it against two Eval Pack/model configurations, and compare dimensions.
- [x] Submit human feedback and verify history/reload.
- [x] Enable advanced mode and inspect Judge raw input/output; disable it and verify summaries remain.
- [x] Verify 390/768/1024/1440 and compare with `quality-evaluation-lab-reference.png`.
- [x] Run:

```bash
cd backend
.venv/bin/python -m compileall -q app/evaluation app/api/routes_agent_evaluations.py

cd ../frontend
npx tsc --noEmit

cd ..
git diff --check
```

