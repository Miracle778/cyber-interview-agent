# R2 Cancellable Streaming Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every interactive curation command a durable, model-selectable, cancellable execution with replayable SSE output, and add safe bulk publication to the candidate artifact card.

**Architecture:** Extend the existing `AgentExecutionService` rather than creating a second runtime: command submission prepares a durable execution and returns `202`, then a domain-owned background handler performs `Plan -> Validate -> Execute` while the runtime owns task cancellation and terminal state. The existing session event stream remains the only SSE channel; model configuration is snapshotted per execution, while curation command and bulk-publication repositories retain domain-specific state and idempotency.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, LangChain/LangGraph model adapters, Pydantic, React 19, TypeScript, TanStack Query, native EventSource, Vitest/Testing Library, pytest.

## Global Constraints

- Work only in `/private/tmp/cyber-interview-agent-r2-ui-design` on `codex/r2-complete-review-agent`; do not switch the main repository away from `main`.
- Preserve the accepted `Plan -> Validate -> Execute` command boundary; models never execute publication side effects directly.
- Keep `GET /api/agent/sessions/{sessionId}/events` as the only product SSE channel.
- Do not fake streaming by slicing complete text; only real natural-language model chunks may produce `assistant.delta`.
- Structured classifier JSON remains internal; expose progress and the resolved business response, not raw JSON tokens.
- A stop request cancels only the current execution. Persisted user input remains visible; partial assistant output never enters formal context.
- A started single-question publication transaction completes; cancellation prevents later items and never rolls back successful items.
- Model and reasoning selection are immutable execution snapshots; UI changes affect only the next execution.
- Default runtime and acceptance environment has no Langfuse dependency.
- Use targeted tests during Tasks 1–4. Run the full backend suite, full frontend suite/build, browser acceptance and documentation gate only in Task 4.
- Use `ui-ux-pro-max` exactly once at the start of Task 4, recording its recommendations and stopping after the UI implementation matches the accepted interaction design.
- Do not create subagents: the state machine, API, persistence and UI touch shared contracts and should remain under one owner.

---

## File Responsibility Map

### Runtime and persistence

- Create `backend/app/db/migrations/runtime/010_cancellable_interactions.sql`: add execution cancellation/configuration fields, command-to-execution linkage, curation session preferences and bulk-publication tables.
- Modify `backend/app/application/session_service.py`: expose execution configuration and cancellation request state; add atomic cancel-request and recovery operations.
- Modify `backend/app/application/execution_service.py`: run domain-owned background handlers under the existing task registry; cancel cooperatively and publish terminal events.
- Modify `backend/app/application/workspace_runtime.py`: inject per-execution curation model factory and recover unfinished interactions.
- Modify `backend/app/application/event_projector.py`: preserve genuine model chunks only; no artificial chunking.

### Curation command and publication domain

- Modify `backend/app/agents/curation_command.py`: accept a `ModelOverride` for the classifier while leaving the summarizer on its system role binding.
- Modify `backend/app/application/graph_factory.py`: build command models from an execution snapshot.
- Modify `backend/app/review/models.py`: add command submission, session preference and bulk-publication records.
- Modify `backend/app/review/repository.py`: persist command lifecycle, preferences, bulk operation/items and idempotent state transitions.
- Modify `backend/app/review/application.py`: split synchronous command handling into prepare/background phases and implement bulk preflight/run/retry.
- Modify `backend/app/schemas/review.py`: define asynchronous command, model preference and bulk-publication API resources.
- Modify `backend/app/api/routes_review.py`: return accepted executions immediately and expose bulk-publication endpoints.

### Frontend

- Modify `frontend/src/features/agent/agentTypes.ts`: expose cancellation request and streaming event payloads.
- Modify `frontend/src/features/agent/useAgentEvents.ts`: maintain execution-scoped delta buffers and terminal state without duplicate replay.
- Modify `frontend/src/features/review/reviewTypes.ts`: define model preference, accepted command and bulk-publication resources.
- Modify `frontend/src/features/review/reviewApi.ts`: submit model snapshots and call preflight/start/retry/cancel APIs.
- Modify `frontend/src/features/review/QuestionCatalog.tsx`: own the selected execution, SSE lifecycle, model preference and bulk mutations.
- Modify `frontend/src/features/review/CurationConversation.tsx`: render model controls, real stop state, streaming messages and one-click publication.
- Modify `frontend/src/features/review/CurationRuntimePanel.tsx`: show actual execution/model/interruption facts and recovery actions.
- Modify review CSS in the existing stylesheet that owns `.curation-*` and `.review-chat-*` selectors; locate it with `rg -n "curation-composer|curation-artifacts" frontend/src` before editing.

### Tests and evidence

- Modify `backend/tests/test_runtime_migrations.py`, `test_agent_routes_v2.py`, `test_curation_session_api.py`, `test_review_repository.py`, `test_agent_restart_v2.py`, and `test_event_projector.py`.
- Modify `frontend/src/features/agent/useAgentEvents.test.tsx`, `frontend/src/features/review/reviewApi.test.ts`, `CurationConversation.test.tsx`, and `QuestionCatalog.test.tsx`.
- Modify `task_plan.md`, `findings.md`, `progress.md`, and local `docs/verification/r2.md` only after the corresponding implementation evidence exists.

---

### Task 1: Durable execution configuration and cooperative cancellation

**Files:**
- Create: `backend/app/db/migrations/runtime/010_cancellable_interactions.sql`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_agent_routes_v2.py`
- Test: `backend/tests/test_agent_restart_v2.py`

**Interfaces:**
- Produces: `ExecutionConfiguration(provider_model_id: str | None, reasoning_effort: ReasoningEffort)`.
- Produces: `ExecutionRecord.configuration`, `ExecutionRecord.cancel_requested_at`, and `ExecutionRecord.cancellation_requested`.
- Produces: `ProductRepository.request_execution_cancel(execution_id) -> ExecutionRecord`, an atomic, idempotent cancel request.
- Produces: `ExecutionCancellation.raise_if_requested() -> None`, `ExecutionCancellation.critical_section()` and `AgentExecutionService.run_background(execution, handler)`.
- Consumes later: Task 2 prepares a command execution and passes a domain handler to `run_background`; Task 3 uses the same primitive for bulk publication.

- [x] **Step 1: Add failing migration and repository tests**

Add tests that require migration version 10 and round-trip explicit configuration/cancellation state:

```python
def test_cancellable_interaction_migration_adds_execution_state(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
    assert {"configuration_json", "cancel_requested_at"} <= columns
    versions = [row[0] for row in connection.execute(
        "SELECT version FROM runtime_schema_migrations ORDER BY version"
    )]
    assert versions[-1] == 10


def test_execution_configuration_and_cancel_request_round_trip(repository) -> None:
    execution = repository.create_execution(
        "session-1",
        input={"operation": "curation.command"},
        model_bindings={},
        configuration={
            "providerModelId": "model-1",
            "reasoningEffort": "medium",
        },
    )
    requested = repository.request_execution_cancel(execution.id)
    repeated = repository.request_execution_cancel(execution.id)
    assert requested.cancel_requested_at is not None
    assert repeated.cancel_requested_at == requested.cancel_requested_at
    assert requested.configuration.provider_model_id == "model-1"
```

- [x] **Step 2: Run targeted tests and verify the expected failures**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_runtime_migrations.py tests/test_agent_routes_v2.py tests/test_agent_restart_v2.py --tb=short
```

Expected: failures report missing migration version 10, missing execution columns, or missing repository methods.

- [x] **Step 3: Add migration 010 and typed execution configuration**

Create the migration with additive columns and domain tables needed by Tasks 2–3. Keep the existing database status constraint; API `accepted` maps to queued/prepared work and API `cancelling` is derived from `status == running` plus `cancel_requested_at`:

```sql
ALTER TABLE agent_runs
    ADD COLUMN configuration_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(configuration_json) AND json_type(configuration_json) = 'object'
    );

ALTER TABLE agent_runs ADD COLUMN cancel_requested_at TEXT;

ALTER TABLE review_curation_command_receipts
    ADD COLUMN execution_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL;
ALTER TABLE review_curation_command_receipts
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'accepted' CHECK (
        lifecycle_status IN (
            'accepted', 'running', 'completed', 'partial_failure',
            'failed', 'cancelled', 'interrupted'
        )
    );

ALTER TABLE review_curation_sessions ADD COLUMN preferred_model_id TEXT;
ALTER TABLE review_curation_sessions
    ADD COLUMN preferred_reasoning_effort TEXT NOT NULL DEFAULT 'none' CHECK (
        preferred_reasoning_effort IN ('none', 'low', 'medium', 'high')
    );
```

Also create `review_bulk_publications` and `review_bulk_publication_items` with operation/item status checks, execution linkage and unique `(operation_id, candidate_id)`; Task 3 will populate them.

In `session_service.py`, add:

```python
ReasoningEffort = Literal["none", "low", "medium", "high"]

@dataclass(frozen=True, slots=True)
class ExecutionConfiguration:
    provider_model_id: str | None = None
    reasoning_effort: ReasoningEffort = "none"

@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    # existing fields remain
    configuration: ExecutionConfiguration
    cancel_requested_at: str | None

    @property
    def cancellation_requested(self) -> bool:
        return self.cancel_requested_at is not None
```

Extend `create_execution(session_id: str, *, input: dict[str, Any], model_bindings: dict[str, str], configuration: dict[str, Any] | None = None, execution_id: str | None = None)` and `_execution(row)` to validate the stored JSON. Add `request_execution_cancel` as one conditional SQL update that preserves the first timestamp and returns terminal records unchanged.

- [x] **Step 4: Generalize the task registry for domain handlers**

Add a narrow runtime protocol without importing review-domain types:

```python
class ExecutionCancelled(asyncio.CancelledError):
    pass

@dataclass(frozen=True, slots=True)
class ExecutionCancellation:
    repository: ProductRepository
    execution_id: str
    control: ExecutionControl

    def raise_if_requested(self) -> None:
        if self.repository.get_execution(self.execution_id).cancellation_requested:
            raise ExecutionCancelled()

    @contextmanager
    def critical_section(self):
        self.control.interruptible = False
        try:
            yield
        finally:
            self.control.interruptible = True

ExecutionHandler = Callable[[ExecutionRecord, ExecutionCancellation], Awaitable[None]]
```

Implement `run_background(execution, handler)` by registering an `ExecutionControl(task, interruptible=True)` in the existing task registry. The wrapper must call the handler, transition running to completed only when the handler has not already chosen a terminal state, map `ExecutionCancelled`/`asyncio.CancelledError` to cancelled, and map other exceptions to failed while preserving the current graph `_execute` behavior.

Change `cancel()` so it first calls `request_execution_cancel` and publishes `execution.cancelling`. If the registered control is interruptible (for example, currently awaiting a model stream), cancel and await the task immediately. If it is inside `critical_section` (for example, a single-question publication transaction), leave the task running; the handler exits the section, checks the persisted request and stops at the next safe point. Publish `execution.cancelled` exactly once after the atomic terminal transition. Add `execution.cancelling` to the allowed event set.

- [x] **Step 5: Cover cancellation races and restart recovery**

Add async tests using `asyncio.Event` barriers:

```python
@pytest.mark.asyncio
async def test_cancel_request_wins_before_handler_safe_point(runtime):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(execution, cancellation):
        entered.set()
        await release.wait()
        cancellation.raise_if_requested()

    session = runtime._repository.get_session("session-1")
    execution = await runtime.prepare(
        session,
        input={"operation": "test.blocking"},
        project_input_message=False,
        configuration={},
    )
    runtime.run_background(execution, handler)
    await entered.wait()
    cancelled = await runtime.cancel(execution.id)
    assert cancelled.status == "cancelled"


def test_restart_preserves_persisted_cancel_request(repository):
    session = repository.create_session(
        workspace_id="w1",
        kind="question.curate",
        title="Cancellation recovery",
        session_id="session-1",
    )
    execution = repository.create_execution(
        session.id,
        input={"operation": "curation.command"},
        model_bindings={},
        configuration={},
    )
    repository.request_execution_cancel(execution.id)
    recovered = repository.interrupt_running()
    assert repository.get_execution(execution.id).status == "cancelled"
```

Also assert a completed execution remains completed when cancel is called afterward, and `execution.cancelled` is not duplicated.

- [x] **Step 6: Run targeted runtime tests**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_runtime_migrations.py tests/test_agent_routes_v2.py tests/test_agent_restart_v2.py --tb=short
```

Expected: all selected tests pass.

- [x] **Step 7: Commit Task 1**

```bash
git add backend/app/db/migrations/runtime/010_cancellable_interactions.sql \
  backend/app/application/session_service.py \
  backend/app/application/execution_service.py \
  backend/app/application/workspace_runtime.py \
  backend/tests/test_runtime_migrations.py \
  backend/tests/test_agent_routes_v2.py \
  backend/tests/test_agent_restart_v2.py
git commit -m "feat(runtime): add cancellable domain executions"
```

---

### Task 2: Asynchronous curation commands, model snapshots and genuine SSE

**Files:**
- Modify: `backend/app/agents/curation_command.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/application/event_projector.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/api/routes_review.py`
- Test: `backend/tests/test_curation_command_agent.py`
- Test: `backend/tests/test_event_projector.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_curation_session_api.py`
- Test: `backend/tests/test_review_api_restart.py`

**Interfaces:**
- Consumes: `AgentExecutionService.run_background`, `ExecutionCancellation`, execution configuration and cancel events from Task 1.
- Produces: `AcceptedCurationCommandResource(command_id, execution_id, status)`.
- Produces: `ReviewApplication.submit_curation_command(session_id: str, *, text: str, summary_version: int, idempotency_key: str, provider_model_id: str, reasoning_effort: ReasoningEffort) -> dict[str, Any]` matching `AcceptedCurationCommandResource`.
- Produces: `ReviewApplication.retry_curation_command(command_id) -> AcceptedCurationCommandResource` and `abandon_curation_command(command_id)`.
- Produces: `CurationCommandResponder.astream(text: str, assembled: AssembledContext, *, context: AgentContext) -> AsyncIterator[AIMessageChunk]` for genuinely generated user-facing responses.
- Produces: session resource fields `preferredModelId`, `preferredReasoningEffort`, and latest command execution state.

- [x] **Step 1: Write failing asynchronous API and idempotency tests**

Replace assumptions that POST waits for a completed receipt. The route must return before a blocking classifier is released:

```python
@pytest.mark.asyncio
async def test_curation_command_returns_accepted_before_classifier_finishes(api, application):
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingClassifier:
        async def classify(self, assembled, *, context):
            entered.set()
            await release.wait()
            return CurationCommandPlan(response="已理解")

    review = application.locate_review_session(session_id)
    review.curation_command_models = dataclasses.replace(
        review.curation_command_models,
        classifier=BlockingClassifier(),
    )

    response = await client.post(
        f"/api/review/curation-sessions/{session_id}/commands",
        json={
            "text": "这题发布吧",
            "summaryVersion": 1,
            "idempotencyKey": "command-key-1",
            "providerModelId": "model-1",
            "reasoningEffort": "medium",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert response.json()["executionId"]
    await entered.wait()
    release.set()


@pytest.mark.asyncio
async def test_repeated_command_key_returns_same_execution(client):
    payload = {
        "text": "总结候选题",
        "summaryVersion": 1,
        "idempotencyKey": "same-key-0001",
        "providerModelId": "model-1",
        "reasoningEffort": "none",
    }
    first = await client.post(
        f"/api/review/curation-sessions/{session_id}/commands", json=payload
    )
    second = await client.post(
        f"/api/review/curation-sessions/{session_id}/commands", json=payload
    )
    assert second.json() == first.json()
```

Add repository assertions that command lifecycle and execution ID survive reconnect/restart.

- [x] **Step 2: Run the focused command tests and verify they fail**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_curation_session_api.py tests/test_review_repository.py tests/test_review_api_restart.py --tb=short
```

Expected: current POST blocks until interpretation completes and the accepted resource fields do not exist.

- [x] **Step 3: Split command prepare from background execution**

Rename the public synchronous entry point to `submit_curation_command` and move current interpretation/business logic into `_run_curation_command`. The prepare path must:

```python
async def submit_curation_command(
    self,
    session_id: str,
    *,
    text: str,
    summary_version: int,
    idempotency_key: str,
    provider_model_id: str,
    reasoning_effort: ReasoningEffort,
) -> dict[str, Any]:
    self.validate_model(provider_model_id, reasoning_effort)
    existing = self.repository.find_curation_command_receipt(
        session_id=session_id,
        idempotency_key=idempotency_key,
        text=text,
        summary_version=summary_version,
    )
    if existing is not None:
        return self._accepted_command_resource(existing)
    execution = await self.executions.prepare(
        session,
        input={"operation": "curation.command", "commandId": command.id},
        project_input_message=False,
        configuration={
            "providerModelId": provider_model_id,
            "reasoningEffort": reasoning_effort,
        },
    )
    self.repository.attach_curation_command_execution(command.id, execution.id)
    self.repository.save_curation_preference(session_id, provider_model_id, reasoning_effort)
    await self.timeline.append(
        session_id=session_id,
        execution_id=execution.id,
        role="user",
        message_kind="text",
        content=text,
        payload={
            "resourceId": command.id,
            "version": summary_version,
            "submittedAt": command.created_at,
        },
    )
    self.executions.run_background(execution, self._curation_command_handler(command.id))
    return self._accepted_command_resource(command)
```

The background handler reloads every record by ID, transitions command lifecycle to running, performs the existing frozen-summary `Plan -> Validate -> Execute`, checks cancellation before model work and each side effect, writes the formal assistant message only after a complete result, and transitions the command lifecycle to the execution terminal outcome.

- [x] **Step 4: Build command models from the execution snapshot**

Change `CurationCommandModels.create` and `ProductionGraphFactory.create_curation_command_models` to accept `interaction_override: ModelOverride`. Apply it to the classifier and a new unstructured responder, while keeping the summarizer on its system binding:

```python
classifier = factory.create(
    AgentSpec(
        role="question_generation",
        execution_name="curation_command_classifier",
        system_prompt=_CLASSIFIER_PROMPT,
        middleware=tuple(middleware),
        response_format=CurationCommandPlan,
    ),
    model_bindings=model_bindings,
    model_override=interaction_override,
    checkpointer=None,
)

responder = factory.create(
    AgentSpec(
        role="question_generation",
        execution_name="curation_command_responder",
        system_prompt=(
            "根据已验证的题库整理上下文回答用户；不得声称已执行任何未提供的操作，"
            "不得自行发布、拒绝或重写题目。"
        ),
        middleware=tuple(middleware),
        response_format=None,
    ),
    model_bindings=model_bindings,
    model_override=interaction_override,
    checkpointer=None,
)
```

Keep the summarizer on `report_summarization`. Inject a callable model factory into `ReviewApplication` so each execution receives its immutable override; do not mutate workspace bindings.

- [x] **Step 5: Project genuine model output without exposing structured JSON**

Keep `AgentEventProjector` limited to actual `AIMessageChunk` text. For the structured classifier, publish `curation.command.interpreting` before invocation and `curation.command.resolved` afterward; do not publish classifier tool/JSON chunks as assistant text.

Add `curation.command.interpreting` to `ProductEventStream._allowed` and to the frontend `EVENT_TYPES` list in Task 4. Every event must retain the execution ID. Reconnection continues from the last accepted numeric cursor through `after`/`Last-Event-ID`, and tests must replay the last delta once to prove client deduplication.

When a plan contains a user-facing free-form `response`, call `CurationCommandResponder.astream`, forward only its `AIMessageChunk` values through the existing projector, accumulate the same chunks, and persist their exact joined text as the formal message after successful completion. Deterministic command results remain templated formal messages and produce no fake deltas. Add tests:

```python
def test_projector_emits_only_real_ai_text_chunks():
    event = projector.project({"type": "messages", "data": (AIMessageChunk(content="你好"), {})})
    assert event[0].type == "assistant.delta"
    assert event[0].payload == {"text": "你好"}


def test_projector_ignores_structured_tool_chunks():
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{
            "name": "publish",
            "args": '{"candidateId":"c1"}',
            "id": "call-1",
            "index": 0,
        }],
    )
    assert projector.project({"type": "messages", "data": (chunk, {})}) == ()
```

- [x] **Step 6: Add cancel, retry and restart API coverage**

Test the full lifecycle:

```python
response = await client.post(
    f"/api/review/curation-sessions/{session_id}/commands",
    json={
        "text": "这道题是否值得发布？",
        "summaryVersion": 1,
        "idempotencyKey": "cancel-command-1",
        "providerModelId": "model-1",
        "reasoningEffort": "low",
    },
)
accepted = response.json()
for _attempt in range(100):
    events = application.replay_events(session_id, after_id=None)
    if any(item.type == "curation.command.interpreting" for item in events):
        break
    await asyncio.sleep(0.01)
else:
    pytest.fail("curation.command.interpreting was not published")
cancelled = await client.post(
    f"/api/agent/executions/{accepted['executionId']}/cancel"
)
assert cancelled.json()["status"] == "cancelled"
detail = (await client.get(
    f"/api/review/curation-sessions/{session_id}"
)).json()
assert any(m["role"] == "user" for m in detail["messages"])
assert not any(
    m["role"] == "assistant" and m["executionId"] == accepted["executionId"]
    and m["messageKind"] == "command_receipt"
    for m in detail["messages"]
)
```

Add restart coverage asserting an unfinished command becomes interrupted, is not automatically executed, and retry creates a new execution linked to the original command/idempotency scope. Add abandon coverage that makes the session immediately usable.

- [x] **Step 7: Run targeted backend command/SSE tests**

Run:

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_curation_command_agent.py \
  tests/test_event_projector.py \
  tests/test_review_repository.py \
  tests/test_curation_session_api.py \
  tests/test_review_api_restart.py --tb=short
```

Expected: all selected tests pass; no test waits on an HTTP request for model completion.

- [x] **Step 8: Commit Task 2**

```bash
git add backend/app/agents/curation_command.py \
  backend/app/application/graph_factory.py \
  backend/app/application/workspace_runtime.py \
  backend/app/application/event_projector.py \
  backend/app/review/models.py backend/app/review/repository.py \
  backend/app/review/application.py backend/app/schemas/review.py \
  backend/app/api/routes_review.py \
  backend/tests/test_curation_command_agent.py \
  backend/tests/test_event_projector.py backend/tests/test_review_repository.py \
  backend/tests/test_curation_session_api.py backend/tests/test_review_api_restart.py
git commit -m "feat(review): run curation commands asynchronously"
```

---

### Task 3: Safe bulk candidate publication

**Files:**
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/api/routes_review.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_curation_session_api.py`
- Test: `backend/tests/test_publication_service.py`

**Interfaces:**
- Consumes: cancellable domain executions from Task 1.
- Produces: `BulkPublicationPreflightResource` with `publishable`, `already_published`, `needs_review`, and `blocked` candidate IDs.
- Produces: `AcceptedBulkPublicationResource(operation_id, execution_id, status)`.
- Produces: `ReviewApplication.preflight_bulk_publication(session_id)` and `start_bulk_publication(session_id, idempotency_key, candidate_ids)`.
- Produces: `retry_bulk_publication(operation_id, idempotency_key)` which targets failed/unprocessed items only.

- [ ] **Step 1: Write failing preflight and partial-result tests**

Add a mixed summary fixture and assert only safe recommendations are selected:

```python
def test_bulk_preflight_selects_only_pending_recommended_candidates(review):
    session_id = create_completed_curation_with_summary(
        review,
        items=(
            candidate_fixture("recommended", status="review_pending", recommendation="recommend_confirm"),
            candidate_fixture("duplicate", status="review_pending", recommendation="link_existing"),
            candidate_fixture("rejected", status="rejected", recommendation="suggest_reject"),
            candidate_fixture("published", status="published", recommendation="recommend_confirm"),
        ),
    )
    result = review.preflight_bulk_publication(session_id)
    assert result.publishable == ("recommended",)
    assert result.already_published == ("published",)
    assert set(result.needs_review) == {"duplicate", "rejected"}
```

Define `candidate_fixture(identifier, *, status, recommendation)` in this test module to return the exact candidate/summary input tuple used by `create_completed_curation_with_summary`; define that helper to create one curation session, one completed batch, save each candidate with `ReviewRepository.save_candidate`, and replace the curation summary with the supplied recommendations. These helpers must use fixed IDs from the snippet so assertions do not depend on UUID order.

Add an async cancellation test where item one commits, cancellation is requested, and item two remains unprocessed. Add a retry test that does not republish item one and uses the same candidate-level idempotency key.

- [ ] **Step 2: Run targeted publication tests and verify they fail**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_review_repository.py tests/test_curation_session_api.py tests/test_publication_service.py --tb=short
```

Expected: bulk preflight/operation methods and routes are missing.

- [ ] **Step 3: Implement typed preflight and operation persistence**

Classify every current summary item from server-owned candidate status and recommendation; never trust a client-provided “safe” flag:

```python
@dataclass(frozen=True, slots=True)
class BulkPublicationPreflight:
    session_id: str
    summary_version: int
    publishable: tuple[str, ...]
    already_published: tuple[str, ...]
    needs_review: tuple[str, ...]
    blocked: tuple[str, ...]
```

Persist one operation row and one immutable item row per selected candidate. Derive candidate idempotency keys as `bulk-publish:{operation_id}:{candidate_id}` and enforce unique operation/candidate pairs.

- [ ] **Step 4: Execute items at cancellation-safe boundaries**

Use the runtime handler from Task 1:

```python
async def _run_bulk_publication(execution, cancellation, operation_id):
    for item in repository.list_bulk_publication_items(operation_id):
        cancellation.raise_if_requested()
        repository.mark_bulk_item_running(item.id)
        try:
            with cancellation.critical_section():
                await self._publish_curation_candidate(
                    item.candidate_id,
                    idempotency_key=item.idempotency_key,
                )
        except Exception as error:
            code = str(getattr(error, "code", "publication_failed"))
            repository.fail_bulk_item(item.id, code=code)
        else:
            repository.complete_bulk_item(item.id)
        cancellation.raise_if_requested()
    repository.complete_bulk_operation_from_items(operation_id)
```

Publish item progress via `publication.changed` with operationId, candidateId and status. Retry constructs a new execution over only `failed` and `pending` items; completed items remain immutable.

- [ ] **Step 5: Add preflight/start/retry routes**

Expose:

```text
GET  /api/review/curation-sessions/{sessionId}/bulk-publication/preflight
POST /api/review/curation-sessions/{sessionId}/bulk-publications
POST /api/review/bulk-publications/{operationId}/retry
GET  /api/review/bulk-publications/{operationId}
```

Start requests include `summaryVersion`, server-returned candidate IDs and an idempotency key. Re-run preflight inside POST and return `409` if the summary or eligibility changed between confirmation and execution.

- [ ] **Step 6: Run targeted publication tests**

Run:

```bash
cd backend
.venv/bin/pytest -q tests/test_review_repository.py tests/test_curation_session_api.py tests/test_publication_service.py --tb=short
```

Expected: all selected tests pass, including partial success, cancellation and retry idempotency.

- [ ] **Step 7: Commit Task 3**

```bash
git add backend/app/review/models.py backend/app/review/repository.py \
  backend/app/review/application.py backend/app/schemas/review.py \
  backend/app/api/routes_review.py backend/tests/test_review_repository.py \
  backend/tests/test_curation_session_api.py backend/tests/test_publication_service.py
git commit -m "feat(review): add safe bulk candidate publication"
```

---

### Task 4: Streaming composer UX, browser acceptance and final evidence

**Files:**
- Modify: `frontend/src/features/agent/agentTypes.ts`
- Modify: `frontend/src/features/agent/agentApi.ts`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Modify: `frontend/src/features/review/CurationConversation.tsx`
- Modify: `frontend/src/features/review/CurationRuntimePanel.tsx`
- Modify: stylesheet located by `rg -l "curation-composer|curation-artifacts" frontend/src`
- Test: `frontend/src/features/agent/agentApi.test.ts`
- Test: `frontend/src/features/agent/useAgentEvents.test.tsx`
- Test: `frontend/src/features/review/reviewApi.test.ts`
- Test: `frontend/src/features/review/CurationConversation.test.tsx`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify local: `docs/verification/r2.md`

**Interfaces:**
- Consumes: accepted command, execution cancel, SSE and bulk-publication contracts from Tasks 1–3.
- Produces: `useAgentEvents` result fields `streamingByExecution`, `executionStateById`, and existing replay-safe event list.
- Produces: a composer that sends the selected model snapshot, swaps Send for Stop, recovers after refresh, and renders partial/final messages correctly.
- Produces: bulk preflight confirmation and per-file progress/retry UI.

- [ ] **Step 1: Invoke `ui-ux-pro-max` once and record actionable constraints**

Read `/Users/miracle778/.codex/skills/ui-ux-pro-max/SKILL.md` completely, use its repository search script for a desktop three-column Agent workspace with compact composer controls, destructive stop action, accessible progress, and bounded artifact lists. Record only the chosen recommendations in `findings.md` under “R2 cancellable streaming UI”; exit the skill after deciding spacing, control hierarchy, responsive behavior and status copy.

- [ ] **Step 2: Write failing event-buffer and API tests**

Cover replay deduplication and terminal replacement:

```tsx
it("buffers deltas per execution and ignores replayed event ids", async () => {
  const event = (id: number, type: string, executionId: string, payload: Record<string, unknown>) => ({
    id, type, sessionId: "session-1", executionId, timestamp: "2026-07-16T00:00:00Z", payload,
  });
  const { result } = renderHook(() => useAgentEvents("session-1", fakeOptions));
  source.emit(event(10, "assistant.delta", "run-1", { text: "你" }));
  source.emit(event(10, "assistant.delta", "run-1", { text: "你" }));
  source.emit(event(11, "assistant.delta", "run-1", { text: "好" }));
  expect(result.current.streamingByExecution["run-1"]?.text).toBe("你好");
});

it("marks partial output cancelled without promoting it to a formal message", async () => {
  source.emit(event(12, "execution.cancelled", "run-1", {}));
  expect(result.current.streamingByExecution["run-1"]?.status).toBe("cancelled");
});
```

Update `reviewApi.test.ts` to assert command POST includes `providerModelId` and `reasoningEffort` and returns the accepted resource. Test preflight, start, retry and generic cancel URLs.

- [ ] **Step 3: Run targeted frontend tests and verify they fail**

Run:

```bash
cd frontend
npm test -- --run \
  src/features/agent/agentApi.test.ts \
  src/features/agent/useAgentEvents.test.tsx \
  src/features/review/reviewApi.test.ts \
  src/features/review/CurationConversation.test.tsx \
  src/features/review/QuestionCatalog.test.tsx
```

Expected: accepted execution types, streaming buffers, model controls and bulk actions are missing.

- [ ] **Step 4: Implement replay-safe execution-scoped streaming state**

Extend the hook with a reducer keyed by execution ID:

```ts
export interface StreamingAssistantState {
  text: string;
  status: "running" | "cancelling" | "cancelled" | "completed" | "failed" | "interrupted";
}

export interface UseAgentEventsResult {
  status: AgentEventConnectionStatus;
  events: AgentEvent[];
  executionError: { code: string; message: string } | null;
  streamingByExecution: Record<string, StreamingAssistantState>;
  executionStateById: Record<string, AgentExecutionStatus>;
}
```

Append only unseen `assistant.delta` events. Set cancelling/cancelled/interrupted/failed/completed from terminal events. When a `session.message.created` event names the same execution, clear its completed temporary buffer after the session query refreshes.

Extend `EVENT_TYPES` with `curation.command.interpreting` and `execution.cancelling`; keep the existing EventSource URL/cursor behavior rather than opening a second stream.

- [ ] **Step 5: Implement the model-selectable stop-aware composer**

In `QuestionCatalog`, subscribe to the selected session with `useAgentEvents`, refetch session/candidates on relevant completion events, and keep `activeExecutionId` from the accepted response rather than treating the HTTP mutation as the running period.

Composer behavior must be explicit:

```tsx
{isRunning ? (
  <Button
    type="button"
    variant="danger"
    disabled={isCancelling}
    onClick={onStop}
  >
    <Square size={15} />{isCancelling ? "正在停止…" : "停止"}
  </Button>
) : (
  <Button type="submit" disabled={!text.trim() || !canCommand}>
    <CornerDownLeft size={16} />发送
  </Button>
)}
```

Render enabled/healthy Provider Models in a compact selector and reasoning strengths beside it. Initialize from session preference, disable both while running, and show the actual execution model in the streamed message metadata/runtime panel. Preserve Enter-to-send and Shift+Enter-to-newline.

- [ ] **Step 6: Render temporary, stopped and interrupted messages**

Insert the execution-scoped temporary assistant message after its associated optimistic user message. While empty show “题匠正在理解你的指令”; while chunks arrive show the accumulated Markdown. Status copy is “Agent 处理中”, “正在停止”, “已停止”, “运行中断”, “处理失败” or “处理完成”. Bound expanded process content with an internal scrollbar so the page layout does not grow without limit.

For interrupted runs, display two actions: retry calls the command retry endpoint; abandon marks the command cancelled/abandoned and returns the composer to idle. Do not place partial text in `CurationMessage[]` or the formal context query cache.

- [ ] **Step 7: Add one-click publication with preflight confirmation**

Add an “一键发布” action to the generated-files card header. On click, request preflight and show an accessible confirmation dialog containing exact counts. Start only after confirmation. Project `publication.changed` events onto file rows; apply the existing published shadow only after server confirmation. When the operation is partial failure, show “仅重试失败项”; when active, the shared stop button cancels its execution.

The confirmation copy must follow the accepted boundary:

```text
将发布 8 道推荐题；2 道需复核题会被跳过。已发布题目不会重复处理。
```

- [ ] **Step 8: Run targeted frontend and backend integration tests**

Run:

```bash
cd frontend
npm test -- --run \
  src/features/agent/agentApi.test.ts \
  src/features/agent/useAgentEvents.test.tsx \
  src/features/review/reviewApi.test.ts \
  src/features/review/CurationConversation.test.tsx \
  src/features/review/QuestionCatalog.test.tsx
```

Then run the cross-layer backend files once:

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_agent_routes_v2.py \
  tests/test_agent_restart_v2.py \
  tests/test_curation_session_api.py \
  tests/test_review_api_restart.py \
  tests/test_publication_service.py --tb=short
```

Expected: all selected tests pass.

- [ ] **Step 9: Run one minimal browser happy path before final evidence**

With backend on `127.0.0.1:8000` and frontend on `127.0.0.1:5174`, verify one existing curation session: choose a model, send a model-backed command, observe real incremental text or interpreting progress, stop it, and send a deterministic command afterward. Record actual event IDs, execution IDs and screenshots in `docs/verification/r2.md`; do not claim streaming if the selected scenario produced only structured classification.

- [ ] **Step 10: Run the final regression only once**

Backend:

```bash
cd backend
.venv/bin/pytest -q --tb=short
```

Frontend:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: all backend and frontend tests pass and Vite build exits 0. Copy the exact final counts into `docs/verification/r2.md`; never reuse older counts.

- [ ] **Step 11: Complete browser/restart acceptance once**

Verify these scenarios without Langfuse:

1. Send → genuine model output or interpreting event → stop → cancelled terminal state.
2. Refresh during/after SSE and confirm no duplicated text.
3. Restart backend during an active command and confirm interrupted state without repeated model/publication work.
4. Retry the interrupted command and confirm a new execution with the same original command context.
5. Switch model after completion and confirm only the next execution uses it.
6. One-click preflight → publish → stop between items → successful items retained → retry only failed/unprocessed items.
7. Desktop and mobile widths keep composer controls, dialog and bounded file list usable.

Record only observed evidence and remaining limitations in `docs/verification/r2.md`.

- [ ] **Step 12: Refresh project status and run documentation gate**

Update `task_plan.md`, `findings.md` and `progress.md` with a handoff of at most ten lines per completed task. Update `docs/verification/r2.md` into final user-guide form. Run:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r2.md \
  --learning docs/learning/r2/ \
  --plan docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md
```

Expected: exit 0. If the formal R2 plan still contains unchecked unrelated acceptance, report the exact gate result and do not label R2 ready for manual verification.

- [ ] **Step 13: Commit Task 4**

```bash
git add frontend/src/features/agent/agentTypes.ts \
  frontend/src/features/agent/agentApi.ts \
  frontend/src/features/agent/useAgentEvents.ts \
  frontend/src/features/agent/agentApi.test.ts \
  frontend/src/features/agent/useAgentEvents.test.tsx \
  frontend/src/features/review/reviewTypes.ts \
  frontend/src/features/review/reviewApi.ts \
  frontend/src/features/review/QuestionCatalog.tsx \
  frontend/src/features/review/CurationConversation.tsx \
  frontend/src/features/review/CurationRuntimePanel.tsx \
  frontend/src/features/review/reviewApi.test.ts \
  frontend/src/features/review/CurationConversation.test.tsx \
  frontend/src/features/review/QuestionCatalog.test.tsx \
  task_plan.md findings.md progress.md
git add "$(rg -l 'curation-composer|curation-artifacts' frontend/src --glob '*.css' | head -1)"
git commit -m "feat(review): add streaming controls and bulk publish UX"
```

Do not add `frontend/node_modules`, `docs/learning/`, or `docs/verification/` to Git. Explicitly synchronize the local verification file into the main repository after the product branch is merged, as required by `AGENTS.md`.
