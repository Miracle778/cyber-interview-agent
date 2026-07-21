# Agent JSONL Diagnostic Traces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every Runtime Agent model and Tool exchange as a safe, append-only, per-Execution JSONL trace that distinguishes agent role, concrete agent name, and individual invocation.

**Architecture:** A filesystem-only `AgentTraceWriter` owns safe paths, serialization, sequencing, append, and fsync. `AgentFactory` injects one `AgentTraceMiddleware` into every compiled Agent using the concrete `AgentSpec.execution_name`; `AgentExecutionService` adds Execution boundary events and the existing summarization middleware records its internal model call through the same writer. Product Events, checkpoints, Runtime SQLite domain facts, and remote observability remain unchanged.

**Tech Stack:** Python 3.12, LangChain `AgentMiddleware`, LangGraph Runtime context, Pydantic v2, JSON Lines, pytest.

## Global Constraints

- Write traces only to `.cyber-interview-agent/agent-traces/<session-id>/<run-id>.jsonl` inside the active workspace.
- Preserve full Agent message content, source excerpts, Tool arguments/results, structured responses, usage, finish metadata, and safe Provider errors without content-length truncation.
- Never serialize API keys, Authorization/cookie headers, secret refs, environment variables, SDK client objects, credential containers, or arbitrary object `repr` output.
- Every event must contain `schema_version=1`, UTC timestamp, monotonic per-file sequence, UUID event ID, workspace/session/run IDs, `agent_role`, `agent_name`, `invocation_id`, event type, and payload.
- Multiple Agents in one Execution share one chronological file; `agent_role`, `agent_name`, and `invocation_id` are mandatory filters.
- Trace failures are fail-open and emit at most one `agent_trace_write_failed` Runtime warning per run.
- Trace content must not enter knowledge vault, SSE, timeline, ordinary logging, Session APIs, or Git.
- Do not add a viewer, download API, remote sink, compression, retention job, or automatic deletion.
- Preserve all unrelated dirty R3 files and local planning files; stage only files named by the current task.
- Repository workflow for this R2 increment requires one Agent to execute the plan inline; do not create implementation subagents.

---

## File Structure

- `backend/app/diagnostics/agent_trace.py`: trace identity/event contracts, safe serializer, workspace path initialization, append/sequence/fsync writer, and trace parsing helper used by tests.
- `backend/app/middleware/agent_trace_middleware.py`: model/Tool request-response-error interception for one concrete Agent identity.
- `backend/app/agents/agent_factory.py`: mandatory concrete `execution_name`, resolved Provider model ID propagation, and automatic trace middleware injection.
- `backend/app/agents/{single_review_agents,review_round_agents,question_curation_agent}.py`: explicit stable names for existing Agents that currently rely on role fallback.
- `backend/app/security/workspace_paths.py`: dedicated `diagnostics.agent_traces` scope.
- `backend/app/application/{workspace_runtime,execution_service}.py`: trace directory initialization, shared writer injection, Execution boundary events, and fail-open warning projection.
- `backend/app/middleware/{middleware_stack,summarization_middleware}.py`: internal `context_summary` trace integration.
- `backend/tests/test_agent_trace_writer.py`: path, JSONL, sequence, restart, concurrency, serialization, and secret-leak tests.
- `backend/tests/test_agent_trace_middleware.py`: model/Tool success/error and multi-Agent identity tests.
- Existing focused tests verify factory injection, middleware stack ordering, path policy, Execution lifecycle, and all Agent call sites.

### Task 1: Build the Safe JSONL Writer and Serializer

**Files:**

- Create: `backend/app/diagnostics/__init__.py`
- Create: `backend/app/diagnostics/agent_trace.py`
- Modify: `backend/app/security/workspace_paths.py`
- Create: `backend/tests/test_agent_trace_writer.py`
- Modify: `backend/tests/test_workspace_paths.py`

**Interfaces:**

- Consumes: `AgentContext.workspace_root`, `WorkspacePathPolicy`, LangChain `BaseMessage`, Pydantic `BaseModel`.
- Produces: `TraceIdentity`, `AgentTraceWriter.append(identity, event_type, payload, *, terminal=False) -> bool`, `safe_trace_value(value) -> JSONValue`, and `initialize_agent_trace_directory(workspace_root) -> Path`.

- [ ] **Step 1: Write failing writer, path, and leak-prevention tests**

```python
def identity(root: Path, *, agent_name: str = "question_discovery") -> TraceIdentity:
    return TraceIdentity(
        workspace_id="w1",
        workspace_root=root,
        session_id="s1",
        run_id="r1",
        agent_role="question_generation",
        agent_name=agent_name,
        invocation_id="inv-1",
    )


def test_writer_appends_parseable_ordered_events_and_resumes_sequence(tmp_path: Path):
    initialize_agent_trace_directory(tmp_path)
    assert AgentTraceWriter().append(identity(tmp_path), "model.request", {"text": "完整原文"})
    assert AgentTraceWriter().append(identity(tmp_path), "model.response", {"text": "完整回答"}, terminal=True)
    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[0]["payload"]["text"] == "完整原文"
    assert rows[1]["payload"]["text"] == "完整回答"


def test_safe_serializer_never_uses_unknown_repr_or_credentials(tmp_path: Path):
    class SecretObject:
        def __repr__(self) -> str:
            return "Bearer leaked-token"

    value = safe_trace_value({
        "content": "Bearer is legitimate interview text",
        "authorization": "Bearer leaked-token",
        "api_key": "sk-leaked",
        "client": SecretObject(),
    })
    encoded = json.dumps(value, ensure_ascii=False)
    assert "legitimate interview text" in encoded
    assert "leaked-token" not in encoded
    assert "sk-leaked" not in encoded
    assert value["client"] == {"type": "SecretObject", "unserializable": True}


def test_trace_path_rejects_symlink_and_invalid_identifier(tmp_path: Path):
    initialize_agent_trace_directory(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    trace_root = tmp_path / ".cyber-interview-agent" / "agent-traces"
    (trace_root / "s1").symlink_to(outside)
    with pytest.raises(PathPolicyError):
        AgentTraceWriter().append(identity(tmp_path), "model.request", {})
    with pytest.raises(PathPolicyError):
        AgentTraceWriter().append(replace(identity(tmp_path), session_id="../escape"), "model.request", {})
```

- [ ] **Step 2: Run the focused tests and verify the expected import failures**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_writer.py tests/test_workspace_paths.py`

Expected: FAIL because `app.diagnostics.agent_trace`, `TraceIdentity`, and the `diagnostics.agent_traces` scope do not exist.

- [ ] **Step 3: Implement the contracts, safe serializer, directory initialization, and append writer**

```python
TraceEventType = Literal[
    "execution.started", "execution.completed", "execution.failed",
    "model.request", "model.response", "model.error",
    "tool.request", "tool.response", "tool.error",
]


@dataclass(frozen=True, slots=True)
class TraceIdentity:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    agent_role: str
    agent_name: str
    invocation_id: str


class AgentTraceWriter:
    _locks: ClassVar[dict[Path, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def append(
        self,
        identity: TraceIdentity,
        event_type: TraceEventType,
        payload: object,
        *,
        terminal: bool = False,
    ) -> bool:
        path = self._trace_path(identity)
        lock = self._lock_for(path)
        with lock:
            sequence = self._last_complete_sequence(path) + 1
            row = {
                "schema_version": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "sequence": sequence,
                "event_id": str(uuid4()),
                "workspace_id": identity.workspace_id,
                "session_id": identity.session_id,
                "run_id": identity.run_id,
                "agent_role": identity.agent_role,
                "agent_name": identity.agent_name,
                "invocation_id": identity.invocation_id,
                "event_type": event_type,
                "payload": safe_trace_value(payload),
            }
            encoded = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("agent trace append made no progress")
                    remaining = remaining[written:]
                if terminal:
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return True
```

Add `"diagnostics.agent_traces": Path(".cyber-interview-agent/agent-traces")` to `SCOPE_PATHS`. Validate every session/run segment with `re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value)`, create directories one level at a time, reject symlinks with `lstat`, open the final file with `O_NOFOLLOW` when the platform exposes it, use mode `0o700` for directories and `0o600` for files, and treat only newline-terminated rows as complete when recovering sequence after a crash.

`safe_trace_value` must explicitly handle `None`, booleans, numbers, strings, lists/tuples, dictionaries, Pydantic models via `model_dump(mode="json")`, and LangChain messages through a field whitelist. Drop dictionary keys matching `api_key`, `authorization`, `cookie`, `headers`, `secret`, `secret_ref`, `access_token`, `refresh_token`, `id_token`, `client`, and `credentials` case-insensitively unless the key is exactly `content`; retain usage keys such as `input_tokens`, `output_tokens`, and `total_tokens`. Unknown objects become `{ "type": type(value).__name__, "unserializable": True }`.

- [ ] **Step 4: Run writer tests and verify permissions and JSONL invariants**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_writer.py tests/test_workspace_paths.py`

Expected: PASS; every non-empty trace line parses independently, sequences survive a new writer instance, invalid paths never create files outside the trace root, and secret fixture bytes are absent.

- [ ] **Step 5: Commit the writer slice**

```bash
git add backend/app/diagnostics/__init__.py backend/app/diagnostics/agent_trace.py backend/app/security/workspace_paths.py backend/tests/test_agent_trace_writer.py backend/tests/test_workspace_paths.py
git commit -m "feat(agent): add safe jsonl trace writer"
```

### Task 2: Trace Every Concrete Agent Model and Tool Invocation

**Files:**

- Create: `backend/app/middleware/agent_trace_middleware.py`
- Modify: `backend/app/agents/agent_factory.py`
- Modify: `backend/app/agents/single_review_agents.py`
- Modify: `backend/app/agents/review_round_agents.py`
- Modify: `backend/app/agents/question_curation_agent.py`
- Modify: `backend/tests/test_agent_factory.py`
- Create: `backend/tests/test_agent_trace_middleware.py`

**Interfaces:**

- Consumes: `AgentTraceWriter`, `TraceIdentity`, LangChain `ModelRequest`, `ModelResponse`, `ToolCallRequest`, and `AgentContext`.
- Produces: `AgentTraceMiddleware(writer, *, agent_role, agent_name, provider_model_id)` and a required non-empty `AgentSpec.execution_name`.

- [ ] **Step 1: Write failing tests for model success/error, Tool pairing, and Agent identity**

```python
def fake_context(tmp_path: Path) -> AgentContext:
    initialize_agent_trace_directory(tmp_path)
    return AgentContext(
        workspace_id="w1", workspace_root=tmp_path, session_id="s1", run_id="r1",
        allowed_tools=frozenset({"read_personal_evidence"}), allowed_scopes=frozenset(),
    )


def fake_model_request(tmp_path: Path, *, messages: list[BaseMessage]):
    return SimpleNamespace(
        messages=messages, system_message=SystemMessage(content="系统提示"),
        tools=[], response_format=None, model_settings={"temperature": 0},
        runtime=SimpleNamespace(context=fake_context(tmp_path)),
    )


def fake_tool_request(tmp_path: Path, *, name: str, args: dict[str, object]):
    return SimpleNamespace(
        tool_call={"id": "call-1", "name": name, "args": args},
        runtime=SimpleNamespace(context=fake_context(tmp_path)),
    )


async def async_value(value):
    return value


@pytest.mark.asyncio
async def test_model_timeout_keeps_request_and_pairs_error(tmp_path: Path):
    middleware = AgentTraceMiddleware(
        AgentTraceWriter(), agent_role="question_generation",
        agent_name="question_discovery", provider_model_id="provider-model-1",
    )
    request = fake_model_request(tmp_path, messages=[HumanMessage(content="完整来源")])

    async def fail(_request):
        raise APITimeoutError(request=httpx.Request("POST", "https://provider.test"))

    with pytest.raises(APITimeoutError):
        await middleware.awrap_model_call(request, fail)
    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert [row["event_type"] for row in rows] == ["model.request", "model.error"]
    assert rows[0]["invocation_id"] == rows[1]["invocation_id"]
    assert rows[0]["agent_name"] == "question_discovery"
    assert rows[0]["payload"]["messages"][0]["content"] == "完整来源"


@pytest.mark.asyncio
async def test_tool_success_records_full_args_and_result(tmp_path: Path):
    middleware = AgentTraceMiddleware(
        AgentTraceWriter(), agent_role="agent_chat",
        agent_name="profile_chat", provider_model_id="provider-model-1",
    )
    request = fake_tool_request(tmp_path, name="read_personal_evidence", args={"evidence_id": "ev-1"})
    result = await middleware.awrap_tool_call(
        request,
        lambda _request: async_value(ToolMessage(content="完整证据", tool_call_id="call-1")),
    )
    assert result.content == "完整证据"
    rows = read_trace_rows(tmp_path, "s1", "r1")
    assert rows[0]["payload"]["args"] == {"evidence_id": "ev-1"}
    assert rows[1]["payload"]["result"]["content"] == "完整证据"
    assert rows[0]["invocation_id"] == rows[1]["invocation_id"]


def test_agent_spec_requires_concrete_name():
    with pytest.raises(TypeError):
        AgentSpec(role="agent_chat", prompt=TEST_PROMPT)
```

- [ ] **Step 2: Run focused middleware/factory tests and verify they fail**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_middleware.py tests/test_agent_factory.py`

Expected: FAIL because trace middleware is absent, `execution_name` is optional, and `AgentFactory` does not inject tracing.

- [ ] **Step 3: Implement the mandatory trace middleware and concrete Agent names**

```python
class AgentTraceMiddleware(AgentMiddleware):
    def __init__(self, writer, *, agent_role: str, agent_name: str, provider_model_id: str):
        self._writer = writer
        self._agent_role = agent_role
        self._agent_name = agent_name
        self._provider_model_id = provider_model_id

    async def awrap_model_call(self, request, handler):
        invocation_id = str(uuid4())
        identity = self._identity(request.runtime.context, invocation_id)
        await self._append(identity, "model.request", self._model_request_payload(request))
        try:
            response = await handler(request)
        except Exception as error:
            await self._append(identity, "model.error", safe_error_payload(error), terminal=True)
            raise
        await self._append(identity, "model.response", self._model_response_payload(response), terminal=True)
        return response

    async def awrap_tool_call(self, request, handler):
        invocation_id = str(request.tool_call.get("id") or uuid4())
        identity = self._identity(request.runtime.context, invocation_id)
        await self._append(identity, "tool.request", {
            "tool_name": request.tool_call["name"],
            "args": request.tool_call.get("args", {}),
        })
        try:
            result = await handler(request)
        except Exception as error:
            await self._append(identity, "tool.error", safe_error_payload(error), terminal=True)
            raise
        await self._append(identity, "tool.response", {"result": result}, terminal=True)
        return result
```

`_append` must call `AgentTraceWriter.append` through `asyncio.to_thread`, catch every trace exception, invoke `context.trace_warning("agent_trace_write_failed")` once when a sink exists, and never alter the wrapped model/Tool return or exception.

Change `AgentSpec` to require `execution_name: str` and reject blank names in `__post_init__`. Construct one `AgentTraceMiddleware` after resolving the Provider model ID and prepend it to every `create_agent(..., middleware=(trace_middleware, *spec.middleware))` tuple, making it the outer Tool wrapper so policy denials are recorded as `tool.response` with error status. Expose `AgentFactory.trace_writer` for Execution and summarization integration. Pass only the already validated Provider model record ID into the middleware; do not inspect or dump the resolved SDK model.

Assign stable names to all existing call sites:

```python
single_review_evaluator
single_review_reporter
review_round_evaluator
review_round_reporter
review_discussion
question_curation
curation_command_classifier
curation_context_summarizer
curation_command_responder
profile_extraction
profile_assessment
profile_chat
profile_action_planner
```

The progressive curation plan replaces `question_curation` with `question_discovery`, `question_enrichment`, and `question_revision` without changing the trace contract.

- [ ] **Step 4: Run middleware, factory, and current Agent contract tests**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_middleware.py tests/test_agent_factory.py tests/test_question_curation_graph.py tests/test_review_agent_graph.py tests/test_review_round_graph.py tests/test_curation_command_agent.py tests/test_profile_agents.py`

Expected: PASS; factory-created Agents always contain exactly one trace middleware, multiple Agent names in one run share a file, and every request-response/error pair shares one invocation ID.

- [ ] **Step 5: Commit the global Agent integration**

```bash
git add backend/app/middleware/agent_trace_middleware.py backend/app/agents/agent_factory.py backend/app/agents/single_review_agents.py backend/app/agents/review_round_agents.py backend/app/agents/question_curation_agent.py backend/tests/test_agent_factory.py backend/tests/test_agent_trace_middleware.py
git commit -m "feat(agent): trace model and tool exchanges"
```

### Task 3: Add Execution Boundaries, Internal Summary Traces, and Acceptance Evidence

**Files:**

- Modify: `backend/app/agents/context.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/middleware/middleware_stack.py`
- Modify: `backend/app/middleware/summarization_middleware.py`
- Modify: `backend/tests/test_agent_middleware_stack.py`
- Modify: `backend/tests/test_agent_routes_v2.py`
- Modify: `backend/tests/test_curation_command_middleware.py`
- Modify: `docs/verification/r2-complete-review-agent.md`

**Interfaces:**

- Consumes: `AgentFactory.trace_writer`, `SqliteMiddlewareProjection.warning`, and the writer/middleware contracts from Tasks 1-2.
- Produces: `AgentContext.trace_warning: Callable[[str], None] | None`, Execution boundary rows, and `agent_name="context_summary"` rows for automatic compaction calls.

- [ ] **Step 1: Write failing lifecycle, summary, and fail-open tests**

```python
async def wait_for_execution(api, session_id: str, execution_id: str, target: str) -> None:
    for _attempt in range(100):
        response = await api.get(f"/api/agent/sessions/{session_id}")
        latest = response.json()["latestExecution"]
        if latest["id"] == execution_id and latest["status"] == target:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"execution {execution_id} did not reach {target}")


async def run_fake_agent_execution(api) -> tuple[str, str]:
    session = (await api.post("/api/agent/sessions", json={"kind": "test.echo"})).json()
    execution = (await api.post(
        f"/api/agent/sessions/{session['id']}/executions",
        json={"input": {"text": "ping"}},
    )).json()
    await wait_for_execution(api, session["id"], execution["id"], "completed")
    return session["id"], execution["id"]


class FailingTraceWriter:
    def append(self, *args, **kwargs):
        raise OSError("disk unavailable")


class FakeResolver:
    def __init__(self, model):
        self.model = model

    def resolve(self, **_kwargs):
        return self.model


TEST_PROMPT = PromptSpec(id="trace-test", version="1.0", system="回答问题")


@pytest.mark.asyncio
async def test_execution_trace_has_terminal_boundaries(api, workspace_root):
    session_id, run_id = await run_fake_agent_execution(api)
    rows = read_trace_rows(workspace_root, session_id, run_id)
    assert rows[0]["event_type"] == "execution.started"
    assert rows[-1]["event_type"] == "execution.completed"
    assert rows[-1]["agent_name"] == "execution_runtime"


@pytest.mark.asyncio
async def test_context_compaction_is_named_separately(tmp_path: Path):
    middleware = ProjectingSummarizationMiddleware(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="摘要")])),
        trigger=("messages", 2), keep=("messages", 1),
        projection=FakeProjection(), threshold_tokens=1,
        trace_writer=AgentTraceWriter(), provider_model_id="provider-model-1",
    )
    await middleware.abefore_model(
        {"messages": [
            HumanMessage(content="第一轮"), AIMessage(content="第二轮"),
            HumanMessage(content="第三轮"),
        ]},
        SimpleNamespace(context=fake_context(tmp_path)),
    )
    rows = read_trace_rows(tmp_path, "s1", "r1")
    summary_rows = [row for row in rows if row["agent_name"] == "context_summary"]
    assert [row["event_type"] for row in summary_rows] == ["model.request", "model.response"]


@pytest.mark.asyncio
async def test_trace_write_failure_warns_once_and_keeps_agent_success(tmp_path: Path):
    warnings: list[str] = []
    context = replace(
        fake_context(tmp_path),
        trace_warning=warnings.append,
    )
    agent = AgentFactory(
        FakeResolver(GenericFakeChatModel(messages=iter([AIMessage(content="answer")]))),
        trace_writer=FailingTraceWriter(),
    ).create(
        AgentSpec(role="agent_chat", execution_name="test_chat", prompt=TEST_PROMPT),
        model_bindings={"agent_chat": "model-1"},
    )
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="q")]}, context=context
    )
    assert result["messages"][-1].text == "answer"
    assert warnings == ["agent_trace_write_failed"]
```

- [ ] **Step 2: Run focused lifecycle tests and verify missing boundaries/summary rows**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_middleware_stack.py tests/test_agent_routes_v2.py tests/test_curation_command_middleware.py`

Expected: FAIL because Execution lifecycle and automatic compaction do not use the trace writer and `AgentContext` has no warning sink.

- [ ] **Step 3: Wire shared writer, fail-open warning, Execution boundaries, and compaction**

```python
@dataclass(frozen=True, slots=True)
class AgentContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]
    progress_scope: tuple[str, ...] = ()
    agent_role: str | None = None
    tool_result_item_limit: int = 50
    tool_excerpt_char_limit: int = 2000
    trace_warning: Callable[[str], None] | None = field(default=None, repr=False, compare=False)
```

Initialize the trace root during `WorkspaceRuntime.create`, reuse `graph_factory.agents.trace_writer` for `AgentExecutionService`, and bind `trace_warning` to the existing `runtime_warnings` projection using the known session/run IDs. Add a private Execution helper:

```python
async def _trace_execution(self, context: AgentContext, event_type: TraceEventType, payload: dict[str, object], *, terminal: bool = False) -> None:
    identity = TraceIdentity(
        workspace_id=context.workspace_id,
        workspace_root=context.workspace_root,
        session_id=context.session_id,
        run_id=context.run_id,
        agent_role=context.agent_role or "execution",
        agent_name="execution_runtime",
        invocation_id=context.run_id,
    )
    try:
        await asyncio.to_thread(self._trace_writer.append, identity, event_type, payload, terminal=terminal)
    except Exception:
        if context.trace_warning is not None:
            context.trace_warning("agent_trace_write_failed")
```

Call it immediately before Graph execution and immediately after completed/failed transitions. Error payloads use `safe_error_payload`; cancelled/interrupted executions do not pretend to be completed and use the existing product terminal state inside an `execution.failed` payload with `status="cancelled"` or `status="interrupted"` only when the Execution cannot continue.

Extend `ProjectingSummarizationMiddleware` with `trace_writer` and `provider_model_id`. When compaction triggers, log the exact trimmed summary prompt before `self.model.ainvoke`, then the returned AI message or safe error as `agent_role="report_summarization"`, `agent_name="context_summary"`. Preserve upstream token trimming and fallback summary behavior. `build_default_middleware` passes the shared writer and resolved summary Provider model ID.

- [ ] **Step 4: Run focused and complete backend regression**

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q tests/test_agent_trace_writer.py tests/test_agent_trace_middleware.py tests/test_agent_factory.py tests/test_agent_middleware_stack.py tests/test_agent_routes_v2.py tests/test_curation_command_middleware.py tests/test_tool_policy_middleware.py`

Expected: PASS.

Run: `cd backend && UV_CACHE_DIR=/tmp/cyber-interview-uv-cache uv run pytest -q`

Expected: PASS with no regressions; trace files are created only inside pytest temporary workspaces.

- [ ] **Step 5: Perform one local multi-Agent JSONL acceptance check**

Run one fake or configured local curation Execution that invokes at least two concrete Agents, then run:

```bash
find .cyber-interview-agent/agent-traces -name '*.jsonl' -type f -print0 | xargs -0 -n1 jq -r '[.sequence,.agent_role,.agent_name,.invocation_id,.event_type] | @tsv'
```

Expected: sequences are monotonic; each model/Tool pair shares an invocation ID; concrete Agent names are distinguishable in one chronological file; no credential fixture appears under `rg -n 'sk-|Bearer |Authorization|secret_ref'`.

Record only IDs, counts, event types, and pass/fail evidence in `docs/verification/r2-complete-review-agent.md`; do not copy local trace content into the verification document.

- [ ] **Step 6: Commit the lifecycle and verification slice**

```bash
git add backend/app/agents/context.py backend/app/application/workspace_runtime.py backend/app/application/execution_service.py backend/app/middleware/middleware_stack.py backend/app/middleware/summarization_middleware.py backend/tests/test_agent_middleware_stack.py backend/tests/test_agent_routes_v2.py backend/tests/test_curation_command_middleware.py
git commit -m "feat(agent): complete local jsonl execution traces"
```

Keep `docs/verification/r2-complete-review-agent.md` as a synchronized local verification artifact; do not stage or commit it.
