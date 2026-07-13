# Runtime Middleware 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real middleware pipeline consumed by the existing `review.single` Agent, providing persisted model usage, context compression, automatic titles, loop protection, and a persistent-HITL adapter while defining—but not implementing—Todo candidates.

**Architecture:** Keep handwritten `StateGraph` workflows and wrap the existing `GraphBuildContext` model/tool/action ports with a three-layer RuntimeMiddleware pipeline. Business code emits safe spans through `ObservabilitySink`; an OpenTelemetry OTLP/HTTP implementation exports to local Langfuse while No-op/fail-open behavior preserves Agent execution when observability is unavailable.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite/WAL, LangGraph, LangChain `AgentMiddleware`, OpenTelemetry SDK/OTLP HTTP, Langfuse v3.176.0 Docker Compose, React 19, TypeScript, Vitest, pytest, Playwright.

## Global Constraints

- Do not rewrite `review.single`, knowledge publication, or the existing `HitlService` state machine.
- Do not implement R2 multi-question behavior, Todo extraction, a Todo Service, Todo persistence, or Todo UI.
- Never persist API keys, raw provider errors, full sensitive prompts, or unredacted tool arguments in middleware records/events.
- Provider-native usage wins; deterministic fallback estimates must set `estimated=true`.
- Streaming usage is recorded once per completed invocation, never once per chunk.
- Title and summary failures produce warning events and never turn a successful business run into `failed`.
- Hard guard failures use only stable codes: `loop_detected`, `no_progress`, `step_budget_exceeded`, `token_budget_exceeded`, `run_timeout`.
- `knowledge.publish` remains an explicit Graph node/handler; the HITL adapter handles ordinary tool approvals only.
- Middleware order is Guard → Invocation → Post-processing and every layer is independently switchable.
- Use one Agent end-to-end. Targeted tests during Tasks 1–3; one cross-layer integration run and one final full regression maximum.
- Do not modify or commit `docs/my_idea.md`.
- Business code depends only on `ObservabilitySink`; Langfuse/OTLP failures are fail-open.
- Trace payload is metadata-only by default; prompt/response/file/tool bodies require explicit local redacted-content opt-in.

---

## File Map

### New backend files

- `backend/app/db/migrations/runtime/006_runtime_middleware.sql`: usage and guard observation tables.
- `backend/app/runtime/middleware/__init__.py`: public exports only.
- `backend/app/runtime/middleware/types.py`: stable dataclasses, protocols, budgets, errors, and `TodoCandidate`.
- `backend/app/runtime/middleware/repository.py`: idempotent usage/guard persistence and aggregates.
- `backend/app/runtime/middleware/pipeline.py`: ordered hooks and per-layer enable flags.
- `backend/app/runtime/middleware/telemetry.py`: model invocation measurement/persistence.
- `backend/app/runtime/middleware/context_budget.py`: token estimation, message compaction, summary policy.
- `backend/app/runtime/middleware/session_title.py`: one-shot title generation and compare-and-set persistence.
- `backend/app/runtime/middleware/loop_guard.py`: persistent budgets, fingerprints, soft warning, hard stop.
- `backend/app/runtime/middleware/hitl_adapter.py`: ordinary-tool approval policy adapter.
- `backend/app/runtime/middleware/langchain_adapter.py`: official `AgentMiddleware` bridge using shared policies.
- `backend/app/runtime/middleware/observability.py`: trace context, No-op sink, OTel sink and bounded shutdown flush.
- `infra/observability/langfuse/compose.yaml`: pinned local Langfuse stack bound to 127.0.0.1.
- `infra/observability/langfuse/.env.example`: non-secret variables and generated-secret instructions.
- `infra/observability/langfuse/README.md`: start, health, project key, stop and destructive cleanup guidance.

### Modified backend files

- `backend/app/providers/chat_gateway.py`: return parsed result/stream chunks with usage envelopes.
- `backend/app/providers/openai_compatible.py`: extract native usage from raw structured response and final stream chunk.
- `backend/app/providers/anthropic_compatible.py`: same usage contract for Anthropic-compatible calls.
- `backend/app/runtime/repository.py`: title compare-and-set, summary update, session message helpers.
- `backend/app/runtime/models.py`: session usage/guard aggregate records.
- `backend/app/runtime/run_manager.py`: build `MiddlewareContext`, wrap model/tool/action ports, post-process completed messages, map guard failures.
- `backend/app/runtime/graph_build_context.py`: retain narrow ports; no database dependency.
- `backend/app/runtime/service.py`: construct repository/pipeline and return summary/usage/warning resources.
- `backend/app/runtime/graph_registry.py`: optional middleware enable/budget policy on `GraphDefinition`.
- `backend/app/schemas/agent.py`: session usage and guard warning API schemas.

### Frontend files

- `frontend/src/features/agent/agentTypes.ts`: session summary/usage/guard types.
- `frontend/src/features/review/ReviewPage.tsx`: compact usage/summary/guard status.
- `frontend/src/features/review/ReviewPage.test.tsx`: persisted middleware state rendering.
- `frontend/src/shared/api/errorAdvice.ts`: stable guard recovery advice.

### Tests and docs

- `backend/tests/test_runtime_middleware_repository.py`
- `backend/tests/test_runtime_middleware_pipeline.py`
- `backend/tests/test_model_usage_middleware.py`
- `backend/tests/test_context_title_middleware.py`
- `backend/tests/test_loop_guard_middleware.py`
- `backend/tests/test_hitl_middleware_adapter.py`
- `backend/tests/test_review_runtime_middleware.py`
- `backend/tests/test_observability.py`
- `tests/e2e/runtime-middleware.spec.ts`
- `docs/verification/runtime-middleware-1-0.md`
- `docs/learning/runtime-middleware-1-0/` seven-file ownership pack after stabilization.

---

### Task 1: Establish the pipeline contracts and durable middleware records

**Files:**
- Create: `backend/app/db/migrations/runtime/006_runtime_middleware.sql`
- Create: `backend/app/runtime/middleware/types.py`
- Create: `backend/app/runtime/middleware/repository.py`
- Create: `backend/app/runtime/middleware/pipeline.py`
- Create: `backend/app/runtime/middleware/observability.py`
- Create: `backend/app/runtime/middleware/__init__.py`
- Create: `infra/observability/langfuse/compose.yaml`
- Create: `infra/observability/langfuse/.env.example`
- Create: `infra/observability/langfuse/README.md`
- Modify: `backend/app/runtime/models.py`
- Modify: `backend/app/runtime/repository.py`
- Modify: `backend/app/runtime/graph_registry.py`
- Test: `backend/tests/test_runtime_database.py`
- Test: `backend/tests/test_runtime_repository.py`
- Create test: `backend/tests/test_runtime_middleware_repository.py`
- Create test: `backend/tests/test_runtime_middleware_pipeline.py`
- Create test: `backend/tests/test_observability.py`

**Interfaces:**
- Produces: `MiddlewareContext`, `MiddlewareLayer`, `MiddlewareConfig`, `ModelInvocation`, `ModelUsage`, `ToolInvocation`, `TodoCandidate`, `RuntimeGuardError`.
- Produces: `RuntimeMiddlewareRepository.record_usage()`, `aggregate_session_usage()`, `record_guard_observation()`, `guard_state()`, `start_trace_segment()`, `finish_trace_segment()`.
- Produces: `RuntimeMiddlewarePipeline.wrap_model()`, `wrap_tool()`, `after_message()`.
- Produces: `TraceContext`, `ObservabilitySink`, `NoopObservabilitySink`, `SafeObservabilitySink`.
- Produces: `GraphDefinition.middleware_config: MiddlewareConfig` with safe defaults.

- [ ] **Step 1: Add RED migration and repository tests**

Create tests that open a fresh Runtime database and assert migration 006 exists, usage operation keys are idempotent, guard and trace segment sequences survive reopening, and title compare-and-set cannot overwrite a user title:

```python
def test_usage_operation_key_is_idempotent(tmp_path):
    connection = connect_runtime_database(tmp_path)
    repository = RuntimeMiddlewareRepository(connection)
    usage = ModelUsage(
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        context_tokens=100,
        latency_ms=14,
        estimated=False,
    )
    repository.record_usage(context(), invocation(), usage, operation_key="r1:evaluate:0")
    repository.record_usage(context(), invocation(), usage, operation_key="r1:evaluate:0")
    aggregate = repository.aggregate_session_usage("s1")
    assert aggregate.call_count == 1
    assert aggregate.total_tokens == 120


def test_compare_and_set_title_preserves_user_edit(runtime_repository):
    session = create_session(runtime_repository, title="新会话")
    runtime_repository.compare_and_set_session_title(session.id, expected="新会话", title="缓存穿透")
    assert runtime_repository.compare_and_set_session_title(
        session.id, expected="新会话", title="被覆盖"
    ) is False
    assert runtime_repository.get_session(session.id).title == "缓存穿透"
```

- [ ] **Step 2: Run Task 1 RED tests**

Run:

```bash
cd backend
python3 -m pytest \
  tests/test_runtime_database.py \
  tests/test_runtime_repository.py \
  tests/test_runtime_middleware_repository.py \
  tests/test_runtime_middleware_pipeline.py \
  tests/test_observability.py -q --tb=short
```

Expected: FAIL because migration 006 and middleware modules do not exist.

- [ ] **Step 3: Add migration 006**

Create the exact schema:

```sql
CREATE TABLE model_invocation_usage (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    operation_key TEXT NOT NULL,
    role TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    provider_model_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    context_tokens INTEGER NOT NULL CHECK (context_tokens >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, operation_key)
);

CREATE INDEX idx_model_usage_session_created
    ON model_invocation_usage(session_id, created_at, id);

CREATE TABLE runtime_guard_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    kind TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, sequence)
);

CREATE TABLE runtime_trace_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    segment_sequence INTEGER NOT NULL CHECK (segment_sequence > 0),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    UNIQUE(run_id, segment_sequence)
);
```

- [ ] **Step 4: Implement stable middleware types**

Define the actual contracts in `types.py`:

```python
class MiddlewareLayer(StrEnum):
    GUARD = "guard"
    INVOCATION = "invocation"
    POST_PROCESSING = "post_processing"


@dataclass(frozen=True, slots=True)
class MiddlewareConfig:
    enabled_layers: frozenset[MiddlewareLayer] = frozenset(MiddlewareLayer)
    soft_context_tokens: int = 12_000
    hard_context_tokens: int = 16_000
    max_graph_steps: int = 40
    max_model_calls: int = 12
    max_tool_calls: int = 20
    max_run_seconds: int = 300
    repeat_soft_limit: int = 3
    repeat_hard_limit: int = 4


@dataclass(frozen=True, slots=True)
class MiddlewareContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    operation_key: str
    role: str
    provider_id: str
    provider_model_id: str
    messages: tuple[Any, ...]
    purpose: Literal["business", "context_summary", "session_title"] = "business"


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    operation_key: str
    tool_name: str
    arguments: dict[str, object]


class RuntimeMiddleware(Protocol):
    layer: MiddlewareLayer
    order: int

    async def wrap_model(self, context, invocation, call_next): ...
    async def wrap_tool(self, context, invocation, call_next): ...
    async def after_message(self, context, message): ...


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_tokens: int
    latency_ms: int
    estimated: bool


@dataclass(frozen=True, slots=True)
class TodoCandidate:
    source_message_ids: tuple[str, ...]
    suggested_title: str
    due_at: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    confidence: float


class RuntimeGuardError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
```

Validate positive budgets in `MiddlewareConfig.__post_init__`; allow only the five stable guard codes.

- [ ] **Step 5: Implement repositories and pipeline ordering**

`RuntimeMiddlewarePipeline` must compose wrappers deterministically and skip disabled layers:

```python
class RuntimeMiddlewarePipeline:
    def __init__(self, middleware: Sequence[RuntimeMiddleware], config: MiddlewareConfig):
        self._middleware = tuple(sorted(middleware, key=lambda item: item.order))
        self._config = config

    async def wrap_model(self, context, invocation, call_next):
        handler = call_next
        for item in reversed(self._enabled(MiddlewareLayer.INVOCATION, MiddlewareLayer.GUARD)):
            previous = handler
            handler = lambda inv, item=item, previous=previous: item.wrap_model(
                context, inv, previous
            )
        return await handler(invocation)

    async def after_message(self, context, message):
        for item in self._enabled(MiddlewareLayer.POST_PROCESSING):
            await item.after_message(context, message)
```

Use explicit local async functions instead of late-bound lambdas in production. Repository methods use `INSERT ... ON CONFLICT(run_id, operation_key) DO NOTHING` and aggregate with `SUM`/`COUNT`.

- [ ] **Step 6: Add session CAS/summary repository methods and Graph defaults**

Add:

```python
def compare_and_set_session_title(self, session_id: str, *, expected: str, title: str) -> bool: ...
def update_session_summary(self, session_id: str, *, summary: str) -> SessionRecord: ...
```

Extend `GraphDefinition`:

```python
middleware_config: MiddlewareConfig = MiddlewareConfig()
```

Existing graph definitions require no changes and receive safe defaults.

- [ ] **Step 7: Add fail-open observability contracts and local Langfuse**

Define the framework-neutral boundary:

```python
@dataclass(frozen=True, slots=True)
class TraceContext:
    workspace_id: str
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int


class ObservabilitySink(Protocol):
    @contextmanager
    def span(
        self,
        name: str,
        *,
        context: TraceContext,
        attributes: Mapping[str, str | int | float | bool],
        links: Sequence[object] = (),
    ) -> Iterator[SpanHandle]: ...

    def force_flush(self, timeout_millis: int) -> bool: ...


class NoopObservabilitySink:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield NoopSpanHandle()

    def force_flush(self, timeout_millis: int) -> bool:
        return True
```

`SafeObservabilitySink` catches exporter/sink exceptions, calls an injected local warning publisher, and returns a No-op handle. Tests use a deliberately failing inner sink and assert the wrapped business function still returns its value.

Add OpenTelemetry dependencies without Langfuse SDK coupling:

```bash
cd backend
uv add 'opentelemetry-api>=1.30,<2' \
  'opentelemetry-sdk>=1.30,<2' \
  'opentelemetry-exporter-otlp-proto-http>=1.30,<2'
```

Create local Compose from the official Langfuse `v3.176.0` Docker Compose, pin `langfuse/langfuse:3.176.0` and `langfuse/langfuse-worker:3.176.0`, retain PostgreSQL/ClickHouse/Redis/MinIO named volumes, and change host mappings to `127.0.0.1`. `.env.example` lists generated secret variables but contains no usable production secret. README commands:

```bash
cd infra/observability/langfuse
cp .env.example .env
# Edit .env with local-only headless-init IDs, user credentials, and project keys.
docker compose config
docker compose up -d
curl --fail http://127.0.0.1:3000/api/public/health
docker compose down
```

Generate the OTLP Basic Auth value from the same local project keys and store the
result only in the uncommitted `.env` as `LANGFUSE_OTLP_AUTH`:

```bash
printf '%s' "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}:${LANGFUSE_INIT_PROJECT_SECRET_KEY}" | base64
```

Document destructive cleanup separately as `docker compose down -v` and label it data-deleting. Do not run `down -v` during tests.

- [ ] **Step 8: Run Task 1 GREEN tests and commit**

Run the Step 2 command. Expected: all selected tests pass.

Commit:

```bash
git add backend/app/db/migrations/runtime/006_runtime_middleware.sql \
  backend/app/runtime/middleware backend/app/runtime/models.py \
  backend/app/runtime/repository.py backend/app/runtime/graph_registry.py \
  backend/pyproject.toml backend/uv.lock infra/observability/langfuse \
  backend/tests/test_runtime_database.py backend/tests/test_runtime_repository.py \
  backend/tests/test_runtime_middleware_repository.py \
  backend/tests/test_runtime_middleware_pipeline.py backend/tests/test_observability.py
git commit -m "feat(runtime): add middleware pipeline foundation"
```

---

### Task 2: Wrap model calls with usage telemetry and context budgets

**Files:**
- Create: `backend/app/runtime/middleware/telemetry.py`
- Create: `backend/app/runtime/middleware/context_budget.py`
- Modify: `backend/app/providers/chat_gateway.py`
- Modify: `backend/app/providers/openai_compatible.py`
- Modify: `backend/app/providers/anthropic_compatible.py`
- Modify: `backend/app/runtime/run_manager.py`
- Modify: `backend/app/runtime/service.py`
- Modify: `backend/app/runtime/middleware/observability.py`
- Test: `backend/tests/test_chat_gateway.py`
- Create test: `backend/tests/test_model_usage_middleware.py`
- Create test: `backend/tests/test_context_title_middleware.py`
- Modify test: `backend/tests/test_observability.py`

**Interfaces:**
- Consumes: Task 1 `RuntimeMiddlewarePipeline`, `ModelInvocation`, `ModelUsage`, repository.
- Produces: `ProviderModelResult[T]`, `ProviderStreamChunk`, `estimate_message_tokens()`, `ContextBudgetMiddleware`.
- Produces: model calls routed through pipeline from `_BoundModelInvoker`.
- Produces: `OpenTelemetryObservabilitySink`, `ObservabilitySettings`, root/model spans exported over OTLP/HTTP.

- [ ] **Step 1: Add RED tests for native usage, fallback estimates, stream finalization, and compaction**

Tests must prove both usage paths and no per-chunk duplication:

```python
@pytest.mark.asyncio
async def test_native_usage_is_recorded_once():
    adapter = FakeAdapter(result=ProviderModelResult(
        value=Answer(score="good"),
        usage=ProviderUsage(input_tokens=50, output_tokens=10),
    ))
    result = await gateway.invoke_structured(binding=binding(), schema=Answer, messages=[])
    assert result.value.score == "good"
    assert result.usage.total_tokens == 60
    assert result.usage.estimated is False


@pytest.mark.asyncio
async def test_stream_usage_is_not_counted_per_chunk():
    adapter = FakeAdapter(chunks=[
        ProviderStreamChunk(text="甲"),
        ProviderStreamChunk(text="乙", usage=ProviderUsage(40, 8)),
    ])
    chunks = [chunk async for chunk in gateway.stream_text(binding=binding(), messages=[])]
    assert "".join(chunk.text for chunk in chunks) == "甲乙"
    assert [chunk.usage for chunk in chunks if chunk.usage] == [ProviderUsage(40, 8)]
```

Context test:

```python
def test_compaction_keeps_system_recent_messages_and_references():
    compacted = compact_messages(
        messages=long_history(),
        summary="已掌握缓存穿透定义",
        keep_recent=4,
        protected_refs=("q1", "draft1"),
    )
    assert compacted[0]["role"] == "system"
    assert "已掌握缓存穿透定义" in str(compacted)
    assert "q1" in str(compacted) and "draft1" in str(compacted)
```

- [ ] **Step 2: Run Task 2 RED tests**

```bash
cd backend
python3 -m pytest \
  tests/test_chat_gateway.py \
  tests/test_model_usage_middleware.py \
  tests/test_context_title_middleware.py \
  tests/test_observability.py -q --tb=short
```

Expected: FAIL because usage envelopes and budget middleware do not exist.

- [ ] **Step 3: Add provider usage envelopes**

In `chat_gateway.py` define:

```python
@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ProviderModelResult(Generic[SchemaT]):
    value: SchemaT
    usage: ProviderUsage | None


@dataclass(frozen=True, slots=True)
class ProviderStreamChunk:
    text: str
    usage: ProviderUsage | None = None
```

Change adapter/gateway protocols so structured calls return `ProviderModelResult`; streams yield `ProviderStreamChunk`.

- [ ] **Step 4: Extract native usage in both adapters**

For structured output call `with_structured_output(schema, ..., include_raw=True)` and extract `raw.usage_metadata`. For streams, configure streaming usage where supported and emit usage only when present on the final chunk. Use one shared helper:

```python
def usage_from_message(message: Any) -> ProviderUsage | None:
    metadata = getattr(message, "usage_metadata", None)
    if not isinstance(metadata, dict):
        return None
    input_tokens = int(metadata.get("input_tokens", 0))
    output_tokens = int(metadata.get("output_tokens", 0))
    return ProviderUsage(input_tokens, output_tokens)
```

Do not expose `response_metadata` wholesale.

- [ ] **Step 5: Implement telemetry and deterministic estimates**

`ModelUsageMiddleware.wrap_model()` measures latency, calls `call_next`, records native usage, or estimates missing values with one deterministic tokenizer function:

```python
def estimate_text_tokens(text: str) -> int:
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


def estimate_message_tokens(messages: Sequence[Any]) -> int:
    return sum(estimate_text_tokens(normalize_message_text(item)) + 4 for item in messages)
```

The fallback is explicitly approximate; it must set `estimated=True`. Persist failed calls with zero output tokens and a stable provider error code.

- [ ] **Step 6: Implement OTLP/HTTP tracing before real model debugging**

Add environment-backed settings with disabled defaults:

```python
@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    enabled: bool = False
    service_name: str = "cyber-interview-agent"
    otlp_endpoint: str = "http://127.0.0.1:3000/api/public/otel/v1/traces"
    otlp_headers: str = ""
    capture_content: bool = False
    flush_timeout_ms: int = 2_000


def create_observability_sink(
    settings: ObservabilitySettings,
    publish_warning: Callable[[str], None],
) -> ObservabilitySink:
    if not settings.enabled:
        return NoopObservabilitySink()
    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        headers=parse_otlp_headers(settings.otlp_headers),
    )
    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=512))
    return SafeObservabilitySink(OpenTelemetryObservabilitySink(provider), publish_warning)
```

Tests use OpenTelemetry `InMemorySpanExporter` and assert the hierarchy `agent.run` → `model.invoke`/`model.stream`, safe IDs, model/role, latency, token counts, status and `usage.estimated`. Assert no attribute contains prompt text, response text, API keys or raw provider errors when `capture_content=False`. A failing exporter must not change the returned model result.

Start `agent.run` in RunManager and make model spans children through the active OTel context. Do not persist OTel objects in Graph state.

- [ ] **Step 7: Implement context budget middleware**

Before `call_next`, compare estimated context to graph config. On soft threshold, use injected `summarize_context(messages, existing_summary)` once and replace older messages with:

```python
[
    {"role": "system", "content": f"会话压缩摘要：\n{summary}"},
    *protected_system_messages,
    *recent_messages,
]
```

If the compacted request still exceeds `hard_context_tokens`, raise `RuntimeGuardError("token_budget_exceeded", "上下文已超过运行预算")`. Summary failures below the hard limit publish `middleware.warning` and continue unchanged.

Only `purpose="business"` invocations may trigger compaction. Summary/title calls still pass through telemetry but use `purpose="context_summary"` or `purpose="session_title"`, preventing recursive post-processing.

- [ ] **Step 8: Route `_BoundModelInvoker` through the pipeline**

Construct a monotonic operation key per run and role:

```python
operation_key = f"model:{role}:{self._call_sequence}"
self._call_sequence += 1
invocation = ModelInvocation(
    operation_key=operation_key,
    role=role,
    provider_id=binding.provider_id,
    provider_model_id=binding.provider_model_id,
    messages=tuple(messages),
)
```

Both structured and stream calls must use `pipeline.wrap_model`. For streams, finalize telemetry in `finally` only after the stream terminates; cancellation records `failed` once.

Model spans use `gen_ai.operation.name`, `gen_ai.request.model`, safe provider/model IDs, token counts and `cyber.usage.estimated`. Do not attach message bodies unless `capture_content=True`, and then only after the repository redaction helper runs.

- [ ] **Step 9: Run Task 2 GREEN tests and integration subset**

Run Step 2 plus:

```bash
python3 -m pytest tests/test_run_manager.py \
  tests/test_openai_adapter.py tests/test_anthropic_adapter.py -q --tb=short
```

Expected: all selected tests pass; existing provider error sanitization remains green.

- [ ] **Step 10: Commit Task 2**

```bash
git add backend/app/providers backend/app/runtime/middleware/telemetry.py \
  backend/app/runtime/middleware/context_budget.py \
  backend/app/runtime/middleware/observability.py backend/app/runtime/run_manager.py \
  backend/app/runtime/service.py backend/tests/test_chat_gateway.py \
  backend/tests/test_model_usage_middleware.py \
  backend/tests/test_context_title_middleware.py backend/tests/test_observability.py \
  backend/tests/test_run_manager.py
git commit -m "feat(runtime): meter model usage and context budgets"
```

---

### Task 3: Add automatic titles, persistent loop guards, and session API/UI

**Files:**
- Create: `backend/app/runtime/middleware/session_title.py`
- Create: `backend/app/runtime/middleware/loop_guard.py`
- Modify: `backend/app/runtime/run_manager.py`
- Modify: `backend/app/runtime/service.py`
- Modify: `backend/app/schemas/agent.py`
- Create test: `backend/tests/test_loop_guard_middleware.py`
- Modify test: `backend/tests/test_agent_routes.py`
- Modify: `frontend/src/features/agent/agentTypes.ts`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/shared/api/errorAdvice.ts`
- Modify test: `frontend/src/features/review/ReviewPage.test.tsx`
- Create test: `frontend/src/shared/api/errorAdvice.test.ts`

**Interfaces:**
- Consumes: Task 1 repository/pipeline; Task 2 model invocation and usage aggregates.
- Produces: `SessionTitleMiddleware`, `LoopGuardMiddleware`, `SessionUsageResource`, `GuardWarningResource`.
- Produces: visible Review usage/summary/guard status.
- Produces: `middleware.session_title`, `middleware.context_compression`, `middleware.loop_guard`, and `tool.invoke` child spans.

- [ ] **Step 1: Add RED backend tests for title, guard thresholds, restart, and safe errors**

```python
@pytest.mark.asyncio
async def test_title_is_generated_once_after_first_completed_exchange(runtime):
    session = await complete_review(runtime, title="新会话")
    refreshed = await runtime.session_detail(session.id)
    assert refreshed["title"] == "缓存穿透复习"
    assert title_model.call_count == 1


@pytest.mark.asyncio
async def test_repeat_guard_warns_then_fails_after_restart(runtime_factory):
    runtime = runtime_factory()
    run = await start_repeating_run(runtime)
    await runtime.shutdown()
    restarted = runtime_factory()
    failed = await restarted.resume_run(run.id)
    await restarted.wait(failed.id)
    assert restarted.get_run(run.id).error_code == "loop_detected"
```

Route test asserts `summary`, camelCase usage fields, and a redacted latest warning.

Observability assertions use the in-memory exporter and verify title/compression/guard/tool spans contain trigger reason and stable status but no generated title text, summary body, fingerprints or tool arguments.

- [ ] **Step 2: Add RED frontend rendering and advice tests**

Mock session detail:

```ts
usage: {
  inputTokens: 120,
  outputTokens: 40,
  totalTokens: 160,
  contextTokens: 120,
  callCount: 2,
  estimatedCount: 1,
},
summary: "缓存穿透的定义与常见防护",
latestGuardWarning: { code: "loop_detected", message: "检测到重复执行" },
```

Assert the page renders `160 tokens`、`含 1 次估算`、`上下文已压缩` and actionable loop recovery text.

- [ ] **Step 3: Run Task 3 RED tests**

```bash
cd backend
python3 -m pytest \
  tests/test_loop_guard_middleware.py \
  tests/test_agent_routes.py -q --tb=short
cd ../frontend
./node_modules/.bin/vitest run src/features/review/ReviewPage.test.tsx \
  src/shared/api/errorAdvice.test.ts --reporter=dot
```

Expected: FAIL on missing guard/title resources and UI fields.

- [ ] **Step 4: Implement one-shot session titles**

`SessionTitleMiddleware.after_message()` returns immediately unless the title is in the configured placeholder set and a user/assistant pair exists. Invoke the title model once, normalize it, then CAS:

```python
def normalize_title(value: str) -> str:
    return " ".join(value.replace("\n", " ").strip(" '\"").split())[:40]

updated = repository.compare_and_set_session_title(
    context.session_id,
    expected=current.title,
    title=normalize_title(generated),
)
```

On failure publish `middleware.warning` with `code="session_title_failed"`; never raise into completed business flow.

The title call uses `ModelInvocation(purpose="session_title", ...)`; the summarizer uses `purpose="context_summary"`. Both are metered, neither may trigger compression/title middleware recursively.

- [ ] **Step 5: Implement persistent loop/no-progress guards**

Fingerprint only normalized safe metadata:

```python
fingerprint = sha256(
    canonical_json({"kind": kind, "name": name, "args": redact_and_normalize(args)}).encode()
).hexdigest()
```

Persist every observation before checking counts. At `repeat_soft_limit`, publish `runtime.guard.warning` once and return a correction instruction. At `repeat_hard_limit`, raise `RuntimeGuardError("loop_detected", ...)`. Check elapsed time, model/tool counts, and token aggregates before each invocation. Restore counts exclusively from repository on resume.

Each middleware/tool span records only operation name, budget/threshold numbers, safe tool name/scope and stable result code. Guard fingerprints remain local SQLite hashes and never become span attributes.

Pass `recursion_limit=definition.middleware_config.max_graph_steps` to `graph.ainvoke`. This covers Graphs that loop without making model/tool calls; catch LangGraph `GraphRecursionError` and map it to `step_budget_exceeded`.

- [ ] **Step 6: Map guard errors in RunManager**

Add a dedicated `except RuntimeGuardError` before the generic exception branch:

```python
except RuntimeGuardError as error:
    failed = self._repository.transition_run(
        run.id,
        expected="running",
        target="failed",
        error_code=error.code,
        error_message=str(error),
    )
    await self._event_stream.publish(
        failed.session_id, failed.id, "run.failed",
        {"code": error.code, "message": str(error)},
    )
```

Do not expose fingerprints or raw arguments.

The graph invocation config must include the hard step budget:

```python
result = await graph.ainvoke(
    graph_input,
    {
        "configurable": {"thread_id": run.session_id},
        "recursion_limit": definition.middleware_config.max_graph_steps,
    },
)
```

Map `GraphRecursionError` through the same safe failure helper with `code="step_budget_exceeded"`.

- [ ] **Step 7: Extend Agent API resources**

Add:

```python
class SessionUsageResource(AgentModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    context_tokens: int
    call_count: int
    estimated_count: int


class GuardWarningResource(AgentModel):
    code: str
    message: str


class SessionDetailResource(SessionResource):
    summary: str | None = None
    usage: SessionUsageResource
    latest_guard_warning: GuardWarningResource | None = None
    messages: list[MessageResource]
    latest_run: RunResource | None
    pending_action: PendingActionSummaryResource | None = None
```

Service aggregates only the selected session and never returns observation fingerprints.

- [ ] **Step 8: Render compact middleware state in ReviewPage**

Extend TypeScript types exactly to match camelCase resources. Render within `review-session-bar`:

```tsx
{detail ? (
  <div className="review-runtime-meta" aria-label="运行用量">
    <span>{detail.usage.totalTokens} tokens</span>
    {detail.usage.estimatedCount > 0 ? <span>含 {detail.usage.estimatedCount} 次估算</span> : null}
    {detail.summary ? <span>上下文已压缩</span> : null}
  </div>
) : null}
```

If `latestGuardWarning` exists, show its safe message and advice. Add advice mappings for all five guard codes.

- [ ] **Step 9: Run Task 3 GREEN tests, typecheck, and commit**

Run Step 3, then:

```bash
cd frontend
./node_modules/.bin/tsc --noEmit
```

Expected: backend/frontend targeted tests and TypeScript pass.

Commit:

```bash
git add backend/app/runtime/middleware/session_title.py \
  backend/app/runtime/middleware/loop_guard.py backend/app/runtime/run_manager.py \
  backend/app/runtime/service.py backend/app/schemas/agent.py \
  backend/tests/test_loop_guard_middleware.py backend/tests/test_agent_routes.py \
  frontend/src/features/agent/agentTypes.ts frontend/src/features/review/ReviewPage.tsx \
  frontend/src/features/review/ReviewPage.test.tsx frontend/src/shared/api/errorAdvice.ts
git commit -m "feat(runtime): add title and loop guard middleware"
```

---

### Task 4: Bridge HITL, prove `review.single`, and close acceptance

**Files:**
- Create: `backend/app/runtime/middleware/hitl_adapter.py`
- Create: `backend/app/runtime/middleware/langchain_adapter.py`
- Modify: `backend/app/runtime/run_manager.py`
- Modify: `backend/app/runtime/graph_build_context.py`
- Create test: `backend/tests/test_hitl_middleware_adapter.py`
- Create test: `backend/tests/test_review_runtime_middleware.py`
- Create: `tests/e2e/runtime-middleware.spec.ts`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Create local: `docs/verification/runtime-middleware-1-0.md`
- Create local: `docs/learning/runtime-middleware-1-0/` seven files.

**Interfaces:**
- Consumes: complete pipeline, existing `HitlService`, `request_action`, `Command(resume=...)`, `review.single`.
- Produces: `ToolApprovalPolicy`, `PersistentHitlMiddleware`, `LangChainRuntimeMiddlewareAdapter`.
- Produces: `hitl.interrupt`, `hitl.resume`, `knowledge.publish` spans and linked restart trace segments.
- Preserves: explicit `knowledge.publish` node/handler and current publication idempotency.

- [ ] **Step 1: Add RED HITL boundary tests**

```python
@pytest.mark.asyncio
async def test_ordinary_tool_policy_creates_persistent_action():
    policy = ToolApprovalPolicy(require_approval=frozenset({"write_profile"}))
    middleware = PersistentHitlMiddleware(policy=policy, request_action=request_action)
    result = await middleware.wrap_tool(context(), tool_call("write_profile"), call_next)
    assert result.interrupted_action_id == "action-1"
    request_action.assert_awaited_once()
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_publish_remains_explicit():
    middleware = PersistentHitlMiddleware(policy=ToolApprovalPolicy())
    await complete_review_until_publication(runtime_with(middleware))
    action = (await runtime.list_actions("w1", status="pending"))[0]
    assert action.action_type == "knowledge.publish"
    assert action.idempotency_key.startswith("review-run:")
```

Also instantiate `LangChainRuntimeMiddlewareAdapter` and assert it subclasses official `AgentMiddleware` and delegates shared model/tool policies without a database connection.

- [ ] **Step 2: Add RED full `review.single` middleware integration test**

Use deterministic fake Provider usage and assert:

```python
waiting = await runtime.session_detail(session.id)
assert waiting["usage"]["callCount"] == 2
assert waiting["usage"]["totalTokens"] == 240
assert waiting["pendingAction"]["actionType"] == "knowledge.publish"
await approve_latest_action(runtime, session.id)
completed = await runtime.session_detail(session.id)
assert completed["title"] != "新会话"
assert completed["pendingAction"] is None
```

Restart Runtime from the same Workspace path, assert usage/title/summary remain, approve publication, and verify one Vault document. Assert the resumed `agent.run` segment contains an OTel Link to the previous persisted trace/span context and all segments share the safe Langfuse session attribute. Disable all middleware layers in a second graph definition and assert the original evaluation/report/publication output still succeeds with zero usage records.

- [ ] **Step 3: Run Task 4 RED tests**

```bash
cd backend
python3 -m pytest \
  tests/test_hitl_middleware_adapter.py \
  tests/test_review_runtime_middleware.py \
  tests/test_hitl_service.py \
  tests/test_knowledge_publication_graph.py -q --tb=short
```

Expected: FAIL because the HITL and official-agent adapters are absent.

- [ ] **Step 4: Implement ordinary-tool HITL adapter**

Define:

```python
@dataclass(frozen=True, slots=True)
class ToolApprovalPolicy:
    require_approval: frozenset[str] = frozenset()

    def requires_approval(self, tool_name: str) -> bool:
        return tool_name in self.require_approval
```

The adapter creates a safe preview from allowlisted fields, calls existing `request_action` with `action_type=f"tool.approval.{tool_name}"`, and invokes LangGraph `interrupt({"actionId": action.id})`. It executes `call_next` only after an approved resume decision. Reject returns a stable tool rejection result. Never route `knowledge.publish` through this adapter.

Create `hitl.interrupt` before returning the interrupt result, `hitl.resume` when delivery resumes the run, and `knowledge.publish` around the explicit publication handler. Attributes are limited to action/run/session IDs, action type, decision/status and target state; edited content and Vault body are excluded.

- [ ] **Step 5: Implement the official LangChain adapter**

Subclass `AgentMiddleware` and delegate only hooks supported by shared policies:

```python
class LangChainRuntimeMiddlewareAdapter(AgentMiddleware):
    def __init__(self, pipeline: RuntimeMiddlewarePipeline, context_factory):
        self._pipeline = pipeline
        self._context_factory = context_factory

    async def awrap_model_call(self, request, handler):
        context, invocation = self._context_factory.model(request)
        return await self._pipeline.wrap_model(context, invocation, lambda _inv: handler(request))

    async def awrap_tool_call(self, request, handler):
        context, invocation = self._context_factory.tool(request)
        return await self._pipeline.wrap_tool(context, invocation, lambda _inv: handler(request))
```

No existing graph must migrate to `create_agent` in this task. This adapter is validated by unit contract only.

- [ ] **Step 6: Run Task 4 GREEN and one cross-layer integration subset**

Run Step 3, then:

```bash
python3 -m pytest \
  tests/test_review_runtime_integration.py \
  tests/test_hitl_restart.py \
  tests/test_draft_routes.py \
  tests/test_agent_routes.py -q --tb=short
```

Expected: all selected tests pass; restart and publication behavior remain unchanged.

- [ ] **Step 7: Add and run one browser acceptance spec**

`runtime-middleware.spec.ts` must:

1. register a Workspace and configured fake Provider;
2. complete one `review.single` answer and wait for report action;
3. assert usage is visible while the explicit publication action is pending;
4. approve publication, then assert title changed from placeholder and the same publication path is used;
5. refresh and assert usage/title remain;
6. run a test graph configured to repeat and assert actionable loop error;
7. restart backend, reload, and assert persisted state;
8. verify 1440×1000 and 375×812 have no horizontal overflow and console has no warnings/errors.

Before the app spec, start local Langfuse and use headless initialization values from the uncommitted `.env`. Set:

```bash
export CYBER_OBSERVABILITY_ENABLED=true
export CYBER_OTLP_ENDPOINT=http://127.0.0.1:3000/api/public/otel/v1/traces
export CYBER_OTLP_HEADERS="Authorization=Basic ${LANGFUSE_OTLP_AUTH},x-langfuse-ingestion-version=4"
export CYBER_OBSERVABILITY_CAPTURE_CONTENT=false
```

After the run, flush the exporter and query the self-hosted public API with project Basic Auth:

```bash
curl --fail \
  -u "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}:${LANGFUSE_INIT_PROJECT_SECRET_KEY}" \
  "http://127.0.0.1:3000/api/public/sessions/${SESSION_ID}"
```

Assert the response contains `agent.run`, two model observations, HITL and publication observations grouped by `${SESSION_ID}`. Search the serialized response for the test API key, answer, prompt sentinel and Vault markdown sentinel; all must be absent. Then stop Langfuse (without `-v`), run one targeted review again, and assert the business run/publication still complete with a local observability warning.

Run once:

```bash
CYBER_E2E_PYTHON=backend/.venv/bin/python \
  frontend/node_modules/.bin/playwright test \
  --config playwright.config.ts tests/e2e/runtime-middleware.spec.ts --reporter=line
```

Expected: 1 passed. If an assertion fails, rerun only this spec after the fix; do not restart full regression.

- [ ] **Step 8: Run final regression and build once**

```bash
cd backend
python3 -m pytest -q --tb=short
cd ../frontend
./node_modules/.bin/vitest run --reporter=dot
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/vite build
```

Expected: backend and frontend suites pass; TypeScript and Vite build exit 0. Record exact counts from this run only.

- [ ] **Step 9: Finalize verification and ownership docs**

Create `docs/verification/runtime-middleware-1-0.md` with fixed headings:

- `## 这次实现了什么`
- `## 代码地图`
- `## 自动验证`
- `## 人工验证`
- `## 当前边界`

Generate the seven learning files only after code/browser stability. Explicitly distinguish Provider-native usage from estimates and state that Todo extraction is not implemented. Run:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/runtime-middleware-1-0.md \
  --learning docs/learning/runtime-middleware-1-0/ \
  --plan docs/superpowers/plans/2026-07-12-runtime-middleware-1-0.md
```

Expected: `Stage documentation gate passed`.

- [ ] **Step 10: Commit acceptance closeout**

```bash
git add backend/app/runtime/middleware/hitl_adapter.py \
  backend/app/runtime/middleware/langchain_adapter.py \
  backend/app/runtime/run_manager.py backend/app/runtime/graph_build_context.py \
  backend/tests/test_hitl_middleware_adapter.py \
  backend/tests/test_review_runtime_middleware.py tests/e2e/runtime-middleware.spec.ts \
  task_plan.md findings.md progress.md
git commit -m "feat(runtime): validate middleware with review agent"
```

Keep `docs/verification/` and `docs/learning/` local, then explicitly synchronize them into the main repository after branch merge as required by `AGENTS.md`.
