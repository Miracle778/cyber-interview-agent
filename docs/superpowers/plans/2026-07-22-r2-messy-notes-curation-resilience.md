# R2 Messy-Notes Curation Resilience Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with a review checkpoint after every commit. Use `superpowers:subagent-driven-development` for the recommended execution mode, or execute inline when one Agent owns the slice end-to-end.

**Goal:** Make question curation reliably process incomplete, irregular notes with per-seed partial success, bounded fallback, explicit answer provenance, strict publication gates, and migration-safe recovery of all existing completed work.

**Architecture:** Preserve the current coverage-first discovery pipeline and legacy Work Items as immutable audit evidence. Add one durable Seed Task per discovered question, use batches of at most three Seed Tasks per Provider invocation, normalize Provider observations into application-owned candidates, and commit outcomes independently per seed. Content defects degrade or skip only one seed; only infrastructure, security, persistence, or authoritative-state corruption may fail the Batch.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, asyncio, LangGraph/LangChain, React 19, TypeScript, TanStack Query, Vitest, Testing Library, CSS semantic tokens.

## Global Constraints

- Work only in `/Users/miracle778/Project/cyber-interview-agent-new/.worktrees/r2-complete-review-agent` on `feature/review-agent-workspace`.
- Do not modify or commit `docs/my_idea.md`.
- Preserve the untracked `curation-failure-handoff.md` and `docs/superpowers/architecture-decisions/2026-07-21-question-curation-failure-incident-review.md`; never stage them accidentally.
- Treat `docs/superpowers/specs/2026-07-22-r2-messy-notes-curation-resilience-design.md` as the accepted source of truth.
- Discovery must retain exactly-once coverage. Deterministic rules may identify question/evidence boundaries, but may not invent answers.
- Provider observations are untrusted input. Evidence refs, seed identity, retry limits, state transitions, candidate quality, and publication eligibility belong to the application.
- The durable recovery unit is one Seed Task. A Provider invocation may contain at most 3 seeds, with at most 3 concurrent invocations.
- Each Seed Task receives at most 2 automatic Provider calls: one batched attempt and, only when needed, one single-seed fallback.
- `completed`, `degraded`, and `skipped` are automatic terminal states. Completed/degraded output is immutable and never automatically replayed.
- Content-shape or content-completeness defects never fail the Batch. Red failure UI remains reserved for infrastructure, persistence, authoritative evidence corruption, security, or unreconcilable state.
- Existing Work Items, candidates, drafts, Trace rows, and the current Batch are additive-migration inputs; do not delete or rewrite them.
- Current Batch `907129b5-0a8c-47cb-b8a0-be42b73459a9` must retain 80 completed discovery units and 22 completed enrichment outputs without Provider replay.
- No real Provider call occurs during migration or automated acceptance. A real Provider run requires the user to explicitly trigger a concrete material.
- Update `docs/verification/r2-complete-review-agent.md` locally after every Task; do not stage `docs/verification/`.
- Use focused tests per Task. Run one cross-layer regression after integration and one final regression only if acceptance fixes make it necessary.
- Before claiming the slice ready for manual verification, run the repository documentation gate from `AGENTS.md`.

---

## File and Interface Map

### Persistence and state ownership

- Create `backend/app/db/migrations/runtime/026_curation_seed_tasks.sql`.
- Modify `backend/app/review/models.py`.
- Modify `backend/app/review/repository.py`.
- Add `review_curation_seed_tasks` as the durable per-question recovery ledger.
- Add `review_curation_seed_retry_receipts` for one-shot, idempotent manual retries.
- Add Seed Task linkage and quality columns to `review_question_candidates`, backfilling old candidates as `unknown` and `needs_review=1`.

### Source intake and discovery

- Modify `backend/app/services/document_ingestion.py` to return safe extraction classifications.
- Create `backend/app/review/curation_sources.py` for curation-specific source projection and warning codes.
- Modify `backend/app/review/application.py` to continue when at least one source is usable and to finish normally when none is usable.
- Retain `backend/app/review/curation_sections.py` and `backend/app/review/curation_planner.py` coverage invariants.

### Provider boundary and quality normalization

- Modify `backend/app/agents/question_curation_contracts.py` for permissive Provider observations.
- Create `backend/app/agents/question_curation_normalization.py` for deterministic association, repair, provenance, and quality classification.
- Modify `backend/app/agents/prompts/question_curation_prompts.py` to include `seed_key`, authoritative refs, and split answer fields.
- Modify `backend/app/agents/question_curation_agent.py` so discovery, enrichment, and revision all return Provider observations to the same normalizer.

### Reconciliation, scheduler, and Graph

- Create `backend/app/review/curation_seed_reconciliation.py`.
- Modify `backend/app/review/curation_scheduler.py` to aggregate invocation-level transport failures without conflating per-seed content outcomes.
- Modify `backend/app/graphs/question_curation.py` to plan/reconcile Seed Tasks, invoke in groups of three, persist each seed independently, and run single-seed fallbacks.
- Modify `backend/app/application/execution_service.py` only where terminal projection currently assumes any worker exception means Batch failure.

### API, resources, events, and publication

- Modify `backend/app/schemas/review.py`.
- Modify `backend/app/api/routes_review.py`.
- Modify `backend/app/review/application.py`.
- Modify `backend/app/application/event_projector.py` and `backend/app/application/session_service.py`.
- Add one-shot manual retry endpoint, seed/quality resource projections, safe `curation.seed.changed` events, and explicit AI-supplement publication confirmation.

### Frontend

- Modify `frontend/src/features/review/reviewTypes.ts` and `frontend/src/features/review/reviewApi.ts`.
- Modify `frontend/src/features/review/QuestionCatalog.tsx`.
- Modify `frontend/src/features/review/CurationRuntimePanel.tsx` and `frontend/src/features/review/CurationProvisionalList.tsx`.
- Modify `frontend/src/features/review/CurationArtifactCard.tsx`, `frontend/src/features/review/CurationArtifactDetail.tsx`, and `frontend/src/features/review/QuestionDetailPanel.tsx`.
- Modify `frontend/src/features/agent/useAgentEvents.ts` and `frontend/src/app/global.css`.

---

### Task 1: Add the Durable Seed Task and Manual-Retry State Machines

**Files:**

- Create: `backend/app/db/migrations/runtime/026_curation_seed_tasks.sql`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Create: `backend/tests/test_curation_seed_tasks.py`

**Interfaces:**

```python
SeedTaskStatus = Literal[
    "pending", "running", "completed", "degraded",
    "retryable", "interrupted", "skipped",
]

plan_curation_seed_task(
    *, batch_id: str, discovery_work_item_id: str, seed_ordinal: int,
    question_text: str, primary_source_ref: str,
    source_refs: tuple[str, ...], input_digest: str,
) -> CurationSeedTaskRecord

claim_curation_seed_tasks(
    batch_id: str, *, statuses: tuple[str, ...], limit: int,
) -> tuple[CurationSeedTaskRecord, ...]

complete_curation_seed_task(
    seed_task_id: str, *, expected_version: int,
    status: Literal["completed", "degraded"], candidate: dict[str, object],
    answer_basis: str, material_support: str, needs_review: bool,
    normalization_issues: tuple[str, ...],
) -> CurationSeedTaskRecord

mark_curation_seed_retryable(
    seed_task_id: str, *, expected_version: int, error_code: str,
    normalization_issues: tuple[str, ...],
) -> CurationSeedTaskRecord

skip_curation_seed_task(
    seed_task_id: str, *, expected_version: int, error_code: str,
    normalization_issues: tuple[str, ...],
) -> CurationSeedTaskRecord

begin_curation_seed_retry(
    seed_task_id: str, *, expected_version: int, idempotency_key: str,
    request_digest: str, execution_id: str,
) -> tuple[CurationSeedRetryReceiptRecord, bool]

claim_manual_curation_seed_retry(
    receipt_id: str, *, expected_seed_version: int,
) -> CurationSeedTaskRecord
```

- [ ] **Step 1: Write migration and repository tests first**

Extend migration tests to require version 26, both new tables, all indexes/checks, candidate quality columns, old-row backfill, and `PRAGMA foreign_key_check == []`.

In `test_curation_seed_tasks.py`, prove:

- `seed_key = sha256(batch_id + discovery_work_item_id + seed_ordinal + primary_source_ref)` is stable and unique inside one Batch;
- repeated planning with the same identity returns the same row and rejects changed immutable input;
- only pending/retryable/interrupted may be claimed under the defined transition rules;
- automatic attempt count cannot exceed 2;
- completed/degraded candidate JSON and quality fields are immutable;
- interruption returns running tasks to resumable state without incrementing a new attempt;
- skipped is not automatically claimable;
- one manual retry receipt is idempotent for the same key/digest and rejects key reuse with a changed request;
- stale `expected_version` raises `ReviewConflictError`;
- repository queries never expose Provider exception text as `last_error_code`.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_runtime_migrations.py tests/test_curation_seed_tasks.py
```

Expected: migration 26 and Seed Task symbols are absent.

- [ ] **Step 3: Implement additive migration 026**

Create `review_curation_seed_tasks` with the accepted fields and checks. Add `discovery_work_item_id` because stable identity and legacy reconciliation require an authoritative origin. Add a unique `(batch_id, seed_key)` index and scheduling indexes on `(batch_id, status, seed_ordinal)`.

Create `review_curation_seed_retry_receipts` with `seed_task_id`, `idempotency_key`, `request_digest`, `execution_id`, `result_status`, timestamps, and unique `(seed_task_id, idempotency_key)`.

Add these candidate columns:

```sql
seed_task_id TEXT REFERENCES review_curation_seed_tasks(id) ON DELETE SET NULL,
answer_basis TEXT NOT NULL DEFAULT 'unknown',
material_support TEXT NOT NULL DEFAULT 'unknown',
needs_review INTEGER NOT NULL DEFAULT 1,
normalization_issues_json TEXT NOT NULL DEFAULT '["legacy_quality_unknown"]'
```

Constrain quality enums and JSON validity. Add a unique partial index on non-null `seed_task_id`. Existing candidates remain publishable only through the new explicit review rule; do not infer provenance from their text.

- [ ] **Step 4: Implement records and transactional transitions**

Add immutable dataclasses and literal types in `models.py`. In `repository.py`, keep planning, claim, outcome commit, interruption, and receipt creation transactional. Use optimistic version predicates for every mutable transition. Automatic scheduling increments `automatic_attempt_count` when its Provider invocation is claimed. Manual receipt execution uses the separate manual claim and increments only `manual_attempt_count`; it never resets or bypasses the automatic limit.

- [ ] **Step 5: Verify and commit**

Run the focused command again, then:

```bash
git diff --check
git add backend/app/db/migrations/runtime/026_curation_seed_tasks.sql backend/app/review/models.py backend/app/review/repository.py backend/tests/test_runtime_migrations.py backend/tests/test_curation_seed_tasks.py
git commit -m "feat(review): add durable curation seed tasks"
```

Reviewer gate: inspect the migration from a pre-026 database, verify completed output cannot be overwritten, and verify no cascade can delete existing candidates or legacy Work Items.

---

### Task 2: Classify Irregular and Unusable Sources Without Failing the Batch

**Files:**

- Modify: `backend/app/services/document_ingestion.py`
- Create: `backend/app/review/curation_sources.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/review/curation_sections.py`
- Test: `backend/tests/test_document_ingestion.py`
- Create: `backend/tests/test_curation_sources.py`
- Modify: `backend/tests/test_curation_sections.py`
- Modify: `backend/tests/test_curation_session_api.py`

**Interfaces:**

```python
ExtractionCode = Literal[
    "usable", "low_signal", "no_extractable_text",
    "unsupported_encoding", "parse_failed",
]

@dataclass(frozen=True, slots=True)
class TextExtractionResult:
    text: str
    code: ExtractionCode

extract_text_result(path: Path) -> TextExtractionResult

prepare_curation_sources(
    sources: tuple[tuple[str, Path], ...],
) -> CurationSourcePreparation
```

- [ ] **Step 1: Add the source-condition matrix as failing tests**

Cover non-empty UTF-8 text, whitespace-only text, tiny/repeated-noise text, invalid UTF-8, text-layer PDF, PDF with no extractable text, parser failure, and a mixed multi-source session. Assert exceptions become safe codes without paths, parser details, or document text.

Add section tests for keyword lists, incomplete questions, answers without questions, numbered prose, code fences, logs, multiple topics in one paragraph, and long unbroken text. Every usable atomic section must appear exactly once in a deterministic range or model discovery window.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_document_ingestion.py tests/test_curation_sources.py tests/test_curation_sections.py tests/test_curation_session_api.py -k "source or extraction or coverage or unusable"
```

- [ ] **Step 3: Implement safe extraction classification**

Keep the existing `extract_text(path) -> str` compatibility wrapper for unrelated callers. Add `extract_text_result` and a curation projection that retains only usable text while recording per-source warning codes. `low_signal` may still enter discovery when it contains meaningful non-whitespace content; mark it as a warning rather than silently dropping it.

Do not add OCR, image interpretation, alternate remote parsers, or arbitrary encoding guessing.

- [ ] **Step 4: Integrate source outcomes into session startup and resource warnings**

When at least one source is usable, start the existing discovery path with those excerpts and persist warnings for the others. When none is usable, create/finalize the Batch without Provider calls, set the session to normal `completed`, and return per-source reasons. Path/workspace violations must still fail securely.

- [ ] **Step 5: Verify and commit**

```bash
git diff --check
git add backend/app/services/document_ingestion.py backend/app/review/curation_sources.py backend/app/review/application.py backend/app/review/curation_sections.py backend/tests/test_document_ingestion.py backend/tests/test_curation_sources.py backend/tests/test_curation_sections.py backend/tests/test_curation_session_api.py
git commit -m "feat(review): classify messy curation sources"
```

Reviewer gate: prove all-unusable input completes without a red Agent failure, while a workspace escape still fails and does not leak its resolved path.

---

### Task 3: Separate Provider Observations from Deterministic Candidate Quality

**Files:**

- Modify: `backend/app/agents/question_curation_contracts.py`
- Create: `backend/app/agents/question_curation_normalization.py`
- Modify: `backend/app/agents/prompts/question_curation_prompts.py`
- Modify: `backend/app/agents/question_curation_agent.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/tests/test_question_curation_graph.py`
- Create: `backend/tests/test_question_curation_normalization.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class NormalizedSeedOutcome:
    seed_task_id: str
    status: Literal["completed", "degraded", "retryable"]
    candidate: dict[str, object] | None
    answer_basis: Literal["source", "mixed", "model", "unknown"]
    material_support: Literal["sufficient", "partial", "minimal", "unknown"]
    needs_review: bool
    normalization_issues: tuple[str, ...]
    error_code: str | None

normalize_provider_candidate_observation(
    observation: object,
    *, seed_tasks: tuple[CurationSeedTaskRecord, ...],
) -> tuple[NormalizedSeedOutcome, ...]
```

- [ ] **Step 1: Write the malformed-Provider matrix as failing tests**

Cover optional/null/extra fields; string-or-list topics, key points, follow-ups, and refs; Chinese/English difficulty aliases; missing/unknown difficulty; duplicates and blanks; missing title/question; missing seed key; missing/reordered refs; fewer candidates than seeds; more than three candidates; duplicate candidates for one seed; unknown/cross-seed refs; shuffled output; top-level invalid shape; empty/truncated response; source-only, mixed, model-only, and undeclared answers.

For every case assert both the per-seed outcome and the exact ordered `normalization_issues`. Assert that no output array position is ever used for association.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_question_curation_normalization.py tests/test_question_curation_graph.py -k "provider or normalize or contract or prompt or revision"
```

- [ ] **Step 3: Widen only the Provider observation models**

Provider observation fields accept null, extras, and `str | list[str | None]`. Enrichment observations include `seed_key`, `source_answer`, and `supplemental_answer`. Keep strict `QuestionSnapshot`/publication contracts separate; do not weaken them to make Provider parsing pass.

- [ ] **Step 4: Implement stable association and deterministic repairs**

Associate in this exact order:

1. exact valid `seed_key`;
2. one unique valid primary source ref;
3. one unique normalized question text;
4. otherwise mark the affected seed retryable.

Copy authoritative refs from the Seed Task. Hard-reject unknown/cross-seed refs. Apply only the accepted safe repairs: seed question fallback, title fallback, `未分类`, difficulty mapping/default, string-to-list, blank/duplicate removal, empty follow-ups, and neutral correction note. Missing answer or key points remains retryable and is never fabricated.

Derive `answer_basis`, `material_support`, `needs_review`, and deterministic issue codes from the split answer observation. Treat Provider self-reported support as an observation, not verified fact.

- [ ] **Step 5: Route enrichment and revision through the same boundary**

Update prompts to require seed key echo and answer splitting, but keep application-side fallbacks authoritative. Revision receives one known seed/candidate context and cannot add refs. Agent client transport retry remains separate from the one-seed content fallback implemented later.

- [ ] **Step 6: Verify and commit**

```bash
git diff --check
git add backend/app/agents/question_curation_contracts.py backend/app/agents/question_curation_normalization.py backend/app/agents/prompts/question_curation_prompts.py backend/app/agents/question_curation_agent.py backend/app/review/models.py backend/tests/test_question_curation_graph.py backend/tests/test_question_curation_normalization.py
git commit -m "feat(review): normalize curation provider observations"
```

Reviewer gate: mutate every untrusted ref and confirm no Provider-created evidence enters a normalized candidate; confirm missing core content never becomes an empty strict field.

---

### Task 4: Reconcile Legacy Work Items into Seed Tasks Without Replay

**Files:**

- Create: `backend/app/review/curation_seed_reconciliation.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/review/application.py`
- Create: `backend/tests/test_curation_seed_reconciliation.py`
- Modify: `backend/tests/test_curation_session_api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SeedReconciliationResult:
    planned: int
    restored_completed: int
    restored_degraded: int
    pending: int
    warnings: tuple[dict[str, object], ...]

reconcile_curation_seed_tasks(
    repository: ReviewRepository, batch_id: str,
) -> SeedReconciliationResult
```

- [ ] **Step 1: Build legacy-state fixtures and failing reconciliation tests**

Create pre-seed fixtures with completed discovery Work Items, completed enrichment chunks, failed/pending enrichment chunks, shuffled candidates, duplicate refs, and already-finalized candidates. Assert:

- every completed discovery seed gets one stable Seed Task;
- completed legacy candidate output maps only by valid primary ref or unique normalized question text;
- mapped legacy output becomes completed/degraded with `unknown` provenance and `needs_review=True`;
- failed/pending legacy chunks produce only pending tasks for seeds without a terminal result;
- repeated reconciliation changes no rows or counts;
- completed legacy candidates are not double-counted by reducers;
- ambiguous legacy output becomes a warning and retryable task, never a positional match.

Add a synthetic fixture with the same shape as the current Batch: 80 completed discovery units and 22 completed enrichment outputs. Assert all 22 are restored and no fake Agent method is called.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_seed_reconciliation.py tests/test_curation_session_api.py -k "reconcile or legacy or preserve"
```

- [ ] **Step 3: Implement idempotent reconciliation**

Read completed discovery outputs in stable `(unit_index, seed_ordinal)` order, create Seed Tasks, then fold completed enrichment output onto them. Never update legacy Work Item JSON. Record safe warnings for unmappable legacy rows. Prefer Seed Tasks in progress/candidate reducers once reconciliation has run.

Invoke reconciliation before enrichment planning, Batch resume, and curation resource projection so upgraded states are consistent across CLI, API, restart, and browser paths.

- [ ] **Step 4: Validate against an isolated copy of the real runtime database**

Copy the current runtime SQLite file into `/tmp`, run migrations and reconciliation only on the copy, and query counts for Batch `907129b5-0a8c-47cb-b8a0-be42b73459a9`. Expected: discovery remains 80 completed, 22 completed enrichment outputs are represented once, and Provider invocation count remains zero. Do not alter the live runtime database in this step.

- [ ] **Step 5: Verify and commit**

```bash
git diff --check
git add backend/app/review/curation_seed_reconciliation.py backend/app/review/repository.py backend/app/graphs/question_curation.py backend/app/review/application.py backend/tests/test_curation_seed_reconciliation.py backend/tests/test_curation_session_api.py
git commit -m "feat(review): reconcile legacy curation seed output"
```

Reviewer gate: compare counts before/after two reconciliations and inspect Agent fakes to prove zero Provider calls for restored completed output.

---

### Task 5: Execute Batched Enrichment with Per-Seed Commit and One Fallback

**Files:**

- Modify: `backend/app/review/curation_scheduler.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/tests/test_curation_scheduler.py`
- Modify: `backend/tests/test_question_curation_graph.py`
- Modify: `backend/tests/test_curation_session_api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CurationInvocationResult:
    seed_task_ids: tuple[str, ...]
    transport_error_code: str | None

run_curation_invocation_wave(
    invocations: tuple[tuple[str, ...], ...], *, limit: int,
    worker: Callable[[tuple[str, ...]], Awaitable[None]],
) -> CurationWaveResult
```

- [ ] **Step 1: Write concurrency, partial-success, and recovery tests first**

Use barriers/counters to prove at most 3 concurrent Provider calls and at most 3 seeds per first-pass call. Cover one-bad/two-good, one missing result, malformed whole response, all malformed responses, 429 reduction to concurrency 1, timeout/5xx exhaustion, process cancellation, pause, terminate, resume, and restart.

Assert:

- valid sibling seeds commit immediately even when one seed is retryable;
- only retryable seeds receive a single-seed fallback;
- automatic attempt count never exceeds 2;
- malformed content becomes retryable/skipped, not Batch failed;
- completed/degraded/skipped tasks do not replay after pause/restart;
- all skipped or zero seeds ends normally with no candidates;
- exhausted Provider connectivity may fail the Batch only after all started sibling calls settle and their successes persist;
- persistence/security/authoritative-state exceptions retain their dedicated failure semantics.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_scheduler.py tests/test_question_curation_graph.py tests/test_curation_session_api.py -k "seed or fallback or partial or concurrency or restart or pause or transport"
```

- [ ] **Step 3: Replace enrichment Work Item scheduling with Seed Task scheduling**

Select at most 9 pending seeds per wave, pack them into up to 3 invocations, and claim each task before calling the Agent. Normalize one response against the invocation's exact task set and commit each result independently. Keep legacy enrichment Work Items as audit records; new recovery/progress decisions read Seed Tasks.

Run retryable tasks in later waves as one-seed invocations. A second unusable content result becomes skipped. A transport interruption becomes interrupted and is reset to pending only by explicit Batch resume.

- [ ] **Step 4: Narrow Batch failure reduction**

Introduce an explicit error classifier for infrastructure/provider unavailability, database/file transaction, security/path boundary, authoritative state corruption, and invariant conflicts. Provider-created unknown refs and schema/content defects stay per seed. Do not use a catch-all worker exception to fail the Batch before classification.

Finalize to `review_pending` when at least one candidate exists; finalize normally to `completed` when no candidate survives. Preserve warning and quality summaries in both cases.

- [ ] **Step 5: Verify and commit**

```bash
git diff --check
git add backend/app/review/curation_scheduler.py backend/app/graphs/question_curation.py backend/app/application/execution_service.py backend/app/review/repository.py backend/tests/test_curation_scheduler.py backend/tests/test_question_curation_graph.py backend/tests/test_curation_session_api.py
git commit -m "feat(review): isolate curation outcomes per seed"
```

Reviewer gate: inspect the call log for a one-bad/two-good case and verify exactly two Provider invocations total: one three-seed call and one single-seed fallback.

---

### Task 6: Project Seed Quality, Add Manual Retry, and Enforce Publication Gates

**Files:**

- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/application/event_projector.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/tests/test_curation_session_api.py`
- Modify: `backend/tests/test_review_routes.py`
- Modify: `backend/tests/test_event_projector.py`
- Modify: `backend/tests/test_review_service.py`

**Resource additions:**

```text
CurationSessionResource.seedProgress:
  total/completed/degraded/retrying/skipped/pending

CurationSessionResource.qualitySummary:
  source/mixed/model/unknown/needsReview

CurationSessionResource.sourceWarnings[]

QuestionCandidateResource:
  seedTaskId/answerBasis/materialSupport/needsReview/normalizationIssues
```

**Endpoint:**

```http
POST /api/review/curation-sessions/{sessionId}/seed-tasks/{seedTaskId}/retry
Idempotency-Key: retry-seed-0001
Content-Type: application/json

{"expectedVersion": 3}
```

- [ ] **Step 1: Write API, event, and publication tests first**

Assert the resource counters are mutually consistent and derived from durable rows. Assert the retry endpoint:

- returns 202 with a receipt for skipped/retryable only;
- rejects another session's task, stale versions, terminal completed/degraded tasks, and content/ref/output fields;
- returns the same receipt for the same key/digest;
- schedules one single-seed Execution and never starts an autonomous loop.

Assert `curation.seed.changed` contains only `sessionId`, `batchId`, `seedTaskId`, `status`, attempt counts, quality flags, and `errorCode`. Projector tests must prove question text, answers, Provider output, paths, and exception messages are dropped.

Add publication tests for incomplete candidates and `mixed/model/unknown` provenance. Direct publish, active-version update, command-driven confirm, and bulk publication must all share the same validator.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_session_api.py tests/test_review_routes.py tests/test_event_projector.py tests/test_review_service.py -k "seed_progress or seed_retry or quality or publish or event"
```

- [ ] **Step 3: Add backward-compatible schemas and resources**

Add typed seed progress, quality summary, source warning, candidate quality, retry command, and accepted retry receipt resources. Keep existing progress/timing fields unchanged for current clients.

Add `confirm_ai_supplement: bool = False` to single-candidate publish/update-active commands and `confirmed_ai_candidate_ids: list[str] = []` to bulk publication. The server must require confirmation for `mixed`, `model`, or `unknown`; a hidden or stale client cannot bypass the gate.

- [ ] **Step 4: Implement one-shot retry and safe events**

Validate ownership/version/status, create the receipt and Execution transactionally, then schedule exactly one Seed Task attempt. Publish safe state changes after committed transitions. Replayed requests return the original accepted resource.

- [ ] **Step 5: Centralize strict publication validation**

Validate non-empty title, question, answer, topics, and key points; supported difficulty; authoritative refs; current draft version/hash; duplicate resolution; and explicit AI supplement confirmation. Return stable field/error codes to the UI. Manual edits may resolve incomplete content, but provenance remains review-visible.

- [ ] **Step 6: Verify and commit**

```bash
git diff --check
git add backend/app/schemas/review.py backend/app/api/routes_review.py backend/app/review/application.py backend/app/review/repository.py backend/app/application/event_projector.py backend/app/application/session_service.py backend/tests/test_curation_session_api.py backend/tests/test_review_routes.py backend/tests/test_event_projector.py backend/tests/test_review_service.py
git commit -m "feat(review): expose curation quality and seed retry"
```

Reviewer gate: call every publication entry point with a model/unknown candidate and no confirmation; all must fail with the same safe domain code.

---

### Task 7: Add Warning-State Quality UX and Explicit Single-Seed Recovery

**Files:**

- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.tsx`
- Modify: `frontend/src/features/review/CurationProvisionalList.tsx`
- Modify: `frontend/src/features/review/CurationArtifactCard.tsx`
- Modify: `frontend/src/features/review/CurationArtifactDetail.tsx`
- Modify: `frontend/src/features/review/QuestionDetailPanel.tsx`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Modify: `frontend/src/app/global.css`
- Modify: `frontend/src/features/review/reviewApi.test.ts`
- Modify: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.test.tsx`
- Modify: `frontend/src/features/review/QuestionDetailPanel.test.tsx`
- Modify: `frontend/src/features/agent/useAgentEvents.test.tsx`

- [ ] **Step 1: Invoke the UI design review gate before editing**

Use `ui-ux-pro-max` only for this Task to check semantic color, information hierarchy, compact desktop/mobile layout, and accessible action states against the existing R2 visual system. Exit the gate with an explicit component/state checklist; do not redesign navigation or the overall shell.

- [ ] **Step 2: Write interaction and rendering tests first**

Cover:

- live seed totals for completed/degraded/retrying/skipped/pending;
- yellow warnings for AI supplement, partial/minimal support, incomplete, and skipped;
- red only for real Batch/Execution failure;
- filters for primarily AI-generated, insufficient support, and incomplete/review-required;
- retry button only on skipped/retryable tasks, disabled while accepted/running;
- repeated click reuses one idempotency key until receipt resolution;
- source warnings rendered per file without raw parser text;
- publish confirmation dialog naming the provenance risk;
- event-driven targeted invalidation without putting content into SSE;
- 390px layout, keyboard focus, `aria-live`, and non-color-only labels.

- [ ] **Step 3: Run focused frontend tests and confirm RED**

```bash
cd frontend && npm test -- --run src/features/review/reviewApi.test.ts src/features/review/QuestionCatalog.test.tsx src/features/review/CurationRuntimePanel.test.tsx src/features/review/QuestionDetailPanel.test.tsx src/features/agent/useAgentEvents.test.tsx
```

- [ ] **Step 4: Implement typed API state and mutations**

Add resource types and `retryCurationSeedTask`. In `QuestionCatalog`, own filters, receipt state, query invalidation, and explicit AI confirmation. Continue using the backend as the source of truth after SSE/retry responses.

- [ ] **Step 5: Implement semantic quality presentation**

Use existing neutral/primary/success styles for normal progress. Use semantic warning tokens, icon, and text for AI supplement/partial/incomplete/skipped. Keep danger tokens exclusively for genuine failure and destructive termination. Show provenance and support in both cards and detail panels; never hide publication blockers behind hover-only UI.

- [ ] **Step 6: Verify and commit**

Run focused tests, then `npm run build` and:

```bash
git diff --check
git add frontend/src/features/review/reviewTypes.ts frontend/src/features/review/reviewApi.ts frontend/src/features/review/QuestionCatalog.tsx frontend/src/features/review/CurationRuntimePanel.tsx frontend/src/features/review/CurationProvisionalList.tsx frontend/src/features/review/CurationArtifactCard.tsx frontend/src/features/review/CurationArtifactDetail.tsx frontend/src/features/review/QuestionDetailPanel.tsx frontend/src/features/agent/useAgentEvents.ts frontend/src/app/global.css frontend/src/features/review/reviewApi.test.ts frontend/src/features/review/QuestionCatalog.test.tsx frontend/src/features/review/CurationRuntimePanel.test.tsx frontend/src/features/review/QuestionDetailPanel.test.tsx frontend/src/features/agent/useAgentEvents.test.tsx
git commit -m "feat(review): show curation quality and recovery states"
```

Reviewer gate: visually compare warning and failure side by side; they must remain distinguishable in color, icon, label, and action semantics.

---

### Task 8: Run Cross-Layer Acceptance, Preserve the Current Batch, and Refresh Delivery Evidence

**Files:**

- Create: `backend/tests/test_curation_messy_notes_acceptance.py`
- Modify as required by defects only: files touched in Tasks 1–7
- Update locally, do not stage: `docs/verification/r2-complete-review-agent.md`
- Update after implementation stabilizes: `task_plan.md`
- Update after implementation stabilizes: `findings.md`
- Update after implementation stabilizes: `progress.md`
- Update formal architecture docs only if implementation reveals a material divergence from the accepted spec.

- [ ] **Step 1: Add one cross-layer messy-notes acceptance fixture**

Use a fully synthetic, non-secret material containing keywords, bullets, incomplete questions, answers without questions, numbered prose, code, logs, repeated topics, long text, and one unusable source. Use a scripted fake Provider that returns one good, one repairable, one incomplete, one cross-ref, one malformed top-level response, and one transport failure in separate invocations.

Assert final candidates, provenance counts, single-seed fallbacks, skipped reasons, Batch terminal state, no replay, safe events, and publication blocking.

- [ ] **Step 2: Run the first full regression after integration**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q
cd ../frontend && npm test -- --run && npm run build
```

Fix only evidenced regressions. Re-run targeted affected tests first. Use a second full regression only after fixes that cross subsystem boundaries.

- [ ] **Step 3: Validate migration and reconciliation on an isolated real-data copy**

Repeat the Task 4 `/tmp` database-copy procedure after all schema/reducer work is final. Record only counts and stable IDs in local verification. Required evidence for Batch `907129b5-0a8c-47cb-b8a0-be42b73459a9`:

- 80 completed discovery units remain present;
- all 22 completed enrichment outputs are represented exactly once;
- completed/degraded Seed Tasks are not claimable;
- no Provider call occurs during migration, resource projection, or reconciliation.

- [ ] **Step 4: Run browser acceptance**

Start local backend/frontend services and first run one minimal happy path. Then run one complete desktop and 390px acceptance pass for partial success, live elapsed/progress, warning vs failure semantics, pause/refresh/resume, one skipped-seed retry, quality filters, editing incomplete content, and strict publication confirmation. Re-run only affected scenarios after fixes. Stop services afterward.

- [ ] **Step 5: Refresh documentation evidence and gates**

Update `docs/verification/r2-complete-review-agent.md` as the final user guide and acceptance record, but keep it uncommitted per repository policy. Refresh the R2 learning ownership pack only after implementation stabilizes, classify it with the required risk profile, compare it with the previous same-profile stage, and run:

```bash
python3 scripts/check_stage_docs.py --verification docs/verification/r2-complete-review-agent.md --learning docs/learning/r2-complete-review-agent/ --plan docs/superpowers/plans/2026-07-22-r2-messy-notes-curation-resilience.md
```

Unchecked browser acceptance or inconsistent evidence blocks “ready for manual verification.” Unfinished learning exercises remain non-blocking ownership debt.

- [ ] **Step 6: Commit acceptance code and formal planning updates**

Stage only the new acceptance test, required defect fixes, and formal/root planning updates. Inspect `git status --short` before committing so the two unrelated untracked documents and all local verification/learning files remain unstaged.

```bash
git diff --check
git commit -m "test(review): verify messy notes curation resilience"
```

Reviewer gate: verify the final report separates product status/evidence, maturity boundary, ownership status, next product task, and non-blocking user exercise.

---

## Completion Boundary

This plan is complete only when:

- Seed Tasks are the durable enrichment recovery boundary and legacy Work Items remain auditable;
- irregular source and Provider-shape defects produce warnings, degradation, or skips instead of whole-Batch failure;
- one bad seed cannot roll back or replay valid siblings;
- every automatic seed attempt is bounded to two calls;
- current completed discovery/enrichment work is preserved without Provider replay;
- source/model provenance is visible and enforced at every publication entry point;
- pause, terminate, restart, manual seed retry, safe SSE, desktop, and 390px behavior have acceptance evidence;
- full tests/build, migration checks, browser acceptance, and documentation gate pass.

The delivered maturity level remains a single-process bounded scheduler with SQLite recovery and human-reviewed AI supplementation. It is not a distributed queue, OCR pipeline, autonomous repair Agent, or semantic fact-verification system.
