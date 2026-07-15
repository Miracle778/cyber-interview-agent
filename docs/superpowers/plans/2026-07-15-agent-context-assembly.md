# Agent Context Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary eight-message curation prompt with a reusable token-budgeted context assembler, durable curation focus, and deterministic-first command interpretation.

**Architecture:** A pure `ContextAssembler` selects structured state, a prior summary, recent complete turns, and prioritized resources without knowing review-domain fields. `CurationCommandInterpreter` owns the domain adapter and uses `Plan -> Validate -> Execute`: deterministic parsing first, a stateless structured classifier only for unresolved language, and existing application services for all side effects.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite additive migrations, LangChain `create_agent`, official `AgentMiddleware`, LangGraph checkpoints, pytest, React/Vitest.

## Global Constraints

- Work only in `/private/tmp/cyber-interview-agent-r2-ui-design` on `codex/r2-complete-review-agent`; do not create another worktree or dispatch subagents.
- Do not modify or commit `docs/my_idea.md`, `docs/learning/`, or `docs/verification/`.
- Keep `QuestionCurationAgent` as the question-generation business Agent; the command interpreter owns no tools, checkpoint, or side effects.
- Preserve publication, HITL, Vault, index, summary-version, candidate-state, and idempotency boundaries.
- Use `question_generation` for classification and `report_summarization` for compaction, while separating execution names from model roles.
- Use targeted RED/GREEN tests per task. Run one final backend suite, one final frontend suite/build, and one complete browser acceptance pass.
- R2 acceptance assumes no Langfuse configuration; observability remains fail-open.
- Run backend tests with `/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest` because the worktree-local virtualenv is incomplete.

---

### Task 1: Reusable token-budget context assembly

**Files:**
- Create: `backend/app/agents/context_assembly.py`
- Create: `backend/tests/test_context_assembly.py`
- Modify: `backend/app/agents/factory.py`
- Modify: `backend/tests/test_agent_factory.py`

**Interfaces:**
- Produces `ContextBudget`, `ContextMessage`, `ContextTurn`, `ContextResource`, `ContextSummary`, `ContextMaterial`, `AssembledContext`, `ContextBudgetExceededError`.
- Produces `ContextAssembler.assemble(material, budget, token_counter) -> AssembledContext`.
- Produces `model_token_counter(model) -> Callable[[str], int]`, preferring `model.get_num_tokens` and falling back to LangChain approximate counting when the provider counter fails.
- Adds `AgentSpec.execution_name: str | None = None`; model resolution still uses `role`, while `create_agent(name=...)` uses `execution_name or role`.

- [x] **Step 1: Add RED tests**

`test_context_assembly.py` must prove that output/system/schema/tool reservations reduce the available input, required material fails closed when it cannot fit, turns are never split, recent turns remain chronological, optional resources follow `(priority, ref)`, and omitted turns are returned as `overflow_turns`.

Use this concrete fixture shape:

```python
def _tokens(text: str) -> int:
    return len(text.split())


def test_assembler_keeps_complete_recent_turns():
    turns = tuple(
        ContextTurn((
            ContextMessage(f"u{i}", "user", "one two"),
            ContextMessage(f"a{i}", "assistant", "three four"),
        ))
        for i in range(3)
    )
    result = ContextAssembler().assemble(
        ContextMaterial("publish this", "state", ContextSummary.empty(), turns, ()),
        ContextBudget(max_input_tokens=18, reserved_output_tokens=4),
        _tokens,
    )
    assert result.recent_turns == turns[-2:]
    assert result.overflow_turns == turns[:1]
    assert result.threshold_tokens == 14
```

Extend `test_agent_factory_delegates_to_create_agent_without_invocation_wrapper` with `AgentSpec(role="question_generation", execution_name="curation_command_classifier", ...)`; assert resolver receives `question_generation` and `create_agent` receives name `curation_command_classifier`.

- [x] **Step 2: Verify RED**

Run:

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_context_assembly.py tests/test_agent_factory.py
```

Expected: FAIL because the module and `execution_name` do not exist.

- [x] **Step 3: Implement the core**

Use immutable dataclasses and this exact budget contract:

```python
@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_input_tokens: int
    reserved_output_tokens: int = 0
    reserved_system_tokens: int = 0
    reserved_schema_tokens: int = 0
    reserved_tool_tokens: int = 0

    @property
    def available_input_tokens(self) -> int:
        value = self.max_input_tokens - self.reserved_output_tokens \
            - self.reserved_system_tokens - self.reserved_schema_tokens \
            - self.reserved_tool_tokens
        if value <= 0:
            raise ContextBudgetExceededError()
        return value
```

`ContextMaterial` contains `current_input`, `working_state`, `prior_summary`, `turns`, and `resources`. `AssembledContext` exposes `estimated_input_tokens`, `threshold_tokens`, `recent_turns`, `overflow_turns`, `selected_resources`, and deterministic `render()`. Count fixed required material first; raise `context_budget_exceeded` instead of truncating it. Select whole recent turns newest-to-oldest, restore chronological order, then select optional resources by priority. The curation caller uses `max_input_tokens=int(model_context_limit * 0.70)` before subtracting output/system/schema/tool reservations so the assembled prompt stays below the existing summarization middleware trigger instead of being summarized a second time.

- [x] **Step 4: Verify GREEN and commit**

Run the Step 2 command. Expected: all selected tests PASS.

```bash
git add backend/app/agents/context_assembly.py backend/app/agents/factory.py backend/tests/test_context_assembly.py backend/tests/test_agent_factory.py
git commit -m "feat(agent): add token-budget context assembly"
```

---

### Task 2: Durable curation context projection

**Files:**
- Create: `backend/app/db/migrations/runtime/009_curation_context.sql`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/tests/test_runtime_migrations.py`
- Modify: `backend/tests/test_review_repository.py`

**Interfaces:**
- Produces `CurationContextRecord` with session ID, version, focused IDs, last intent, last-result IDs, summary dict, summary cursor, and timestamps.
- Produces `get_or_create_curation_context(session_id)` and compare-and-swap `replace_curation_context(..., expected_version)`.
- Produces `find_curation_command_receipt(session_id, idempotency_key, text, summary_version) -> CurationCommandReceiptRecord | None`; it validates the existing text hash/version before any context assembly or model call.
- Stale updates raise `ReviewConflictError("curation context version changed")`.

- [ ] **Step 1: Add RED migration/repository tests**

Expect table `review_curation_context` and migration versions `[1,2,3,4,5,6,7,8,9]` for fresh and existing generation-two databases. Add a repository round-trip that stores focus `("candidate-6",)`, `last_intent="inspect"`, summary refs, cursor `message-8`, and proves a second write with the old version conflicts. Add a receipt lookup test that returns `None` before creation, returns the same receipt afterward, and raises `ReviewConflictError` when the same key is reused with different text or summary version.

- [ ] **Step 2: Verify RED**

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_runtime_migrations.py tests/test_review_repository.py
```

Expected: FAIL because migration 9 and repository APIs do not exist.

- [ ] **Step 3: Add the migration and typed CAS repository**

Create this additive table:

```sql
CREATE TABLE review_curation_context (
    session_id TEXT PRIMARY KEY REFERENCES review_curation_sessions(session_id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    focused_candidate_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(focused_candidate_ids_json) AND json_type(focused_candidate_ids_json) = 'array'),
    last_intent TEXT,
    last_result_candidate_ids_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(last_result_candidate_ids_json) AND json_type(last_result_candidate_ids_json) = 'array'),
    dialogue_summary_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(dialogue_summary_json) AND json_type(dialogue_summary_json) = 'object'),
    summarized_through_message_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`get_or_create` uses `INSERT OR IGNORE` then `SELECT`. `replace` writes the complete projection, increments version, and uses `WHERE session_id = ? AND version = ?`. `find_curation_command_receipt` performs the existing `(session_id, idempotency_key)` query and hash/version validation without inserting a processing receipt; `begin_curation_command` reuses the same validator after interpretation to keep one idempotency rule.

- [ ] **Step 4: Verify GREEN and commit**

Run the Step 2 command. Expected: all selected tests PASS.

```bash
git add backend/app/db/migrations/runtime/009_curation_context.sql backend/app/review/models.py backend/app/review/repository.py backend/tests/test_runtime_migrations.py backend/tests/test_review_repository.py
git commit -m "feat(review): persist curation conversation focus"
```

---

### Task 3: Deterministic-first command interpreter and stateless model components

**Files:**
- Create: `backend/app/review/curation_command_contracts.py`
- Create: `backend/app/agents/curation_command.py`
- Create: `backend/app/review/curation_context.py`
- Create: `backend/tests/test_curation_command_agent.py`
- Create: `backend/tests/test_curation_context.py`
- Delete: `backend/app/agents/curation_intent.py`
- Delete: `backend/tests/test_curation_intent_agent.py`
- Modify: `backend/app/review/curation_commands.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/tests/test_curation_commands.py`
- Create: `backend/tests/test_curation_command_middleware.py`
- Delete: `backend/tests/test_curation_intent_middleware.py`

**Interfaces:**
- Moves `CandidateSelector` and renamed `CurationCommandPlan` into review contracts; adds `CurationDialogueSummary`.
- Produces `CurationCommandService.try_parse(text, summary, focused_candidate_ids) -> CurationCommandPlan | None` and `resolve_plan(plan=...)`.
- Produces `CurationCommandModels(classifier, summarizer, context_limit_tokens)`; both calls are stateless, tool-free, and checkpoint-free.
- Produces `CurationContextAdapter.recover_focus`, `build_material`, and `focus_after`.
- Produces `CurationCommandInterpreter.interpret(text, summary, focused_candidate_ids, context_provider) -> CurationCommandPlan`; it invokes the async `context_provider` only when deterministic parsing returns `None`.
- Renames factory method `create_curation_intent_agent` to `create_curation_command_models`.
- Renames `build_curation_intent_context` to `build_curation_command_context`.

- [ ] **Step 1: Add RED deterministic-parser and adapter tests**

Assert these exact cases:

```python
assert service.try_parse("发布第 6 题", summary, ()).publish.ordinals == [6]
assert service.try_parse("这题发布吧", summary, ("candidate-6",)).publish.ordinals == [6]
assert service.try_parse(
    "这题发布吧", summary, ("candidate-2", "candidate-6")
).clarification == "当前同时关联多道题，请明确要操作的题号。"
assert service.try_parse("加了备注的重新生成，其他的发布", summary, ()) is None
```

For the adapter, create twelve alternating visible messages and put `candidateIds=["candidate-6"]` on the latest assistant receipt. Assert only valid IDs recover, turns stay complete, candidate 6 becomes a required full resource, and all other candidates appear only in the compact working-state index.

- [ ] **Step 2: Verify parser RED**

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_curation_commands.py tests/test_curation_context.py
```

Expected: FAIL because focus-aware parsing, contracts, and adapter do not exist.

- [ ] **Step 3: Implement contracts, parser, and adapter**

`CurationCommandPlan` retains publish/reject/regenerate/inspect selectors, feedback, resummarize, clarification, and response. Unknown free language returns `None` from `try_parse`; unsafe multi-focus pronouns return a clarification plan. `resolve_plan` remains the single summary-version and selector validator.

`CurationCommandInterpreter.interpret` calls `try_parse` first and immediately returns its plan when present. Otherwise it awaits `context_provider()` exactly once and delegates the assembled result to the classifier. This lazy boundary is required so explicit commands do not assemble context or call either model.

`CurationContextAdapter.build_material` must include summary version, focus, and compact ordinal/title/status/recommendation/note index in working state; include full question/answer/key-points/follow-ups only for focused candidates; group only visible `text` and `command_receipt` records after the cursor; and exclude the current command from history.

- [ ] **Step 4: Verify parser GREEN**

Run Step 2. Expected: all selected tests PASS.

- [ ] **Step 5: Add RED classifier/summarizer tests**

Assert model roles stay `question_generation` and `report_summarization`, execution names become `curation_command_classifier` and `curation_context_summarizer`, neither runnable receives tools/checkpointer, classifier receives only rendered assembled context, summarizer receives prior summary plus overflow turns but no candidate/source bodies, and each invocation has a unique `progress_scope`.

- [ ] **Step 6: Verify model-component RED**

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_curation_command_agent.py tests/test_curation_command_middleware.py
```

Expected: FAIL because the renamed components and factory method do not exist.

- [ ] **Step 7: Implement one-shot model components**

Create strict structured-output `create_agent` runnables with empty tools, `checkpointer=None`, explicit execution names, and existing middleware. Classifier input is `AssembledContext.render()`. Summarizer input is only the prior `ContextSummary` and `overflow_turns`; it returns `CurationDialogueSummary`. Keep unique invocation IDs in `AgentContext.progress_scope` so no-progress fingerprints cannot collide.

- [ ] **Step 8: Verify GREEN and commit**

Run Steps 2 and 6. Expected: all selected tests PASS.

```bash
git add backend/app/review/curation_command_contracts.py backend/app/agents/curation_command.py backend/app/review/curation_context.py backend/app/review/curation_commands.py backend/app/application/graph_factory.py backend/app/application/workspace_runtime.py backend/tests/test_curation_command_agent.py backend/tests/test_curation_command_middleware.py backend/tests/test_curation_context.py backend/tests/test_curation_commands.py
git add -u backend/app/agents/curation_intent.py backend/tests/test_curation_intent_agent.py backend/tests/test_curation_intent_middleware.py
git commit -m "refactor(review): interpret curation commands safely"
```

---

### Task 4: Integrate compaction, restart recovery, and final evidence

**Files:**
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/tests/test_curation_session_api.py`
- Modify: `backend/tests/test_review_api_restart.py`
- Modify: `backend/tests/test_runtime_migrations.py`
- Modify: `task_plan.md`, `findings.md`, `progress.md`
- Modify local-only: `docs/verification/r2-complete-review-agent.md`

**Interfaces:**
- Existing idempotency lookup returns before classification, compaction, or focus mutation.
- Successful results update focus with CAS; failure and ordinary clarification do not invent focus.
- Structured summary success advances summary/cursor and marks compaction; failure records `curation_context_summary_failed` and retains the old cursor.
- Actual classifier prompt drives context usage; deterministic commands fabricate no model usage.

- [ ] **Step 1: Add RED API and restart tests**

Cover six behaviors with recording fakes:

1. `发布第 1 题` invokes neither classifier nor summarizer.
2. Inspect candidate 1, append more than eight unrelated messages, then `这题发布吧`; only candidate 1 is targeted.
3. Two focused IDs plus `这题发布吧` yields clarification and no status change.
4. A tiny test budget forces overflow; valid summary advances cursor and `contextCompacted`.
5. Summary failure records warning, leaves cursor unchanged, and classifier still receives selected recent turns.
6. Reusing an idempotency key leaves model call counts and context version unchanged.

Restart test: inspect candidate 1, close and recreate runtime against the same workspace, then `这题发布吧`; candidate 1 is recovered from persisted context/structured timeline without parsing free text.

- [ ] **Step 2: Verify integration RED**

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_runtime_migrations.py
```

Expected: FAIL on durable-focus, compaction, restart, and zero-call assertions.

- [ ] **Step 3: Replace the eight-message application path**

In `execute_curation_command`, call `find_curation_command_receipt` and return an existing receipt before interpretation; load/create/recover context; run deterministic parsing first; unresolved language uses adapter, assembler, optional structured summarization, then classifier. Resolve the plan against frozen summary version/current resources and execute existing domain branches. After a successful receipt, CAS-update focus and result IDs from actual results. Remove `visible_messages[-8:]` and `resolve_curation_intent`. Summary failure emits a warning without cursor advancement; hard budget failure returns stable `context_budget_exceeded`. Do not expose summary text or checkpoint state.

- [ ] **Step 4: Verify integration GREEN and targeted regression**

Run Step 2, then:

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q tests/test_context_assembly.py tests/test_agent_factory.py tests/test_agent_middleware_stack.py tests/test_curation_commands.py tests/test_curation_context.py tests/test_curation_command_agent.py tests/test_curation_command_middleware.py tests/test_curation_session_api.py tests/test_review_api_restart.py tests/test_runtime_migrations.py tests/test_review_repository.py
```

Expected: all selected tests PASS without new warnings.

- [ ] **Step 5: Commit integrated implementation**

```bash
git add backend task_plan.md findings.md progress.md
git commit -m "feat(review): assemble durable curation context"
```

- [ ] **Step 6: Run final verification once**

```bash
cd backend
/Users/miracle778/Project/cyber-interview-agent-new/backend/.venv/bin/python -m pytest -q
cd ../frontend
./node_modules/.bin/vitest run --reporter=dot
npm run build
```

Expected: zero test failures and build exit 0. Record exact counts and final SHA in `progress.md` and local verification.

- [ ] **Step 7: Run one complete browser acceptance pass**

Verify: inspect one candidate; add more than eight messages; publish via “这题”; restart and repeat a pronoun command; establish multi-focus and see clarification without publication; confirm current/threshold tokens and compacted state come from backend; confirm no Langfuse service is required. Update local `docs/verification/r2-complete-review-agent.md` with actual evidence and rerun only failed scenarios after fixes.

- [ ] **Step 8: Refresh stage state**

Mark Task 11 complete only after browser evidence exists. Update `findings.md` and `progress.md`. Do not close R2 while earlier stage 8-10 browser scenarios or learning/verification synchronization remain pending.
