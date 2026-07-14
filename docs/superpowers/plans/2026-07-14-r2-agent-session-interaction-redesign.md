# R2 Agent Session Interaction Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Keep one Agent on the slice end-to-end; do not create a worktree or dispatch subagents. Use `ui-ux-pro-max` only at the three UI gates called out below, and stop after the documented artifact/checklist is produced.

**Goal:** Replace R2's batch/list prototype with a usable Agent-session experience: source-scoped question-curation conversations, a separate question library, history-first review rounds, and non-blocking answer evaluation with observable SSE stages.

**Architecture:** Extend the existing generation-2 Runtime and LangGraph execution path instead of adding another chat runtime. Add migration `003` for structured product timeline messages, curation-session projections, question-source evidence links, and durable attempt evaluation states. Keep LangGraph checkpoints as internal execution truth; expose only safe product projections through R2 APIs. Accept answers atomically, return a `202` receipt before model work, then project stage events and validated evaluation cards into the same product session.

**Tech Stack:** Python 3.14, FastAPI, SQLite, Pydantic v2, LangChain/LangGraph, React 19, TypeScript, TanStack Query, native SSE, Vitest, Playwright, `ui-ux-pro-max`.

**Authoritative inputs:**

- Spec: `docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md`
- Visual reference: `docs/superpowers/assets/r2/agent-session-redesign-reference.png`
- Existing implementation plan: `docs/superpowers/plans/2026-07-14-r2-complete-review-agent.md`
- This plan supersedes only the unfinished browser-interaction portion of Task 3/4 in the existing plan.

## Global constraints and budgets

- Stay in `/private/tmp/cyber-interview-agent-r2-ui-design` on `codex/r2-complete-review-agent`; preserve the untracked `frontend/node_modules` symlink.
- Use one Agent for all four tasks. Do not switch agents or create subagents.
- Do not modify `docs/my_idea.md`; do not require Langfuse for any R2 acceptance scenario.
- Product events contain IDs, stage, counts, status and versions only. They never contain source text, answers, reference answers, report bodies, provider errors or secrets.
- Do not expose Chain of Thought. Curation and evaluation show named stages and validated cards; only derived discussion may stream final user-visible text via `assistant.delta`.
- Use targeted tests after each red/green step. Run the final full backend suite, full frontend suite and production build exactly once after all targeted tests pass.
- Run one minimal browser happy path after Task 3 and one complete desktop/mobile/refresh/restart acceptance pass in Task 4. After a fix, rerun only the affected scenario.
- Keep each command output under roughly 4,000 tokens with `-q --tb=short`, file-specific Vitest invocations, `rg`, and `git diff --stat`.

## UI design contract produced by `ui-ux-pro-max`

Run the following once at the start of Task 2; its exit condition is a checked-in implementation note in this plan's Task 2 commit message, not a new permanent design framework:

```bash
python3 /Users/miracle778/.codex/skills/ui-ux-pro-max/scripts/search.py \
  "AI agent session review dashboard knowledge curation" \
  --design-system --project-name "Cyber Interview Agent R2" \
  --format markdown --variance 4 --motion 3 --density 8
python3 /Users/miracle778/.codex/skills/ui-ux-pro-max/scripts/search.py \
  "agent chat progress async feedback keyboard accessibility" --domain ux -n 8
python3 /Users/miracle778/.codex/skills/ui-ux-pro-max/scripts/search.py \
  "data dense dark productivity dashboard" --domain style -n 5
```

Apply these selected results during Tasks 2 and 3:

- Direction: `AI-native + data-dense dashboard + modern dark`; keep the existing deep-neutral/cyan identity and Lucide icons.
- Tokens: reuse semantic CSS variables; use a 4/8 spacing rhythm, 44px minimum interactive targets, 4.5:1 text contrast, and 150–300ms state transitions.
- Hierarchy: one primary CTA per view; the center conversation is dominant, history is left, runtime/progress is right; narrow screens collapse sidebars without horizontal scrolling.
- Feedback: acknowledge an action in under 100ms; show progress when work exceeds 300ms; retain the optimistic user message while evaluation runs.
- Accessibility: visible focus, logical keyboard order, icon labels/tooltips, `aria-live` for stage changes, and `prefers-reduced-motion` support.
- Performance: paginate/virtualize long session and question lists; do not append unbounded SSE event arrays to rendered DOM.
- Rejected results: landing-page composition, purple/pink marketing palettes, heavy glassmorphism and ambient glow.

## Planned file map

### Runtime and review domain

- Create `backend/app/db/migrations/runtime/003_r2_session_experience.sql`.
- Modify `backend/app/application/session_service.py` and `backend/app/schemas/agent.py` for structured, safe timeline messages.
- Modify `backend/app/review/models.py` and `backend/app/review/repository.py` for curation projections, source links, answer receipts and attempt statuses.
- Create `backend/app/review/curation_commands.py` for the constrained command grammar and deterministic target resolution.
- Create `backend/app/review/timeline.py` for user-visible message/card projection only.
- Modify `backend/app/review/application.py`, `backend/app/application/execution_service.py`, curation/review Graphs and R2 schemas/routes.

### Web client

- Modify `frontend/src/features/review/reviewTypes.ts`, `reviewApi.ts`, `reviewSessionApi.ts`, `ReviewShell.tsx`, `QuestionCatalog.tsx`, `ReviewPage.tsx`, `ReviewHistory.tsx`, `ReviewRound.tsx`, and `frontend/src/app/global.css`.
- Create `frontend/src/features/review/CurationSessionList.tsx`, `CurationConversation.tsx`, `CurationRuntimePanel.tsx`, `SourceSelectionDialog.tsx`, `QuestionLibrary.tsx`, `ReviewLanding.tsx`, `ReviewConversation.tsx`, `ReviewRuntimePanel.tsx`, and `SessionMessage.tsx`.
- Add colocated Vitest files for every new stateful component; extend existing API, page, round and SSE-hook tests.

---

## Task 1: Build durable session/timeline and async-answer facts

**Files:**

- Create: `backend/app/db/migrations/runtime/003_r2_session_experience.sql`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Create: `backend/app/review/timeline.py`
- Modify: `backend/app/schemas/review.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_agent_routes_v2.py`
- Create: `backend/tests/test_review_timeline.py`

### Step 1: Write migration and repository failures

Add tests proving migration `003` is additive and preserves existing R2 rows. Require:

```text
agent_messages.message_kind TEXT NOT NULL DEFAULT 'text'
agent_messages.payload_json TEXT NOT NULL DEFAULT '{}'
review_curation_sessions
review_question_source_links
review_attempts.status
review_attempts.evaluation_error_code
review_attempts.evaluation_started_at
review_attempts.evaluation_completed_at
```

`review_curation_sessions` has a unique `session_id`, selected source JSON, active batch, stage, completed/total work units, summary version and timestamps. `review_question_source_links` has unique `(question_id, source_id, evidence_ref)`, batch/session IDs and merge reason. Attempt status is constrained to `evaluating`, `waiting_for_follow_up`, `completed`, or `evaluation_failed`; the existing `skipped` field remains the orthogonal skip fact.

Run:

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short \
  tests/test_runtime_migrations.py tests/test_review_repository.py
```

Expected RED: migration version `003`, curation records, source links and attempt status methods do not exist.

### Step 2: Implement additive migration and typed records

Add frozen records/types:

```python
CurationStage = Literal[
    "queued", "reading_sources", "generating",
    "merging", "summarizing", "waiting_for_command",
    "publishing", "completed", "failed",
]
AttemptStatus = Literal[
    "evaluating", "waiting_for_follow_up", "completed",
    "evaluation_failed",
]
MessageKind = Literal[
    "text", "stage", "curation_summary", "question_card",
    "review_prompt", "review_answer", "evaluation_card",
    "command_receipt", "error",
]
```

Implement repository methods `create_curation_session`, `update_curation_progress`, `get/list_curation_sessions`, `replace_curation_summary`, `upsert_question_source_link`, `list_question_source_links`, `accept_review_answer`, `complete_attempt_evaluation`, and `fail_attempt_evaluation`.

`accept_review_answer(...) -> ReviewAnswerReceipt` must use one SQLite transaction to:

1. verify request version and idempotency;
2. resolve the input request;
3. insert/update the attempt with `evaluating` status and answer/follow-up answer;
4. append a `review_answer` product timeline message with safe payload IDs;
5. transition the existing execution from `waiting_for_input/interrupted` to `running`;
6. return the same receipt for the same key/value and conflict for the same key/different value.

Do not start model work inside this transaction.

### Step 3: Project safe structured timeline resources

Extend `MessageRecord`/`MessageResource` with `message_kind` and parsed `payload`. Add `SessionTimelineProjector` helpers that append a user-visible message and then emit `session.message.created` containing only `messageId`, `messageKind`, `resourceId`, and `version`.

Test that:

- session detail returns ordered structured messages after restart;
- payloads reject unsupported message kinds and non-object JSON;
- source text, user answer and reference answer are stored only in permitted domain/content fields, not event payloads;
- a stage or card message can be rebuilt from stable resource IDs.

Run:

```bash
.venv/bin/python -m pytest -q --tb=short \
  tests/test_runtime_migrations.py tests/test_review_repository.py \
  tests/test_review_timeline.py tests/test_agent_routes_v2.py
```

Expected GREEN: all targeted tests pass.

### Step 4: Commit the durable foundation

```bash
git diff --check
git add backend/app/db/migrations/runtime/003_r2_session_experience.sql \
  backend/app/application/session_service.py backend/app/schemas/agent.py \
  backend/app/review/models.py backend/app/review/repository.py \
  backend/app/review/timeline.py backend/app/schemas/review.py \
  backend/tests/test_runtime_migrations.py backend/tests/test_review_repository.py \
  backend/tests/test_review_timeline.py backend/tests/test_agent_routes_v2.py
git commit -m "feat(review): add durable session timeline facts"
```

---

## Task 2: Deliver source-scoped question-curation conversations

**Files:**

- Create: `backend/app/review/curation_commands.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/agents/question_curation.py`
- Modify: `backend/app/agents/question_curation_contracts.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/schemas/review.py`
- Test: `backend/tests/test_review_service.py`
- Test: `backend/tests/test_review_api_v2.py`
- Test: `backend/tests/test_review_api_restart.py`
- Create: `backend/tests/test_curation_commands.py`
- Create: `backend/tests/test_curation_session_api.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Create: `frontend/src/features/review/CurationSessionList.tsx`
- Create: `frontend/src/features/review/CurationConversation.tsx`
- Create: `frontend/src/features/review/CurationRuntimePanel.tsx`
- Create: `frontend/src/features/review/SourceSelectionDialog.tsx`
- Create: `frontend/src/features/review/QuestionLibrary.tsx`
- Create: `frontend/src/features/review/SessionMessage.tsx`
- Modify: `frontend/src/app/global.css`
- Test: corresponding `*.test.tsx` and `reviewApi.test.ts`

### Step 1: Run the implementation-time UI design gate

Run the three `ui-ux-pro-max` commands in the UI design contract. Compare the output to the committed spec and reference image. Exit when the selected direction, tokens, responsive behavior and rejected anti-patterns are unchanged or explicitly reconciled in the Task 2 commit body.

### Step 2: Write failing curation command/session tests

Define API contracts:

```text
POST /api/review/curation-sessions -> 202 CurationSessionResource
GET  /api/review/curation-sessions?workspaceId=...&page=...
GET  /api/review/curation-sessions/{sessionId}
POST /api/review/curation-sessions/{sessionId}/commands -> 202 CurationCommandReceipt
```

Creation takes one or more selected `sourceRefs`. Previously used or in-progress sources produce warnings but never a `409`. A session detail contains source summaries, stage/progress, timeline, latest structured summary, runtime facts and candidate counts; batches remain internal versions.

Test the constrained command grammar with explicit fixtures:

- `确认所有推荐题` resolves to the current summary version's recommended candidate IDs;
- `确认 1、3、5` and `拒绝 2` resolve numbered targets against that same summary version;
- `重写第 4 题：补充边界条件` and `重新总结` produce bounded commands;
- ambiguous text such as `看着办` returns a clarification message and creates no publication action;
- stale summary versions and repeated idempotency keys are safe;
- batch publication may partially succeed and records per-candidate receipts.

Run:

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short \
  tests/test_curation_commands.py tests/test_curation_session_api.py
```

Expected RED: the new session resources, grammar and routes do not exist.

### Step 3: Implement curation progress, merging and summary

On `create_curation_session`:

1. create one `question.curate` product session for the selected source set;
2. persist `review_curation_sessions` before scheduling Graph work;
3. reuse the existing question-generation Agent and batch repository;
4. publish stage/progress events at reading, extraction, merge and summary boundaries;
5. merge against active catalog and same-session candidates, retaining all source/evidence links and a safe merge reason;
6. write one structured curation summary with stable ordinals, concise question summaries, recommendation and reason;
7. finish in `waiting_for_command`, not `completed`.

Commands operate on stable IDs resolved from the persisted summary version. An explicit, unambiguous confirmation message is the HITL decision and calls the existing publication action/receipt path without an extra confirmation click. Update the summary and timeline after every command result.

Keep the existing batch/candidate endpoints temporarily for internal compatibility, but route the new UI only through curation-session resources and the question library.

Run:

```bash
.venv/bin/python -m pytest -q --tb=short \
  tests/test_curation_commands.py tests/test_curation_session_api.py \
  tests/test_review_service.py tests/test_review_api_v2.py \
  tests/test_review_api_restart.py
```

Expected GREEN: curation survives restart, reports honest progress, retains source links, and commands are deterministic/idempotent.

### Step 4: Build the two-view curation workbench with TDD

First write component/API tests for:

- default `整理会话` view with left session list, center conversation/composer and right runtime panel;
- `AI 整理` opens a source-selection dialog, warns for reused/in-progress files, and still permits submit;
- selecting a session restores its messages and current progress;
- command submission immediately renders the user message and then reconciles the server receipt;
- `题目库` is a separate paginated/filterable view with source links and rendered Markdown reading state;
- HITL UI appears only when the selected session/resource actually needs a decision;
- 375/768/1024/1440 layouts preserve center-task priority and keyboard order.

Implement shared `SessionMessage` rendering for stage, summary, question and receipt cards. Use `aria-live="polite"` for stage updates and do not render the full raw SSE history.

Run:

```bash
cd frontend
npm test -- --run \
  src/features/review/reviewApi.test.ts \
  src/features/review/QuestionCatalog.test.tsx \
  src/features/review/CurationSessionList.test.tsx \
  src/features/review/CurationConversation.test.tsx \
  src/features/review/QuestionLibrary.test.tsx
npx tsc --noEmit
```

Expected GREEN: targeted UI tests and TypeScript pass.

### Step 5: Commit the curation vertical slice

```bash
git diff --check
git add backend/app/review backend/app/graphs/question_curation.py \
  backend/app/agents/question_curation.py \
  backend/app/agents/question_curation_contracts.py \
  backend/app/api/routes_review.py backend/app/schemas/review.py \
  backend/tests/test_curation_commands.py backend/tests/test_curation_session_api.py \
  backend/tests/test_review_service.py backend/tests/test_review_api_v2.py \
  backend/tests/test_review_api_restart.py \
  frontend/src/features/review frontend/src/app/global.css
git commit -m "feat(review): add agent-style curation sessions"
```

---

## Task 3: Make review history-first and answer evaluation asynchronous

**Files:**

- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/graphs/review_round.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/schemas/review.py`
- Test: `backend/tests/test_review_input_resume.py`
- Test: `backend/tests/test_review_round_graph.py`
- Test: `backend/tests/test_review_routes.py`
- Test: `backend/tests/test_review_api_restart.py`
- Create: `backend/tests/test_review_async_answer.py`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Modify: `frontend/src/features/agent/useAgentEvents.test.tsx`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/review/ReviewHistory.tsx`
- Modify: `frontend/src/features/review/ReviewRound.tsx`
- Create: `frontend/src/features/review/ReviewLanding.tsx`
- Create: `frontend/src/features/review/ReviewConversation.tsx`
- Create: `frontend/src/features/review/ReviewRuntimePanel.tsx`
- Modify: `frontend/src/app/global.css`
- Test: relevant review/API/SSE `*.test.ts(x)` files

### Step 1: Write the asynchronous protocol tests

Change the answer contract to:

```text
POST /api/review/rounds/{roundId}/answers -> 202 ReviewAnswerReceiptResource
POST /api/review/rounds/{roundId}/retry-evaluation -> 202 ReviewAnswerReceiptResource
```

The receipt contains `receiptId`, `roundId`, `attemptId`, `inputRequestId`, `status: evaluating`, `acceptedAt`, and current resource version. It does not contain an evaluation or wait for model output.

Test:

- HTTP returns while a controlled evaluator future is still blocked;
- accepted answer and user timeline message are queryable immediately;
- duplicate key/value returns the same receipt; duplicate key/different value conflicts;
- process interruption after acceptance but before spawn resumes the original checkpoint/attempt on restart;
- successful evaluation transitions `evaluating -> waiting_for_follow_up|completed` and emits safe ordered stage events;
- provider/validation failure transitions to `evaluation_failed`, preserves the answer, and retry uses the same answer/current index;
- no answer/reference-answer text appears in SSE payloads.

Run:

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short \
  tests/test_review_async_answer.py tests/test_review_input_resume.py \
  tests/test_review_round_graph.py tests/test_review_routes.py
```

Expected RED: the route waits for `executions.wait()` and returns the whole round.

### Step 2: Split acceptance from Graph completion

Refactor `AgentExecutionService.resume_input` into two explicit phases:

- acceptance/transition is performed by the durable repository transaction from Task 1;
- `resume_accepted_input(execution_id, receipt)` publishes `review.answer.accepted` and `review.evaluation.started`, then spawns `Command(resume=...)` without waiting.

`ReviewApplication.submit_answer` returns the durable receipt immediately after scheduling. Remove `await executions.wait()` from the answer route. The Graph updates the existing attempt rather than inserting a second record, and the timeline projector writes a validated evaluation card only after structured output validation succeeds.

Startup reconciliation scans `evaluating` attempts whose execution is `interrupted/running` and resumes the original execution/checkpoint. It must not create a new round, execution or duplicate user message.

Implement `retry_evaluation` only for the current `evaluation_failed` attempt, with its own idempotency receipt.

Run:

```bash
.venv/bin/python -m pytest -q --tb=short \
  tests/test_review_async_answer.py tests/test_review_input_resume.py \
  tests/test_review_round_graph.py tests/test_review_routes.py \
  tests/test_review_api_restart.py
```

Expected GREEN: all protocol, recovery and event-safety tests pass.

### Step 3: Write failing history/chat UI tests

Require:

- `/review` defaults to review history and does not auto-enter the newest round;
- active rounds are pinned but multiple unfinished rounds remain independently selectable;
- `创建复习` is a distinct button/panel and closing it returns to history;
- entering a round renders an ordered chat timeline, not a blocking single form;
- submit appends the user bubble immediately, clears/enables the composer after receipt, and displays evaluation stages through SSE;
- another round can be opened while evaluation continues;
- the final validated evaluation card replaces stage-only feedback;
- `evaluation_failed` offers retry without losing the answer;
- no simulated token-by-token Chain of Thought is rendered.

Run:

```bash
cd frontend
npm test -- --run \
  src/features/agent/useAgentEvents.test.tsx \
  src/features/review/reviewApi.test.ts \
  src/features/review/ReviewPage.test.tsx \
  src/features/review/ReviewRound.test.tsx \
  src/features/review/ReviewLanding.test.tsx \
  src/features/review/ReviewConversation.test.tsx
```

Expected RED: the page auto-selects a round and the answer mutation remains pending until evaluation ends.

### Step 4: Implement the history-first asynchronous chat

Use server resources for all durable state. TanStack Query owns cache/revalidation; component state owns only draft text, selected tab and dialog visibility.

Extend `useAgentEvents` with the new curation/review event names, bound the retained event window, and invalidate the selected session/round on `session.message.created` or terminal stage events. Do not store full message bodies in SSE state.

On answer submit:

1. add an optimistic user message keyed by idempotency key;
2. receive `202` and reconcile it to the persisted message/attempt;
3. keep navigation and composer responsive;
4. show named stages in the conversation and right runtime panel;
5. replace stages with the server-projected evaluation card after invalidation.

Run:

```bash
npm test -- --run \
  src/features/agent/useAgentEvents.test.tsx \
  src/features/review/reviewApi.test.ts \
  src/features/review/ReviewPage.test.tsx \
  src/features/review/ReviewRound.test.tsx \
  src/features/review/ReviewLanding.test.tsx \
  src/features/review/ReviewConversation.test.tsx
npx tsc --noEmit
```

Expected GREEN: targeted frontend tests and types pass.

### Step 5: Run the one minimal browser happy path

With Langfuse variables unset, start the existing backend/frontend dev commands. In the real browser:

1. open review history;
2. create a two-question round;
3. submit one answer;
4. verify the user bubble appears immediately and navigation remains usable;
5. verify SSE stages and one final evaluation card;
6. refresh and verify the same session/timeline restores.

Record only IDs, visible statuses, timings and screenshots in `docs/verification/r2-complete-review-agent.md`; do not claim full browser acceptance yet.

### Step 6: Commit the review vertical slice

```bash
git diff --check
git add backend/app/application/execution_service.py backend/app/review \
  backend/app/graphs/review_round.py backend/app/api/routes_review.py \
  backend/app/schemas/review.py backend/tests/test_review_async_answer.py \
  backend/tests/test_review_input_resume.py backend/tests/test_review_round_graph.py \
  backend/tests/test_review_routes.py backend/tests/test_review_api_restart.py \
  frontend/src/features/agent/useAgentEvents.ts \
  frontend/src/features/agent/useAgentEvents.test.tsx \
  frontend/src/features/review frontend/src/app/global.css
git commit -m "feat(review): make review sessions asynchronous"
```

---

## Task 4: UI/UX audit, final verification and documentation closure

**Files:**

- Modify as findings require: `frontend/src/features/review/**`, `frontend/src/app/global.css`
- Modify local: `docs/verification/r2-complete-review-agent.md`
- Regenerate local: `docs/learning/r2-complete-review-agent/**`
- Modify: `task_plan.md`, `findings.md`, `progress.md`
- Test: affected backend/frontend files plus final suites

### Step 1: Run the final `ui-ux-pro-max` audit once

Re-run focused searches for `accessibility`, `loading feedback`, `navigation`, `responsive dashboard`, and `react performance`. Audit the real page at 375, 768, 1024 and 1440 widths. Capture a concise evidence table in `docs/verification/r2-complete-review-agent.md` with:

- accessibility: keyboard order, visible focus, labels, 44px targets, contrast;
- loading: immediate acknowledgement, honest progress, retry and empty/error states;
- navigation: selected session/round, back-to-history, creation panel and no surprise auto-entry;
- responsive: no horizontal scrolling and center-task priority;
- performance: bounded event rendering, paginated long lists and no avoidable whole-page rerenders.

Fix each actionable finding, rerun only its component test, and stop the skill after the five categories have evidence.

### Step 2: Run targeted integration and restart tests

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short \
  tests/test_curation_session_api.py tests/test_review_async_answer.py \
  tests/test_review_api_restart.py tests/test_review_routes.py
cd ../frontend
npm test -- --run src/features/review src/features/agent/useAgentEvents.test.tsx
npx tsc --noEmit
```

Expected: all targeted integration tests pass before any full regression.

### Step 3: Run the single final full regression and build

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short
cd ../frontend
npm test -- --run
npm run build
```

Record the exact fresh counts and build warning status. Do not rerun full suites unless the full run itself exposes a cross-cutting regression; otherwise rerun only the failed file.

### Step 4: Run one complete browser/restart acceptance pass

With Langfuse unconfigured:

1. create a curation session from multiple selected files, including one previously used file; verify warning-but-allowed behavior;
2. observe reading/extraction/merge/summary stages and restore them after refresh;
3. verify source links and similarity merge evidence in the separate question library;
4. issue explicit confirm/reject/rewrite commands and verify receipts/publication states without a second confirmation click;
5. verify ambiguous commands ask for clarification and publish nothing;
6. verify review opens on history, supports multiple unfinished rounds and uses the explicit create button;
7. submit an answer and verify immediate bubble, non-blocking navigation, stage SSE and final card;
8. restart after answer acceptance but before evaluation completion; verify the original round/checkpoint resumes without duplicate attempts/messages;
9. exercise evaluation failure/retry with a controlled failure adapter;
10. verify desktop and 375px layouts, keyboard navigation, reduced motion, Markdown reading/editing boundary, and conditional HITL visibility.

Update `docs/verification/r2-complete-review-agent.md` with truthful evidence. Browser acceptance remains failed if any required scenario was not actually run.

### Step 5: Refresh final user/learning documents and run the gate

Reshape `docs/verification/r2-complete-review-agent.md` into the final user guide only after browser acceptance passes. Regenerate the R2 foundation-profile seven-file learning pack once, compare its depth with R1.2/R1.3, and record ownership status separately from product completion.

Run:

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r2-complete-review-agent.md \
  --learning docs/learning/r2-complete-review-agent/ \
  --plan docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md
git diff --check
rg -n "TB""D|TO""DO|FIX""ME|浏览器验收通过" \
  docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md \
  docs/verification/r2-complete-review-agent.md \
  docs/learning/r2-complete-review-agent
```

Expected: documentation gate passes; placeholder scan has no unresolved placeholder and every browser claim has matching evidence.

### Step 6: Commit the accepted product changes

Only formal files under `docs/superpowers/` are committed. `docs/verification/` and `docs/learning/` remain local and must later be explicitly synchronized into the main worktree after merge.

```bash
git add frontend/src backend/app backend/tests task_plan.md findings.md progress.md \
  docs/superpowers/specs/2026-07-13-r2-complete-review-agent-design.md \
  docs/superpowers/plans/2026-07-14-r2-agent-session-interaction-redesign.md
git commit -m "feat(review): complete R2 agent session experience"
```

## Final completion report

Report these separately:

1. **Product status and evidence:** exact backend/frontend/build counts, browser scenarios and restart result.
2. **Product maturity boundary:** Web R2 complete; external WeChat/Feishu channels remain R8; Langfuse normal-path acceptance remains the observability follow-up.
3. **Ownership status:** learned, pending learning and pending practice from the refreshed learning pack.
4. **Next product task:** the next roadmap item after accepted R2, not a learning exercise.
5. **Non-blocking user exercise:** one small ownership exercise that does not block merge or the next stage.

## Plan self-review checklist

- [x] Every confirmed spec requirement maps to a task and browser scenario.
- [x] No API returns a full evaluation synchronously from answer submission.
- [x] No event payload or trace contains answer/reference/source/report bodies.
- [x] No product UI exposes Chain of Thought.
- [x] Migration is additive and preserves existing R2/runtime records.
- [x] New Python literals, Pydantic resources and TypeScript unions use the same status names.
- [x] Curation summary ordinals resolve through a persisted summary version, never current array position.
- [x] HITL is visible only for real pending decisions; explicit curation confirmation text is itself the decision receipt.
- [x] UI design gates have concrete commands, artifacts and exit conditions.
- [x] Full regression/build and complete browser acceptance each run once at the prescribed point.
- [x] `docs/verification/r2-complete-review-agent.md` and `docs/learning/r2-complete-review-agent/` are explicitly synchronized after merge even though Git ignores them.
