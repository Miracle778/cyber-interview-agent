# Agent Runtime Framework Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the parallel project Runtime with LangChain `create_agent`, official `AgentMiddleware`, standard tools, and LangGraph-native persistence/streaming before R2.

**Architecture:** Explicit domain `StateGraph` workflows call role-specific `create_agent` nodes or subgraphs. LangGraph owns execution state, checkpoints, interrupts, and streams; application services project only user-facing sessions, actions, events, drafts, publications, usage, and audit data. The migration is intentionally incompatible with the old Runtime database, API internals, checkpoints, and Python protocols, and no dual-stack compatibility bridge is permitted.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic 2, LangChain 1.3.12, LangGraph 1.2.8, SQLite/WAL, OpenTelemetry, local Langfuse v3, React 19, TanStack Query, TypeScript, Vitest, Playwright.

## Global Constraints

- Archive baseline: `archive/pre-agent-runtime-refactor-2026-07-13` at `main@8e1b500`.
- Work only in `/private/tmp/cyber-interview-agent-runtime-convergence` on `codex/agent-runtime-framework-convergence`.
- Do not preserve old Runtime SQLite rows, checkpoints, API schemas, SSE event names, or internal Python protocols.
- Do preserve and re-prove product capabilities and security invariants: Workspace isolation, secret non-disclosure, HITL decisions, draft/version/hash publication, restart recovery, observability fail-open, and the review-to-publication browser flow.
- `create_agent` and official `AgentMiddleware` are the only Agent loop and middleware protocols.
- Domain publication, Vault writes, index updates, and compensating actions stay explicit; never hide them in generic middleware.
- Keep the current frontend layout and visual system; rewrite only data/state integration and necessary status copy.
- One Agent owns the slice; no subagents. Use targeted TDD and no more than one cross-layer integration regression plus one final full regression.
- Do not modify or commit `docs/my_idea.md`; local verification/learning artifacts are synchronized explicitly after merge.

---

## File Map

| Area | New responsibility | Replaces |
|---|---|---|
| `backend/app/agents/model_resolver.py` | Resolve a role binding directly to `BaseChatModel` | `runtime/model_resolver.py`, gateway envelopes |
| `backend/app/agents/factory.py` | Build role-specific `create_agent` graphs | GraphBuildContext model ports |
| `backend/app/agents/context.py` | Narrow runtime context injected by LangChain | broad middleware/tool contexts |
| `backend/app/graphs/review.py` | Explicit review domain topology | `agents/review_definition.py` and legacy review graph |
| `backend/app/graphs/publication.py` | Explicit knowledge publication topology | `runtime/knowledge_publication_graph.py` |
| `backend/app/middleware/` | Direct official `AgentMiddleware` and built-in composition | `runtime/middleware/` pipeline and adapter |
| `backend/app/tools/` | Standard LangChain tools plus project handlers/policies | `ToolRegistry`, `BoundToolInvoker` |
| `backend/app/application/` | Session, execution, approval, event projection | `AgentRuntime`, `RunManager`, `EventStream` orchestration |
| `backend/app/infrastructure/` | Runtime SQLite, checkpointer, providers, telemetry | scattered runtime/db/provider infrastructure |
| `frontend/src/features/agent/` | New resources and stream projection | old run/watch/action event coupling |

## Test Disposition

### KEEP

- Domain/security tests: `test_workspace_paths.py`, `test_atomic_writer.py`, `test_knowledge_drafts.py`, `test_publication_service.py`, `test_hitl_repository.py`, `test_hitl_service.py`, `test_tool_audit.py`, Provider settings/service tests, Markdown/search/Vault tests.
- Frontend visual behavior tests for Settings, Knowledge, Markdown and responsive layout where they do not assert old Agent API shapes.

### REWRITE

- `test_review_definition.py`, `test_review_runtime_integration.py` → new AgentFactory and review Graph behavior tests.
- `test_agent_routes.py`, `test_hitl_routes.py`, `test_hitl_restart.py` → new application/API interrupt and restart tests.
- `test_context_title_middleware.py`, `test_loop_guard_middleware.py`, `test_model_usage_middleware.py`, `test_observability.py` → official middleware integration tests.
- `test_event_stream.py` → LangGraph stream-to-product-event projection tests.
- `ReviewPage.test.tsx`, `ActionCenter.test.tsx`, `useAgentEvents.test.tsx`, `agentApi.test.ts` → new API/event resources while retaining user-visible behavior.

### DELETE

- `test_runtime_middleware_pipeline.py`, `test_hitl_middleware_adapter.py` adapter-only assertions.
- `test_chat_gateway.py`, old structured/stream adapter invocation-envelope assertions.
- `test_tool_registry.py`, `test_tool_executor.py` assertions that only enforce the custom registry/executor.
- `test_graph_registry.py`, `test_run_manager.py`, `test_runtime_repository.py` assertions that only enforce the old mirrored Runtime state machine.
- `test_review_graph.py` and legacy deterministic review graph fixtures.

Before deleting a mixed test file, copy any still-valid capability assertion into the named replacement test. No replacement is required for implementation-only assertions.

### Task 1: Establish the official Agent core and migrate review model work

**Files:**

- Create: `backend/app/agents/context.py`
- Create: `backend/app/agents/model_resolver.py`
- Create: `backend/app/agents/factory.py`
- Create: `backend/app/agents/review.py`
- Create: `backend/app/graphs/__init__.py`
- Create: `backend/app/graphs/review.py`
- Create: `backend/tests/test_agent_factory.py`
- Create: `backend/tests/test_review_agent_graph.py`
- Test disposition: begin rewriting `test_review_definition.py` and `test_review_runtime_integration.py`; do not delete old production code yet.

**Interfaces:**

- Produces `AgentContext(workspace_id, session_id, run_id, allowed_tools, allowed_scopes)` as the only LangChain runtime context.
- Produces `ChatModelResolver.resolve(role: str, provider_model_id: str) -> BaseChatModel`.
- Produces `AgentSpec` and `AgentFactory.create(spec, *, model_bindings, checkpointer=None)` returning a compiled `create_agent` graph.
- Produces `ReviewAgents.evaluate(...) -> AnswerEvaluation` and `ReviewAgents.report(...) -> str` backed by official agents.
- Produces `create_review_graph(dependencies) -> CompiledStateGraph` with explicit evaluate/report nodes and no publication side effects yet.

- [x] **Step 1: Write RED tests for direct model resolution**

Create `test_agent_factory.py` with disabled-model, missing-secret, OpenAI-compatible and Anthropic-compatible cases. Assert the resolver returns `BaseChatModel`, preserves configured `base_url`/model, and never returns API keys from `repr()` or serialized Agent context.

```python
model = resolver.resolve(role="answer_evaluation", provider_model_id=model_record.id)
assert isinstance(model, BaseChatModel)
assert "test-secret" not in repr(model)
```

Run: `pytest -q tests/test_agent_factory.py`

Expected: FAIL because the new resolver/factory modules do not exist.

- [x] **Step 2: Implement `AgentContext` and direct `ChatModelResolver`**

Use a frozen dataclass for safe runtime context:

```python
@dataclass(frozen=True, slots=True)
class AgentContext:
    workspace_id: str
    session_id: str
    run_id: str
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]
```

Construct `ChatOpenAI` with `stream_usage=True`, timeout 30 seconds and the saved compatible base URL; construct `ChatAnthropic` with the compatible base URL and timeout. Translate missing/disabled provider/model/secret to existing stable provider error codes without wrapping model invocation results.

Run: `pytest -q tests/test_agent_factory.py`

Expected: resolver tests PASS; factory tests remain RED.

- [x] **Step 3: Implement and test `AgentFactory` using real `create_agent`**

Define:

```python
@dataclass(frozen=True, slots=True)
class AgentSpec:
    role: str
    system_prompt: str
    tools: tuple[BaseTool, ...] = ()
    middleware: tuple[AgentMiddleware, ...] = ()
    response_format: type[BaseModel] | None = None

class AgentFactory:
    def create(self, spec: AgentSpec, *, model_bindings: Mapping[str, str]):
        model = self._models.resolve(spec.role, model_bindings[spec.role])
        return create_agent(
            model=model,
            tools=spec.tools,
            system_prompt=spec.system_prompt,
            middleware=spec.middleware,
            response_format=spec.response_format,
            context_schema=AgentContext,
            name=spec.role,
        )
```

Patch `create_agent` only to assert composition arguments, then run one real graph invocation with the scripted test `BaseChatModel`. Do not introduce a project invocation wrapper.

Run: `pytest -q tests/test_agent_factory.py`

Expected: PASS.

- [x] **Step 4: Write RED review Agent/Graph behavior tests**

The scripted model must return an `AnswerEvaluation` structured response for the evaluator and Markdown for the reporter. Assert the domain state receives `evaluation` and `report_markdown`, while API keys and Provider records never enter the state.

```python
result = await graph.ainvoke(
    review_input,
    context=AgentContext(...),
    config={"configurable": {"thread_id": "session-1"}},
)
assert result["evaluation"]["score"] == "partial"
assert result["report_markdown"].startswith("# 单题复习")
```

Run: `pytest -q tests/test_review_agent_graph.py`

Expected: FAIL because review agents/graph do not exist.

- [x] **Step 5: Implement `ReviewAgents` and explicit review Graph**

Use two `AgentSpec` instances: evaluator with `response_format=AnswerEvaluation`, reporter with Markdown output. Read evaluator output from `structured_response`; read the reporter's final `AIMessage` using LangChain message helpers. Keep draft creation/publication out of this task.

Run: `pytest -q tests/test_agent_factory.py tests/test_review_agent_graph.py`

Expected: PASS.

- [x] **Step 6: Review Task 1 and commit**

Run: `git diff --check` and targeted tests above. Confirm no new `Gateway`, `Invoker`, `Pipeline`, or generic envelope type was added.

Commit: `refactor(agent): establish official agent execution core`

### Task 2: Convert tools and migrate HITL/publication as explicit domain behavior

**Files:**

- Create: `backend/app/tools/runtime_tools.py`
- Create: `backend/app/middleware/tool_policy.py`
- Create: `backend/app/application/approval_service.py`
- Create: `backend/app/graphs/publication.py`
- Create: `backend/tests/test_runtime_tools.py`
- Create: `backend/tests/test_tool_policy_middleware.py`
- Create: `backend/tests/test_approval_execution.py`
- Modify: `backend/app/graphs/review.py`
- Modify: `backend/app/hitl/models.py`
- Modify: `backend/app/hitl/repository.py`
- Modify: `backend/app/hitl/service.py`
- Modify: `backend/app/knowledge/publication_handler.py`
- Keep domain tests named in KEEP; rewrite HITL/runtime integration tests.

**Interfaces:**

- Produces standard `BaseTool` instances `read_source`, `read_active_knowledge`, `write_review_draft`, and `diagnostic_read`.
- Produces `ToolPolicyMiddleware(AgentMiddleware)` enforcing allowed tool/scope, metadata-only audit, sanitization and stable errors in `awrap_tool_call`.
- Produces `ApprovalService.project_interrupt(...)`, `approve(...)`, and `reject(...)` using official HITL decision payloads and `Command(resume=...)`.
- Produces explicit publication Graph inputs containing `draft_id`, `draft_version`, `content_hash`, title and Markdown.

- [x] **Step 1: Write RED tests for standard tool schemas and injected context**

Assert each tool is a `BaseTool`, exposes only business arguments, receives `ToolRuntime[AgentContext]` as injected context, blocks Workspace traversal, and returns JSON-safe Pydantic output.

Run: `pytest -q tests/test_runtime_tools.py tests/test_workspace_paths.py`

Expected: new tool test FAIL; existing path tests PASS.

- [x] **Step 2: Implement standard tools without a registry**

Adapt existing file handlers behind `@tool(args_schema=...)`; obtain workspace/run identity from `ToolRuntime.context`. Keep the final `WorkspacePathPolicy` check inside the handler. Build tool tuples explicitly per Agent spec rather than globally registering by name.

Run: same command. Expected: PASS.

- [x] **Step 3: Write RED middleware tests for scope, audit, sanitization and official HITL**

Build a real `create_agent` with `ToolPolicyMiddleware` followed by
`HumanInTheLoopMiddleware(interrupt_on={"write_review_draft": True})`. Assert denied scope returns a stable tool error without handler execution; allowed calls produce one audit record; risky calls interrupt before side effects.

Run: `pytest -q tests/test_tool_policy_middleware.py`

Expected: FAIL.

- [x] **Step 4: Implement `ToolPolicyMiddleware` and HITL composition**

Implement only official hooks. The middleware validates `request.tool_call`, reads `request.runtime.context`, starts/finishes metadata-only audit, sanitizes events, and calls the handler exactly once. Do not call `interrupt()` manually inside the middleware; official HITL owns the interrupt.

Run: targeted tool/middleware tests. Expected: PASS.

- [x] **Step 5: Write RED approval and publication tests**

Cover pending action projection from a real interrupt, approve/reject decision translation, duplicate idempotency key, restart using a SQLite checkpointer, draft version/hash conflict, edited approval, Vault publish, publication journal and index-stale.

Run: `pytest -q tests/test_approval_execution.py tests/test_publication_service.py tests/test_knowledge_drafts.py`

Expected: new execution tests FAIL while domain tests remain PASS.

- [x] **Step 6: Implement ApprovalService and explicit publication Graph**

Project the official interrupt payload into the product action repository. Store only safe preview and the thread/run identity. Resume with official decisions:

```python
Command(resume={"decisions": [{"type": "approve"}]})
Command(resume={"decisions": [{"type": "reject", "message": reason}]})
```

Knowledge publication remains its own Graph node/handler using draft version/hash and receipt idempotency. Review Graph creates a draft then enters the explicit publication request node.

Run: all Task 2 targeted tests. Expected: PASS.

- [ ] **Step 7: Delete registry/executor tests only after replacements pass and commit**

Delete `test_tool_registry.py`, `test_tool_executor.py`, and adapter-only HITL tests. Keep file/path/audit/domain tests. Run `rg` to prove new production code does not import `ToolRegistry`, `BoundToolInvoker`, or `PersistentHitlMiddleware`.

Commit: `refactor(agent): adopt standard tools and official hitl`

Deletion is intentionally executed with Task 4's production cutover. Until the new
application service owns the routes, the old entry point still imports the registry and
executor; deleting them earlier would make an otherwise green intermediate commit unusable.

### Task 3: Replace cross-cutting pipeline with official middleware and native stream projection

**Files:**

- Create: `backend/app/middleware/defaults.py`
- Create: `backend/app/middleware/usage.py`
- Create: `backend/app/middleware/session_title.py`
- Create: `backend/app/middleware/no_progress.py`
- Create: `backend/app/middleware/observability.py`
- Create: `backend/app/application/event_projector.py`
- Create: `backend/tests/test_agent_middleware_stack.py`
- Create: `backend/tests/test_event_projector.py`
- Modify: `backend/app/agents/factory.py`
- Modify: `backend/app/agents/review.py`
- Modify: Runtime persistence tables/repositories needed by product projections.

**Interfaces:**

- Produces `build_default_middleware(models, projections, policy) -> tuple[AgentMiddleware, ...]`.
- Uses official `SummarizationMiddleware`, `ContextEditingMiddleware`, `ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`, and `HumanInTheLoopMiddleware`.
- Produces narrow custom `UsageProjectionMiddleware`, `SessionTitleMiddleware`, `NoProgressMiddleware`, and `ObservabilityMiddleware` directly subclassing `AgentMiddleware`.
- Produces `AgentEventProjector.project(stream_part) -> tuple[ProductEvent, ...]` for LangGraph v2 stream output.

- [ ] **Step 1: Write RED tests for the middleware composition contract**

Assert the returned stack contains official middleware classes, stable configured limits, and only the four project middleware types. Assert no `MiddlewareLayer`, numeric order, adapter or project pipeline exists in the composition.

Run: `pytest -q tests/test_agent_middleware_stack.py`

Expected: FAIL.

- [ ] **Step 2: Implement official default stack**

Compose summary/context first, project policy/usage/observability around calls, call limits before execution, official HITL before risky tools, and title/no-progress hooks at lifecycle boundaries. Use explicit list order documented in the test; do not recreate numeric layers.

Run: middleware stack tests. Expected: composition tests PASS.

- [ ] **Step 3: Add RED behavior tests for usage, summary, title and no-progress**

Use scripted messages with native and missing usage metadata. Assert native usage is projected once, missing usage is marked estimated, long history triggers official summarization, title CAS never overwrites a user title, and repeated normalized tool/model progress raises a stable `no_progress` error. Assert persistence failure emits a warning but leaves a successful Agent result intact.

Run: `pytest -q tests/test_agent_middleware_stack.py`

Expected: new cases FAIL.

- [ ] **Step 4: Implement narrow project middleware**

Read standard request/response messages and `usage_metadata`; persist via injected projection ports after model completion. Keep summary state in official Agent messages/checkpoints and only project the current summary indicator to session metadata. Use safe hashes for semantic progress. Instrument official hooks through the existing OTel sink without prompt/tool-argument content.

Run: targeted tests. Expected: PASS.

- [ ] **Step 5: Write RED LangGraph stream projection tests**

Feed v2 `messages`, `updates`, `custom`, interrupt and error parts. Assert exactly one product event per visible transition, stable cursor order, safe payloads, no duplicate tool/model lifecycle events, and keepalive behavior at the HTTP boundary.

Run: `pytest -q tests/test_event_projector.py`

Expected: FAIL.

- [ ] **Step 6: Implement `AgentEventProjector` and commit**

Map only execution, text delta, approval, artifact/publication and recoverable warning events. Persist product events for browser replay; do not persist every internal LangGraph event.

Delete the old project pipeline/adapter tests after new middleware and event tests pass. Commit:

`refactor(agent): use official middleware and native streams`

### Task 4: Replace application Runtime, update frontend, delete the old stack, and accept the rewrite

**Files:**

- Create: `backend/app/application/session_service.py`
- Create: `backend/app/application/execution_service.py`
- Create: `backend/app/application/workspace_runtime.py`
- Create: `backend/app/infrastructure/runtime_database.py`
- Create or replace: fresh Runtime schema/migration files under `backend/app/db/migrations/runtime/`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes_agent.py`
- Modify: `backend/app/api/routes_hitl.py`
- Modify: `backend/app/schemas/agent.py`, `backend/app/schemas/hitl.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/features/agent/*`
- Modify: `frontend/src/features/review/*`
- Modify only data integration in Knowledge/Settings where new resources require it.
- Delete old production modules listed in the design deletion checklist after reference scans pass.

**Interfaces:**

- Produces small `AgentSessionService`, `AgentExecutionService`, and per-workspace dependency container.
- API resources expose product session, execution, messages, current interrupt/action, usage and visible events without mirroring internal Graph states.
- Frontend keeps current layout and consumes the new API/query/event contracts.

- [ ] **Step 1: Write RED application/API tests against the new resources**

Cover create/list/get session, start/cancel execution, approval decision, SSE replay cursor, fresh database startup, graceful old-schema rejection, restart recovery and stable safe errors. Do not assert old response fields or event names.

Run: `pytest -q tests/test_agent_routes_v2.py tests/test_agent_restart_v2.py`

Expected: FAIL.

- [ ] **Step 2: Implement fresh Runtime database and application services**

Create only tables needed for product sessions/messages/execution projections, product events, pending actions, domain records, usage/audit, and LangGraph checkpoint storage. Reject an old schema with an explicit development reset message; do not write migration adapters. Execution service invokes Graph `astream`, passes `thread_id=session.id`, projects events, handles interrupt/cancel/error, and closes resources on shutdown.

Run: new API/restart tests. Expected: PASS.

- [ ] **Step 3: Replace FastAPI dependencies/routes and write frontend RED tests**

Update route schemas around the new services. In frontend tests, assert the existing Review UI still creates a session, starts review, streams text, displays approval only when interrupted, approves/rejects, refreshes draft/publication state and shows actionable errors.

Run: `./node_modules/.bin/vitest run src/features/agent src/features/review`

Expected: FAIL until clients/hooks are updated.

- [ ] **Step 4: Update frontend data integration without visual redesign**

Replace API types, query keys and SSE event handling. Keep AppShell, ReviewPage regions, Knowledge workspace and Settings navigation. Remove old watch/run/action duplication and derive visible status from the session/execution/action resources plus product events.

Run: targeted frontend tests and `./node_modules/.bin/tsc --noEmit`.

Expected: PASS.

- [ ] **Step 5: Delete old Runtime and legacy tests**

Delete `AgentRuntime`, `RunManager`, `GraphBuildContext`, custom graph registry when no longer needed, `ChatModelGateway`, provider invocation envelopes, `ToolRegistry`, `BoundToolInvoker`, `runtime/middleware/`, legacy review files and tests marked DELETE. Preserve provider connection testing, domain repositories, security, audit and publication code still referenced.

Run static gates:

```bash
rg -n "RuntimeMiddlewarePipeline|LangChainRuntimeMiddlewareAdapter|ChatModelGateway|ToolRegistry|BoundToolInvoker|GraphBuildContext|build_review_graph" backend/app
```

Expected: no production matches.

- [ ] **Step 6: Run one cross-layer integration regression**

Run the new backend suite, frontend suite, typecheck and build once. Fix only failures caused by the rewrite; rerun affected files until stable. Record actual counts, not the old 281/75 target.

- [ ] **Step 7: Run browser and real Provider acceptance**

Run one minimal happy path before documentation, then one full pass covering desktop/375px, refresh, approve, reject, duplicate decision, backend restart, Vault target path, native/estimated usage, summary/title/no-progress, and Langfuse fail-open. Validate one real OpenAI-compatible structured response and one real Anthropic-compatible stream.

- [ ] **Step 8: Final full regression, documents and commit**

Run one final backend full suite, frontend full suite, typecheck/build, static deletion scan and stage documentation gate. Generate the risk-profiled learning pack only after implementation stabilizes. Explicitly synchronize ignored verification/learning files after merge.

Commit: `refactor(agent): complete runtime framework convergence`

## Execution Checkpoints and Token Budget

- Checkpoint 1 near 60k tokens: Task 1 complete and review model work runs through official agents.
- Checkpoint 2 near 120k tokens: Tasks 2–3 complete; standard tools, official HITL and middleware pass.
- Checkpoint 3 near 170k tokens: Task 4 old-stack deletion complete; only acceptance remains.
- Target total: 180k tokens; warn at 210k; stop and reassess architecture before 240k.
- If a task exceeds its expected budget by 30%, stop adding compatibility or scope and diagnose the boundary.

## Completion Boundary

The stage is complete only when the new Agent/Graph path passes real Provider and browser acceptance, old Runtime abstractions have no production references, the fresh database starts cleanly, core security/domain invariants pass, and final verification/learning artifacts are synchronized. Completion does not include R2 multi-question behavior or preservation of old test data.
