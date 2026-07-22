# R2 Curation Long-Task Control and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make question curation fast, observable, pausable, resumable, and permanently terminable without replaying completed model work, while making local Agent Trace timestamps directly readable in Beijing time.

**Architecture:** Keep the existing discovery/enrichment pipeline, but separate one Execution attempt from the durable Question Batch and its Work Items. Add structure-aware deterministic seed extraction, larger uncovered-text discovery windows, bounded three-way concurrency, domain control APIs, provisional read-only candidates, and a frontend elapsed-time/control surface. Keep UTC as the canonical timestamp and add an Asia/Shanghai projection to Trace schema v2.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, asyncio, LangGraph/LangChain, React 19, TypeScript, TanStack Query, Vitest, Testing Library, CSS semantic tokens.

## Global Constraints

- Work only in `/Users/miracle778/Project/cyber-interview-agent-new/.worktrees/r2-complete-review-agent` on `feature/review-agent-workspace`.
- Do not modify or commit `docs/my_idea.md`.
- Execution is one attempt; Question Batch owns durable task state; Curation Work Item is the smallest recovery boundary.
- Pause preserves the Batch and permits resume; terminate makes the Batch permanently non-resumable.
- A resumed task creates a new Execution against the same Batch and immutable inputs; completed Work Items never replay.
- Provider invocation is at-least-once; domain output commit is exactly-once through input digest, state predicates, and immutable completed output.
- Deterministic rules only identify question/evidence boundaries. They never generate answers or silently discard uncovered text.
- Discovery and enrichment each default to at most 3 active Provider requests. Rate limiting must reduce subsequent concurrency to 1.
- Enrichment stays at no more than 3 complete candidates per model response and 4,096 visible output tokens.
- Provisional candidates are read-only and cannot enter confirmation, publication, context assembly, or the Knowledge Vault.
- Trace `timestamp` remains canonical UTC. Schema v2 adds `local_timestamp` and `timezone="Asia/Shanghai"`; existing v1 rows remain readable.
- Frontend implementation must follow the existing light, professional, data-dense semantic-token system and the `ui-ux-pro-max` review gate already required by the R2 task plan.
- Update `docs/verification/r2-complete-review-agent.md` locally after every Task; do not stage `docs/verification/`.
- Use focused tests during Tasks. Run the complete backend/frontend regression only after cross-layer integration and once before final acceptance if a second run is necessary.

---

## File and Interface Map

### Runtime persistence and domain state

- Create `backend/app/db/migrations/runtime/019_curation_long_task_control.sql`: rebuild curation Batch/Session/Work Item constraints, add optimistic control fields, Batch attempt history, and idempotent control receipts.
- Modify `backend/app/review/models.py`: add typed Batch status/control/attempt records and Work Item processor/status fields.
- Modify `backend/app/review/repository.py`: own all Batch transitions, control receipts, attempt history, interruption reconciliation, timing aggregation, and provisional output queries.

### Structure-aware planning and model contracts

- Modify `backend/app/review/curation_sections.py`: retain stable atomic sections and remove the six-section Provider-call coupling.
- Create `backend/app/review/curation_planner.py`: classify deterministic question ranges, prove complete source coverage, and pack only uncovered text into bounded LLM windows.
- Modify `backend/app/agents/question_curation_contracts.py`: preserve `source_ref` compatibility while adding bounded ordered `source_refs` and raising discovery output capacity to 20 lightweight seeds.
- Modify `backend/app/agents/prompts/question_curation_prompts.py`: describe the new seed evidence contract and 20-seed discovery maximum.
- Modify `backend/app/agents/question_curation_agent.py`: validate all evidence refs, use the reduced discovery timeout, and retain three-candidate enrichment.

### Bounded scheduler and Graph

- Create `backend/app/review/curation_scheduler.py`: run one bounded wave, wait for all started workers, preserve successes, and report failures deterministically.
- Modify `backend/app/graphs/question_curation.py`: plan deterministic/model work, execute waves of up to the persisted concurrency limit, expose provisional progress, and reduce without serial prior-output dependencies.
- Modify `backend/app/application/execution_service.py`: project monotonic concurrent progress and delegate curation terminal transitions to the domain repository.

### Control API and resource projection

- Modify `backend/app/review/application.py`: pause/resume/terminate, Batch attempt creation, timing/provisional resources, and backward-compatible retry delegation.
- Modify `backend/app/schemas/review.py`: control command, timing, controls, progress, and provisional candidate resources.
- Modify `backend/app/api/routes_review.py`: three domain control endpoints.
- Modify `backend/app/application/session_service.py`: allow the safe curation control event.
- Modify `backend/app/application/workspace_runtime.py`: reconcile interrupted curation tasks at startup.

### Frontend

- Modify `frontend/src/features/review/reviewTypes.ts`: Batch states, timing, controls, active workers, and provisional candidates.
- Modify `frontend/src/features/review/reviewApi.ts`: pause/resume/terminate requests.
- Modify `frontend/src/features/review/QuestionCatalog.tsx`: domain control mutations and refresh/SSE reconciliation.
- Modify `frontend/src/features/review/CurationRuntimePanel.tsx`: real-time elapsed time, distinct state actions, and provisional preview.
- Create `frontend/src/features/review/CurationProvisionalList.tsx`: read-only processing preview.
- Modify `frontend/src/features/agent/useAgentEvents.ts`: add the safe curation control event.
- Modify `frontend/src/app/global.css`: semantic paused/interrupted/terminated/provisional styles.

### Trace time

- Modify `backend/app/diagnostics/agent_trace.py`: schema v2 UTC/local timezone fields.
- Modify `backend/app/middleware/agent_trace_middleware.py`: monotonic `duration_ms` for model/tool terminal events.

---

### Task 1: Upgrade Agent Trace Time Semantics to Schema v2

**Files:**

- Modify: `backend/app/diagnostics/agent_trace.py`
- Modify: `backend/app/middleware/agent_trace_middleware.py`
- Test: `backend/tests/test_agent_trace_writer.py`
- Test: `backend/tests/test_agent_trace_middleware.py`

**Interfaces:**

- Consumes: existing `AgentTraceWriter.append(identity, event_type, payload, terminal=False) -> bool`.
- Produces: every new row has `schema_version=2`, canonical `timestamp`, `local_timestamp`, and `timezone`; terminal model/tool payloads contain non-negative monotonic `duration_ms`.

- [x] **Step 1: Write failing schema and duration tests**

Add exact assertions to `test_agent_trace_writer.py`:

```python
from datetime import datetime

def test_writer_records_utc_and_beijing_time_for_the_same_instant(tmp_path: Path) -> None:
    AgentTraceWriter().append(identity(tmp_path), "model.request", {})
    row = read_trace_rows(tmp_path, "s1", "r1")[0]
    assert row["schema_version"] == 2
    assert row["timezone"] == "Asia/Shanghai"
    utc = datetime.fromisoformat(row["timestamp"])
    local = datetime.fromisoformat(row["local_timestamp"])
    assert utc.utcoffset().total_seconds() == 0
    assert local.utcoffset().total_seconds() == 8 * 60 * 60
    assert utc.timestamp() == local.timestamp()
```

In `test_agent_trace_middleware.py`, invoke the fake model and tool handlers and assert terminal rows contain `duration_ms >= 0`. Retain a hand-written v1 line before a v2 append and assert `read_trace_rows` returns both in sequence.

- [x] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_writer.py tests/test_agent_trace_middleware.py
```

Expected: failures show schema version 1 and missing `local_timestamp`, `timezone`, or `duration_ms`.

- [x] **Step 3: Implement one-instant dual timestamps and monotonic durations**

Use one UTC instant for both representations:

```python
from zoneinfo import ZoneInfo

_LOCAL_TIMEZONE_NAME = "Asia/Shanghai"
_LOCAL_TIMEZONE = ZoneInfo(_LOCAL_TIMEZONE_NAME)

observed_at = datetime.now(timezone.utc)
row = {
    "schema_version": 2,
    "timestamp": observed_at.isoformat(timespec="milliseconds"),
    "local_timestamp": observed_at.astimezone(_LOCAL_TIMEZONE).isoformat(timespec="milliseconds"),
    "timezone": _LOCAL_TIMEZONE_NAME,
    # existing identity, sequence and payload fields
}
```

Measure each middleware invocation with `time.monotonic()` and merge the duration into success/error terminal payloads:

```python
started_at = time.monotonic()
try:
    response = await handler(request)
except BaseException as error:
    payload = {**safe_error_payload(error), "duration_ms": max(0, int((time.monotonic() - started_at) * 1000))}
    ...
payload = {"response": response, "duration_ms": max(0, int((time.monotonic() - started_at) * 1000))}
```

Do not derive duration from either ISO timestamp.

- [x] **Step 4: Run focused verification**

Run the Task 1 command again. Expected: all Trace writer/middleware tests pass and credential-redaction tests remain green. Run `git diff --check`.

- [x] **Step 5: Update local verification and commit**

Record schema v2, v1 compatibility, and monotonic duration evidence in `docs/verification/r2-complete-review-agent.md`, but stage only source/tests:

```bash
git add backend/app/diagnostics/agent_trace.py backend/app/middleware/agent_trace_middleware.py backend/tests/test_agent_trace_writer.py backend/tests/test_agent_trace_middleware.py
git commit -m "feat(agent): add local time to trace events"
```

Reviewer gate: compare UTC and Beijing strings as instants, inspect raw bytes for secrets, and confirm a Trace write failure still cannot fail the Agent call.

---

### Task 2: Add Durable Batch Control, Attempt History, and Recovery State

**Files:**

- Create: `backend/app/db/migrations/runtime/019_curation_long_task_control.sql`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_curation_work_items.py`

**Interfaces:**

- Consumes: current Question Batch and Work Item tables/methods.
- Produces:

```python
request_batch_control(batch_id: str, *, operation: Literal["pause", "terminate"], idempotency_key: str, expected_version: int) -> CurationControlReceiptRecord
finalize_batch_control(receipt_id: str) -> QuestionBatchRecord
resume_curation_batch(batch_id: str, *, execution_id: str, idempotency_key: str, expected_version: int, reason: Literal["paused", "failed", "interrupted"]) -> QuestionBatchRecord
record_curation_attempt(batch_id: str, execution_id: str, *, reason: str) -> CurationBatchAttemptRecord
interrupt_running_curation_work_items(batch_id: str, *, error_code: str) -> int
curation_batch_timing(batch_id: str) -> CurationBatchTiming
```

- [x] **Step 1: Write failing migration and repository state-machine tests**

Extend `test_runtime_migrations.py` to expect migration 19, the new columns, attempt/control tables, indexes, and `PRAGMA foreign_key_check == []`.

Add repository tests that prove:

```python
receipt = repository.request_batch_control(
    batch.id,
    operation="pause",
    idempotency_key="pause-request-0001",
    expected_version=batch.version,
)
assert repository.request_batch_control(
    batch.id,
    operation="pause",
    idempotency_key="pause-request-0001",
    expected_version=batch.version,
) == receipt

paused = repository.finalize_batch_control(receipt.id)
assert paused.status == "paused"
assert paused.version == batch.version + 2

with pytest.raises(ReviewConflictError):
    repository.resume_curation_batch(
        terminated.id,
        execution_id="run-2",
        idempotency_key="resume-request-0001",
        expected_version=terminated.version,
        reason="paused",
    )
```

Also cover changed payload under the same idempotency key, stale expected version, one active attempt, cumulative timing excluding pauses, interrupted Work Item restart, and completed output immutability.

- [x] **Step 2: Run tests and confirm RED**

Run:

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_runtime_migrations.py tests/test_curation_work_items.py
```

Expected: migration version/columns and new repository symbols are missing.

- [x] **Step 3: Implement migration 019**

Rebuild constrained tables while the migration runner has foreign keys disabled. Preserve every existing row and index. Add:

```sql
-- review_question_batches additions
version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
control_intent TEXT CHECK (control_intent IN ('pause', 'terminate')),
concurrency_limit INTEGER NOT NULL DEFAULT 3 CHECK (concurrency_limit BETWEEN 1 AND 3)

-- accepted batch states
CHECK (status IN (
  'generating', 'paused', 'interrupted',
  'review_pending', 'completed', 'failed', 'terminated'
))

CREATE TABLE review_curation_batch_attempts (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
  execution_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL CHECK (ordinal > 0),
  reason TEXT NOT NULL CHECK (reason IN ('initial', 'paused', 'failed', 'interrupted')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(batch_id, ordinal)
);

CREATE TABLE review_curation_control_receipts (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
  idempotency_key TEXT NOT NULL,
  operation TEXT NOT NULL CHECK (operation IN ('pause', 'resume', 'terminate')),
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
  result_status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(batch_id, idempotency_key)
);
```

Rebuild `review_curation_work_items` with `processor_kind IN ('deterministic','model')` and `status IN ('pending','running','completed','failed','interrupted')`. Rebuild `review_curation_sessions.stage` to accept paused/interrupted/terminated.

- [x] **Step 4: Implement typed records and transactional repository methods**

Add frozen records and Literal aliases to `models.py`. Implement every produced method with `BEGIN IMMEDIATE`, expected version/state predicates, canonical request digests, and stable errors. `start_curation_work_item` accepts only pending/failed/interrupted and never increments deterministic completed items.

Timing aggregation must use all related `agent_runs.started_at/finished_at`; an active run uses the current UTC instant, and paused gaps are not present in any Execution interval.

- [x] **Step 5: Run focused tests and integrity checks**

Run the Task 2 command again. Then execute the existing repository regression:

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_review_repository.py tests/test_curation_work_items.py tests/test_runtime_migrations.py
```

Expected: all pass, including existing generation-2 upgrade and foreign-key checks. Run `git diff --check`.

- [x] **Step 6: Update local verification and commit**

```bash
git add backend/app/db/migrations/runtime/019_curation_long_task_control.sql backend/app/review/models.py backend/app/review/repository.py backend/tests/test_runtime_migrations.py backend/tests/test_curation_work_items.py
git commit -m "feat(review): persist curation task controls"
```

Reviewer gate: inspect every transition predicate, recreate a database at version 18 and migrate it, and prove existing Batch/Work Item rows survive unchanged.

---

### Task 3: Build Structure-Aware Discovery Planning and Multi-Reference Seeds

**Files:**

- Modify: `backend/app/review/curation_sections.py`
- Create: `backend/app/review/curation_planner.py`
- Modify: `backend/app/agents/question_curation_contracts.py`
- Modify: `backend/app/agents/prompts/question_curation_prompts.py`
- Modify: `backend/app/agents/question_curation_agent.py`
- Test: `backend/tests/test_curation_sections.py`
- Create: `backend/tests/test_curation_planner.py`
- Modify: `backend/tests/test_question_curation_graph.py`

**Interfaces:**

- Consumes: `section_sources(source_excerpts) -> tuple[SourceSection, ...]`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class DeterministicSeedUnit:
    unit_index: int
    seeds: tuple[QuestionSeed, ...]
    source_refs: tuple[str, ...]
    input_digest: str

@dataclass(frozen=True, slots=True)
class CurationDiscoveryPlan:
    deterministic_units: tuple[DeterministicSeedUnit, ...]
    model_units: tuple[DiscoveryUnit, ...]
    covered_source_refs: tuple[str, ...]

def plan_curation_discovery(sections: tuple[SourceSection, ...]) -> CurationDiscoveryPlan: ...
```

`QuestionSeed` keeps `source_ref` as its primary anchor for stored-output compatibility and adds normalized ordered `source_refs: list[str]` with a maximum of 32 refs. `QuestionSeedChunk` allows at most 20 lightweight seeds.

- [x] **Step 1: Write failing coverage, quality, and compatibility tests**

Cover explicit question lines, question-like Markdown/bold headings, numbered questions, answer lists that must not become peer questions, mixed structured/prose input, and a 40,000-character unstructured source.

Key assertions:

```python
plan = plan_curation_discovery(section_sources((mixed_source,)))
assert set(plan.covered_source_refs) == {section.ref for section in section_sources((mixed_source,))}
assert all(seed.source_ref == seed.source_refs[0] for unit in plan.deterministic_units for seed in unit.seeds)
assert len(plan_curation_discovery(section_sources((plain_40k,))).model_units) in range(7, 11)

legacy = QuestionSeed.model_validate({"question_text": "什么是 MVCC？", "source_ref": "s1#section-0001"})
assert legacy.source_refs == ["s1#section-0001"]
```

Add Agent validation tests for unknown secondary refs, cross-source refs, duplicate refs, and ordered normalization.

- [x] **Step 2: Run tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_sections.py tests/test_curation_planner.py tests/test_question_curation_graph.py
```

Expected: the planner module and multi-reference contract do not exist; the old packer still creates one unit per six short sections.

- [x] **Step 3: Implement coverage-first planning**

Keep atomic section/ref generation in `curation_sections.py`. Move Provider-call planning into `curation_planner.py`:

```python
_QUESTION_CUES = re.compile(r"(?:什么|如何|为什么|区别|原理|机制|怎么|哪些|是否|能否|介绍|说说|谈谈|分析)")

def _is_question_anchor(section: SourceSection) -> bool:
    first_line = section.text.splitlines()[0].strip()
    return (
        first_line.endswith(("?", "？"))
        or _question_heading(first_line, _QUESTION_CUES)
        or _numbered_question(first_line, _QUESTION_CUES)
    )
```

Form a deterministic range from one strong anchor up to the next strong anchor in the same source. Put every remaining section into an ordered LLM window capped at 6,000 characters. Build and validate a coverage set; raise a stable planning error if any ref is missing or appears in incompatible ranges.

- [x] **Step 4: Implement the compatible seed contract and prompt**

Use an after-validator so old `{source_ref}` output becomes `[source_ref]`, while new output requires the primary ref first, removes duplicate refs stably, and rejects more than 32 refs. Update discovery Prompt/rendering to allow no more than 20 seeds and require every cited ref to appear in the current window.

Update `QuestionCurationAgents.discover` and `enrich` to validate all refs against the supplied sections. Set discovery policy to `ModelInvocationPolicy(2_048, 90, 1)` and enrichment to `ModelInvocationPolicy(4_096, 180, 1)`.

- [x] **Step 5: Run focused quality verification**

Run the Task 3 command again. Expected: all planner, legacy contract, Prompt, and Agent validation tests pass. Run `git diff --check`.

- [x] **Step 6: Validate the local authorized material without Provider calls and commit**

Run only the pure planner against the user-selected local material. Record character count, atomic section count, deterministic seed count, uncovered window count, and coverage equality in `docs/verification/r2-complete-review-agent.md`; do not copy source text.

```bash
git add backend/app/review/curation_sections.py backend/app/review/curation_planner.py backend/app/agents/question_curation_contracts.py backend/app/agents/prompts/question_curation_prompts.py backend/app/agents/question_curation_agent.py backend/tests/test_curation_sections.py backend/tests/test_curation_planner.py backend/tests/test_question_curation_graph.py
git commit -m "feat(review): plan curation by document structure"
```

Reviewer gate: inspect every section ref in the coverage report and manually classify a sample of deterministic anchors, uncovered prose, and rejected answer-list boundaries.

---

### Task 4: Execute Discovery and Enrichment with Bounded Concurrency

**Files:**

- Create: `backend/app/review/curation_scheduler.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/application/execution_service.py`
- Test: `backend/tests/test_question_curation_graph.py`
- Test: `backend/tests/test_curation_work_items.py`
- Create: `backend/tests/test_curation_scheduler.py`
- Test: `backend/tests/test_checkpoint_serialization.py`

**Interfaces:**

- Consumes: Task 2 Work Item transitions and Task 3 `CurationDiscoveryPlan`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CurationWaveResult:
    completed_ids: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]

async def run_curation_wave(
    work_item_ids: tuple[str, ...],
    *,
    limit: int,
    worker: Callable[[str], Awaitable[None]],
) -> CurationWaveResult: ...
```

Graph state exposes only IDs, phase, completed/total counts, generated candidate count, warnings, and final candidates. It does not copy full source text into Work Item rows or product Events.

- [x] **Step 1: Write failing scheduler and concurrent Graph tests**

Use an asyncio barrier fake Agent to measure active calls:

```python
active = 0
peak = 0

async def worker(item_id: str) -> None:
    nonlocal active, peak
    active += 1
    peak = max(peak, active)
    await release.wait()
    active -= 1

result = await run_curation_wave(tuple(f"w-{i}" for i in range(6)), limit=3, worker=worker)
assert peak == 3
assert not result.failed
```

Add Graph cases where completion order is reversed, one worker fails while two succeed, a cancellation interrupts running items, deterministic units perform zero Agent calls, a resumed Batch skips completed work, and enrichment receives no unbounded list of earlier generated questions. Add invocation-policy cases proving 429/5xx/network errors retry at most once and schema-validation errors do not retry.

- [x] **Step 2: Run tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_scheduler.py tests/test_question_curation_graph.py tests/test_curation_work_items.py tests/test_checkpoint_serialization.py
```

Expected: scheduler is missing and Graph peak concurrency remains one.

- [x] **Step 3: Implement the bounded wave scheduler**

Use an asyncio semaphore and `gather(return_exceptions=True)`. Wait for every started worker before returning normal failures; do not let one Provider exception discard sibling successes. Re-raise outer `CancelledError` after worker cleanup so pause can finish promptly.

Normalize error codes without Provider body text. Return completed IDs in input order and failed tuples in input order, independent of completion order.

- [x] **Step 4: Refactor the Graph into planning and wave nodes**

Replace `discover_next`/`enrich_next` serial loops with bounded wave nodes:

```text
plan_sections
  -> discover_wave <-> remaining discovery
  -> plan_enrichment
  -> enrich_wave <-> remaining enrichment
  -> reduce_candidates
```

Persist deterministic seed units as completed `processor_kind='deterministic'` Work Items without incrementing model attempt count. Model workers claim and commit independently. Catch `asyncio.CancelledError` inside each active worker, call `interrupt_running_curation_work_items` for its item, then re-raise.

When a final 429/overload error occurs, atomically set the Batch concurrency limit to 1 before failing the Execution. Later resume reads the persisted limit; the reduction lasts only for that Batch, and a newly created Batch starts at 3.

- [x] **Step 5: Remove serial candidate dependencies and add provisional counts**

For each enrichment unit, pass current seeds, their referenced sections, and at most 20 deterministically prefiltered active-question titles. Do not append earlier enrichment outputs. After every wave, compute generated count from completed enrichment output and return monotonic progress.

Final reduction remains the only creator of formal candidates and continues to merge high-confidence duplicates and cap the result at 200.

- [x] **Step 6: Run focused verification and commit**

Run the Task 4 command again. Expected: peak concurrency is exactly 3 when six tasks are ready, sibling success survives one failure, cancellation leaves no running items, and checkpoint serialization passes. Run `git diff --check`.

```bash
git add backend/app/review/curation_scheduler.py backend/app/graphs/question_curation.py backend/app/review/repository.py backend/app/application/execution_service.py backend/tests/test_curation_scheduler.py backend/tests/test_question_curation_graph.py backend/tests/test_curation_work_items.py backend/tests/test_checkpoint_serialization.py
git commit -m "feat(review): run curation work with bounded concurrency"
```

Reviewer gate: inspect task cancellation and exception aggregation; prove successful output is committed before a wave-level error and no concurrent worker can overwrite a completed item.

---

### Task 5: Add Pause, Resume, Terminate, Timing, and Provisional APIs

**Files:**

- Modify: `backend/app/review/application.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/api/routes_review.py`
- Test: `backend/tests/test_curation_session_api.py`
- Test: `backend/tests/test_review_api_restart.py`
- Test: `backend/tests/test_agent_routes_v2.py`

**Interfaces:**

- Consumes: Task 2 repository control/timing APIs and Task 4 provisional Work Item outputs.
- Produces:

```python
class ControlCurationSessionCommand(ReviewModel):
    expected_batch_version: int = Field(ge=1)

async def pause_curation_session(session_id: str, *, expected_batch_version: int, idempotency_key: str) -> dict[str, Any]: ...
async def resume_curation_session(session_id: str, *, expected_batch_version: int, idempotency_key: str) -> dict[str, Any]: ...
async def terminate_curation_session(session_id: str, *, expected_batch_version: int, idempotency_key: str) -> dict[str, Any]: ...
```

The route reads `idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]`; only `expectedBatchVersion` is sent in the JSON body. The curation resource returns Batch status/version, extended progress, timing, controls, and bounded provisional candidates.

- [x] **Step 1: Write failing API, race, and restart tests**

Cover:

```python
paused = await client.post(
    f"/api/review/curation-sessions/{session_id}/pause",
    headers={"Idempotency-Key": "pause-request-0001"},
    json={"expectedBatchVersion": version},
)
assert paused.status_code == 202
assert paused.json()["batchStatus"] == "paused"
assert paused.json()["controls"] == {
    "canPause": False, "canResume": True, "canTerminate": True
}

resumed = await client.post(
    f"/api/review/curation-sessions/{session_id}/resume",
    headers={"Idempotency-Key": "resume-request-0001"},
    json={"expectedBatchVersion": paused.json()["batchVersion"]},
)
assert resumed.json()["executionId"] != old_execution_id
assert resumed.json()["activeBatchId"] == old_batch_id
```

Also test duplicate idempotency keys, stale version 409, terminated resume 409, pause-vs-complete race, current/cumulative timing, provisional candidates hidden from normal candidate endpoints, legacy `/retry`, SSE replay, and restart conversion to interrupted/paused/terminated.

- [x] **Step 2: Run tests and confirm RED**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_agent_routes_v2.py
```

Expected: endpoints/resources are missing and restart leaves the Batch projection generating.

- [x] **Step 3: Implement domain control methods**

For pause/terminate, persist control receipt first, publish a safe control event, call `AgentExecutionService.cancel`, interrupt any remaining running Work Items, and finalize the Batch/Session state. While `status='generating'` and `control_intent='pause'`, project the transient UI stage as `pausing`; it is not a durable Batch status. If natural completion already won the version/state predicate, return the completed resource rather than overwriting it.

For resume, validate Batch status, prepare a new Execution with the same immutable input, call `resume_curation_batch`, insert an attempt row, and only then start the Graph. The old `/retry` uses a deterministic compatibility key based on the failed Execution and delegates to resume.

Initial curation creation must record the initial Batch attempt. Graph failure uses a repository method that atomically marks Batch/Session failed without destroying completed Work Items.

- [x] **Step 4: Implement startup reconciliation and safe events**

Extend the product event allowlist with `curation.control.changed`. Payload is limited to `resourceId`, `batchId`, `status`, `operation`, and `version`.

At Workspace startup, reconcile interrupted executions and domain tasks before accepting requests. Do not automatically resume Provider calls.

- [x] **Step 5: Project timing, controls, and provisional candidates**

Add resource models:

```python
class CurationTimingResource(ReviewModel):
    current_elapsed_ms: int = Field(ge=0)
    cumulative_elapsed_ms: int = Field(ge=0)

class CurationControlsResource(ReviewModel):
    can_pause: bool
    can_resume: bool
    can_terminate: bool

class ProvisionalCandidateResource(ReviewModel):
    id: str
    title: str
    question_text: str
    source_refs: list[str]
```

Derive provisional IDs from `work_item_id + ordinal`, cap the resource at 200, and never create drafts or return publish controls for these items. `active_workers` is the current count of running Work Items, not a frontend guess.

- [x] **Step 6: Run focused backend verification and commit**

Run the Task 5 command again plus:

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_question_curation_graph.py tests/test_curation_work_items.py tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_agent_routes_v2.py
```

Expected: all control, race, resource, restart, and existing Agent route tests pass. Run compileall and `git diff --check`.

```bash
git add backend/app/review/application.py backend/app/application/execution_service.py backend/app/application/session_service.py backend/app/application/workspace_runtime.py backend/app/schemas/review.py backend/app/api/routes_review.py backend/tests/test_curation_session_api.py backend/tests/test_review_api_restart.py backend/tests/test_agent_routes_v2.py
git commit -m "feat(review): control and resume curation tasks"
```

Reviewer gate: stop the process between persisted control intent and Execution cancellation, restart, and verify the resulting Batch state is deterministic with no active orphan.

---

### Task 6: Build the Real-Time Curation Control and Preview UI

**Files:**

- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.tsx`
- Create: `frontend/src/features/review/CurationProvisionalList.tsx`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/review/reviewApi.test.ts`
- Test: `frontend/src/features/review/CurationRuntimePanel.test.tsx`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Test: `frontend/src/features/agent/useAgentEvents.test.tsx`

**Interfaces:**

- Consumes: Task 5 camelCase control/timing/provisional resource.
- Produces:

```typescript
pauseCurationSession(id: string, expectedBatchVersion: number, idempotencyKey: string): Promise<CurationSession>
resumeCurationSession(id: string, expectedBatchVersion: number, idempotencyKey: string): Promise<CurationSession>
terminateCurationSession(id: string, expectedBatchVersion: number, idempotencyKey: string): Promise<CurationSession>
```

Each frontend function serializes only `{ expectedBatchVersion }` in the body and sends the key as the `Idempotency-Key` header.

- [x] **Step 1: Run the required UI design gate and write failing interaction tests**

Use `ui-ux-pro-max` against the existing R2 semantic tokens. Keep the accepted layout: progress card is primary, pause is visible, terminate is separated as a dangerous secondary action, and provisional items are explicitly read-only.

With Vitest fake timers, assert:

```typescript
vi.useFakeTimers();
vi.setSystemTime(new Date("2026-07-22T00:02:31+08:00"));
render(<CurationRuntimePanel session={runningSession} />);
expect(screen.getByText("本次运行 2 分 31 秒")).toBeInTheDocument();
vi.advanceTimersByTime(1000);
expect(screen.getByText("本次运行 2 分 32 秒")).toBeInTheDocument();
```

Also test terminal freeze, paused time not increasing, cumulative time, pause/resume/terminate callbacks, terminate confirmation, distinct semantic classes, active worker/candidate counts, provisional preview without edit/publish buttons, SSE refresh, and reload hydration.

- [x] **Step 2: Run frontend tests and confirm RED**

```bash
cd frontend && npm test -- --run src/features/review/reviewApi.test.ts src/features/review/CurationRuntimePanel.test.tsx src/features/review/QuestionCatalog.test.tsx src/features/agent/useAgentEvents.test.tsx
```

Expected: new types/functions/controls are missing and the existing test still asserts no elapsed time.

- [x] **Step 3: Implement API/types and SSE reconciliation**

Extend `CurationStage` and `QuestionBatch.status`; add exact resource fields from Task 5. Use the existing `commandId()` UUID helper for control idempotency keys. Add `curation.control.changed` to the event union and refresh the selected session on control/progress/terminal events.

- [x] **Step 4: Implement the elapsed clock and controls**

In `CurationRuntimePanel`, tick local `now` once per second only while Batch status is generating. Compute display time from server timing plus the latest execution start; freeze on non-running states. Do not put the ticking text in an assertive live region.

Render:

```text
generating   → 暂停整理 + dangerous 终止整理
pausing      → 正在暂停…
paused       → 继续整理 + dangerous 终止整理
failed       → 继续整理 + dangerous 终止整理
interrupted  → 继续整理 + dangerous 终止整理
terminated   → 已终止，无恢复按钮
```

Keep command/chat Execution cancellation on the existing generic endpoint; use domain endpoints only for the initial/long-running curation Batch.

- [x] **Step 5: Implement read-only provisional preview and semantic styles**

`CurationProvisionalList` displays title, short question text, evidence count, and “处理中预览”. It must not reuse formal candidate action props. Use existing surface, border, primary, warning, danger, focus, spacing, and motion tokens; add no raw colors.

- [x] **Step 6: Run frontend verification and commit**

Run the Task 6 test command, then:

```bash
cd frontend && npm run typecheck && npm run build
```

Expected: all focused tests, TypeScript, and production build pass; only the existing bundle-size warning may remain. Run `git diff --check`.

```bash
git add frontend/src/features/review/reviewTypes.ts frontend/src/features/review/reviewApi.ts frontend/src/features/review/QuestionCatalog.tsx frontend/src/features/review/CurationRuntimePanel.tsx frontend/src/features/review/CurationProvisionalList.tsx frontend/src/features/agent/useAgentEvents.ts frontend/src/app/global.css frontend/src/features/review/reviewApi.test.ts frontend/src/features/review/CurationRuntimePanel.test.tsx frontend/src/features/review/QuestionCatalog.test.tsx frontend/src/features/agent/useAgentEvents.test.tsx
git commit -m "feat(review): show and control curation progress"
```

Reviewer gate: inspect 390px and desktop layouts, keyboard focus, reduced motion, screen-reader announcements, and confirm paused/failed/terminated never share the same visual treatment.

---

### Task 7: Cross-Layer Performance, Recovery, and Acceptance Gate

**Files:**

- Modify: `backend/tests/test_curation_session_api.py`
- Modify: `backend/tests/test_question_curation_graph.py`
- Modify: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Update locally: `docs/verification/r2-complete-review-agent.md`
- Update: `task_plan.md`
- Update: `findings.md`
- Update: `progress.md`

**Interfaces:**

- Consumes: all previous Tasks.
- Produces: one verified R2 curation slice with measured planner/call reduction, bounded concurrency, pause/resume/terminate, progressive preview, real-time timing, and Trace v2 evidence.

- [x] **Step 1: Add a deterministic cross-layer scenario**

Create a fake Provider scenario that starts at least six enrichment items, blocks three concurrently, completes two, fails one, pauses the resumed attempt, restarts the Runtime, resumes again, and finishes.

Assert:

```python
assert peak_provider_calls == 3
assert completed_item_invocations_after_resume == completed_item_invocations_before_resume
assert final_batch.status == "review_pending"
assert repository.list_curation_work_items(batch.id, stage="enrichment")[-1].status == "completed"
assert all(row.status != "running" for row in repository.list_curation_work_items(batch.id))
```

Add the frontend contract scenario that hydrates an interrupted session, resumes it, receives out-of-order progress events, and never displays a lower completed count.

- [x] **Step 2: Run the affected cross-layer tests**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_curation_sections.py tests/test_curation_planner.py tests/test_curation_scheduler.py tests/test_curation_work_items.py tests/test_question_curation_graph.py tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_agent_trace_writer.py tests/test_agent_trace_middleware.py
cd ../frontend && npm test -- --run src/features/review/QuestionCatalog.test.tsx src/features/review/CurationRuntimePanel.test.tsx src/features/review/reviewApi.test.ts src/features/agent/useAgentEvents.test.tsx
```

Expected: all affected cross-layer tests pass.

- [x] **Step 3: Run the one post-integration full regression**

```bash
cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q
cd ../frontend && npm test -- --run && npm run typecheck && npm run build
```

Expected: complete backend and frontend suites pass; build succeeds. Record exact counts and timestamp in local verification.

- [x] **Step 4: Complete local planner and browser acceptance without implicit data export**

Run the pure planner against the user-selected local material and record only counts/digests. Start the app and verify:

1. elapsed time increments in Beijing-local UI;
2. provisional count appears before final completion;
3. pause reaches paused and freezes active elapsed time;
4. refresh preserves paused state;
5. resume keeps completed counts and creates a new Execution;
6. terminate removes resume and a resume API call returns 409;
7. Trace v2 shows matching UTC/Beijing instants.

Do not send the original source to a real Provider unless the user explicitly authorizes that exact run. If authorized, record redacted counts, model ID, peak concurrency, time-to-first-preview, total active time, and retry counts; do not copy prompt/source/response bodies into verification.

- [x] **Step 5: Update project status and final local guide**

Update root planning files with:

- product status and fresh verification evidence;
- maturity boundary: single-process bounded scheduler, not distributed jobs;
- ownership status;
- next product task, returning to R3 Task 8;
- non-blocking user exercise.

Reshape the relevant section of `docs/verification/r2-complete-review-agent.md` into the manual flow for timing, pause, resume, terminate, provisional preview, and Trace local time. Keep `docs/verification/` unstaged.

- [x] **Step 6: Run final diff/document checks and commit**

Run:

```bash
git diff --check
python3 -m compileall -q backend/app backend/tests
```

Confirm `docs/my_idea.md` is unchanged, `docs/verification/r2-complete-review-agent.md` is updated locally, and only intended formal/project status files are staged.

```bash
git add backend/tests/test_curation_session_api.py backend/tests/test_question_curation_graph.py frontend/src/features/review/QuestionCatalog.test.tsx task_plan.md findings.md progress.md
git commit -m "test(review): verify resumable curation workflow"
```

Reviewer gate: compare every acceptance criterion in `docs/superpowers/specs/2026-07-22-r2-curation-long-task-control-and-performance-design.md` with code, tests, browser evidence, and local verification. Any unchecked real-Provider scenario remains explicitly pending and cannot be reported as passed.

---

## Checkpoints

- **Checkpoint A — Durable control foundation:** Tasks 1–2 complete; Trace time and Batch state are migration-safe and independently verified.
- **Checkpoint B — Fast recoverable backend:** Tasks 3–5 complete; structure-aware planning, concurrency, control APIs, restart recovery, timing, and provisional resources work.
- **Checkpoint C — User-visible slice:** Task 6 complete; the page exposes elapsed time and correct pause/resume/terminate behavior.
- **Checkpoint D — Acceptance:** Task 7 complete; full regression, browser evidence, local verification, and root status are synchronized.

## Expected Product Boundary After Completion

The product will support reliable single-process long-running curation with durable Batch/Work Item recovery and bounded concurrent Provider calls. It will not yet provide distributed workers, background scheduling across devices, priority queues, or guaranteed Provider-side cancellation. R3 Task 8 resumes after this slice; R3 `profile.ingest` adopts the same state semantics when its UI/control slice is implemented.
