# Review Checklist and Bulk Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make review questions advance only after required knowledge points are covered or explicitly skipped, expose the frozen question throughout the conversation, add safe bulk confirmation, show recoverable publication progress, and eliminate IME Enter regressions across R2 Agent inputs.

**Architecture:** Keep review progress as durable domain state, not generic Agent Todo state. `KeyPointCoverageReducer` merges validated model decisions into per-attempt coverage, while `ReviewCompletionPolicy` is the only path that can advance a round. Reuse the existing persistent bulk-publication operation and item tables; add progress projection and recovery instead of creating another job system.

**Tech Stack:** FastAPI, Pydantic, SQLite additive migrations, LangGraph, LangChain structured output, React 19, TypeScript, TanStack Query, Vitest/Testing Library.

## Global Constraints

- Existing `key_points` data must remain readable; new rounds freeze required and bonus point classifications.
- Auxiliary review turns never resolve the pending answer request or advance the round.
- Models return structured decisions; only deterministic domain code changes coverage, result kind, or current index.
- Bulk operations submit explicit candidate IDs and remain idempotent.
- No model chain-of-thought, internal event names, or raw database fields appear in user copy.
- R2 inputs reuse the R3/R4 IME guard; ordinary Enter sends and Shift+Enter inserts a newline.
- Use existing visual tokens and Lucide icons; do not apply the palette suggested by the generic UI search.
- Run only affected tests per task; defer one integrated regression to Task 7.

---

### Task 1: Shared IME-safe keyboard guard

**Files:**
- Create: `frontend/src/shared/agent/useAgentComposerKeyboard.ts`
- Create: `frontend/src/shared/agent/useAgentComposerKeyboard.test.tsx`
- Modify: `frontend/src/shared/agent/AgentComposer.tsx`
- Modify: `frontend/src/features/review/CurationConversation.tsx`
- Modify: `frontend/src/features/review/ReviewConversation.tsx`
- Modify: `frontend/src/features/review/ReviewDiscussion.tsx`
- Test: `frontend/src/shared/agent/AgentComposer.test.tsx`
- Test: `frontend/src/features/review/CurationConversation.test.tsx`
- Test: `frontend/src/features/review/ReviewConversation.test.tsx`

**Interfaces:**
- Produces: `useAgentComposerKeyboard(onSend: () => void)` returning `onCompositionStart`, `onCompositionEnd`, and `onKeyDown`.
- Guarantees: composition state, the composition-ending event-loop turn, `nativeEvent.isComposing`, and `keyCode === 229` all suppress sending.

- [x] **Step 1: Add failing shared keyboard tests**

Cover ordinary Enter, Shift+Enter, active composition, `compositionend` followed by Enter in the same tick, and keyCode 229.

- [x] **Step 2: Run the shared test and verify RED**

Run: `npm test -- --run src/shared/agent/useAgentComposerKeyboard.test.tsx`

Expected: FAIL because the hook does not exist.

- [x] **Step 3: Implement the hook and migrate `AgentComposer`**

Move the existing refs/timer guard out of `AgentComposer` without changing visible behavior.

- [x] **Step 4: Migrate all three R2 inputs**

Replace page-local `onKeyDown` checks in curation, review answer, and discussion inputs with the shared hook.

- [x] **Step 5: Run only affected input tests**

Run: `npm test -- --run src/shared/agent/AgentComposer.test.tsx src/shared/agent/useAgentComposerKeyboard.test.tsx src/features/review/CurationConversation.test.tsx src/features/review/ReviewConversation.test.tsx src/features/review/ReviewDiscussion.test.tsx`

Expected: PASS.

---

### Task 2: Required/bonus points and durable coverage model

**Files:**
- Create: `backend/app/db/migrations/runtime/031_review_key_point_coverage.sql`
- Create: `backend/app/review/coverage.py`
- Create: `backend/tests/test_review_coverage.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/agents/question_curation_contracts.py`
- Modify: `backend/app/agents/question_curation_normalization.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/QuestionDetailPanel.tsx`

**Interfaces:**
- Produces: `KeyPointCoverage` records with `point`, `status`, and optional `evidence`.
- Produces: `merge_key_point_coverage(required_points, previous, decision)`.
- Produces: `ReviewCompletionPolicy.can_advance(coverage, skipped)`.
- Compatibility: `QuestionSnapshot.required_key_points` falls back to legacy `key_points`; `bonus_key_points` defaults to empty.

- [x] **Step 1: Write failing reducer and policy tests**

Use literal fixtures to prove partial coverage does not advance, cumulative coverage does, bonus points do not block, unknown model points are rejected, and skip advances.

- [x] **Step 2: Run the coverage test and verify RED**

Run: `../.venv/bin/python -m pytest backend/tests/test_review_coverage.py -q`

Expected: FAIL because `coverage.py` and new snapshot fields do not exist.

- [x] **Step 3: Implement pure coverage types, reducer, and policy**

Keep this module free of database and Agent dependencies.

- [x] **Step 4: Add additive persistence**

Migration 031 adds `coverage_json`, `result_kind`, `hint_level`, and `answer_revisions_json` to `review_attempts`. Repository readers use safe defaults for historical rows.

- [x] **Step 5: Extend question contracts compatibly**

New generated candidates accept `required_key_points` and `bonus_key_points`; legacy `key_points` is normalized into required points. API resources continue returning `keyPoints` and also expose the two explicit lists.

- [x] **Step 6: Add editable required/bonus sections**

The candidate editor shows separate Markdown sections. Existing documents with only “关键点” load those entries as required.

- [x] **Step 7: Run targeted model/repository/schema tests**

Run the new coverage test plus `backend/tests/test_review_repository.py`, `backend/tests/test_review_schema.py`, and the focused question-detail frontend test.

---

### Task 3: Review turn intent and repeated-answer state machine

**Files:**
- Create: `backend/app/review/turn_intent.py`
- Create: `backend/tests/test_review_turn_intent.py`
- Modify: `backend/app/agents/review_round_contracts.py`
- Modify: `backend/app/agents/prompts/review_round_prompts.py`
- Modify: `backend/app/agents/review_round_agents.py`
- Modify: `backend/app/graphs/review_round.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/schemas/review.py`
- Test: `backend/tests/test_review_round_graph.py`
- Test: `backend/tests/test_review_async_answer.py`
- Test: `backend/tests/test_review_routes.py`

**Interfaces:**
- Produces: `ReviewTurnIntent = answer | show_question | request_hint | reveal_answer | explain | skip | unrelated`.
- Produces: structured evaluation fields `covered_key_points`, `partial_key_points`, `missing_key_points`, and evidence by point.
- Auxiliary turns append user/assistant messages but leave the current input request pending.
- Formal answers create or append an answer revision and resume the same round checkpoint.

- [x] **Step 1: Write failing deterministic intent tests**

Cover “查看原题”, “再说一遍”, “给点提示”, “查看答案”, explicit skip, obvious questions, mixed answer/question, and ordinary answers. Ambiguous input defaults to `answer` only after the structured classifier confirms it.

- [x] **Step 2: Run intent tests and verify RED**

Run: `../.venv/bin/python -m pytest backend/tests/test_review_turn_intent.py -q`

- [x] **Step 3: Extend structured evaluation**

The evaluator returns coverage decisions only for frozen required/bonus points. Validation rejects invented points and contradictory statuses.

- [x] **Step 4: Replace the single-follow-up branch**

After each formal answer, merge coverage and request another answer while required points remain. Advance only through `ReviewCompletionPolicy`; remove the one-follow-up implicit completion behavior.

- [x] **Step 5: Add auxiliary turn handling**

High-confidence commands use deterministic handling. Explanations and ambiguous turns use a bounded responder/classifier, persist a visible assistant reply, then re-present the current question without resolving the answer request.

- [x] **Step 6: Preserve retry semantics**

Failed/stopped evaluation keeps the answer revision and coverage. “重新评价” reuses it; “编辑后重试” appends a revision. Partial assistant output never becomes a formal message.

- [x] **Step 7: Run focused graph/API tests**

Cover partial → supplement → pass, show-question twice without progress, hint-assisted pass, answer reveal, skip, failed evaluation retry, refresh reconstruction, and idempotent repeated input.

---

### Task 4: Sticky current-question card and mastery result UX

**Files:**
- Create: `frontend/src/features/review/CurrentQuestionCard.tsx`
- Create: `frontend/src/features/review/CurrentQuestionCard.test.tsx`
- Modify: `frontend/src/features/review/ReviewConversation.tsx`
- Modify: `frontend/src/features/review/ReviewRuntimePanel.tsx`
- Modify: `frontend/src/features/review/ReviewResults.tsx`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Consumes: current frozen question, coverage summary, hint level, result kind, and source references from the round resource.
- Produces: visible actions for “查看提示”, “查看答案”, “查看来源”, and “跳过此题”.

- [x] **Step 1: Write failing component tests**

Assert the full frozen prompt remains visible, progress is count-only before first answer, missing directions appear after evaluation, source opens on demand, and mobile expansion has an accessible label.

- [x] **Step 2: Run component tests and verify RED**

Run: `npm test -- --run src/features/review/CurrentQuestionCard.test.tsx`

- [x] **Step 3: Implement content-first sticky card**

Place it above the internally scrolling message log. Preserve the right rail for runtime facts. Use existing semantic colors, a 65–75 character reading measure, and no decorative motion.

- [x] **Step 4: Update result labels**

Render 独立掌握、提示后掌握、查看答案、已跳过 in history and reports; do not equate revealed/skipped with mastery.

- [x] **Step 5: Run affected review frontend tests**

Run current-question, conversation, runtime panel, results, and review-page tests only.

---

### Task 5: Safe quick selection and bulk confirmation

**Files:**
- Create: `backend/app/db/migrations/runtime/032_question_candidate_confirmation.sql`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `frontend/src/features/review/QuestionLibrary.tsx`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/app/global.css`
- Test: `backend/tests/test_curation_session_api.py`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`

**Interfaces:**
- Produces: candidate confirmation state independent from publication state.
- Produces: bulk-confirm preflight and commit using explicit candidate IDs and per-item receipts.
- Recommendation eligibility requires review-pending, complete content, valid source, no duplicate conflict, and no active mutation.

- [x] **Step 1: Write focused persistence and contract tests**

Cover explicit-ID scope, already-confirmed idempotency, confirmation receipts, and partial results.

- [x] **Step 2: Run focused backend tests**

Run only the new bulk-confirm test nodes.

- [x] **Step 3: Add confirmation persistence and service**

Migration 032 stores confirmation status/version/time. Do not create publication actions during confirmation.

- [x] **Step 4: Add focused selection UI coverage**

Cover select all currently loaded filtered results, select recommended, clear selection on filter change, and batch result feedback.

- [x] **Step 5: Implement the selection bar**

Use a visible checkbox, exact count, secondary “选择推荐项”, primary “批量确认”, and danger-only delete. Keep row selection hit targets at least 44px.

- [x] **Step 6: Run affected question-library tests**

Run only QuestionCatalog/QuestionLibrary tests and TypeScript.

---

### Task 6: Recoverable bulk-publication progress

**Files:**
- Create: `frontend/src/features/review/BulkPublicationProgress.tsx`
- Create: `frontend/src/features/review/BulkPublicationProgress.test.tsx`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Modify: `frontend/src/features/review/CurationConversation.tsx`
- Modify: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/app/global.css`
- Test: `backend/tests/test_curation_session_api.py`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`

**Interfaces:**
- Produces: latest bulk operation lookup by curation session.
- Projects: total, completed, running, pending, skipped, failed, elapsed time, current candidate, terminal status, and per-item details.
- Reuses: generic execution cancellation and existing retry endpoint.

- [x] **Step 1: Add latest-operation persistence coverage**

Prove latest-operation recovery and reuse the existing cancelled/retry-only-unfinished coverage.

- [x] **Step 2: Add resource projection and latest lookup**

No new publication tables. Derive counts from existing item rows and execution timestamps.

- [x] **Step 3: Add focused progress component tests**

Cover live counts/current item/stop and terminal partial failure/retry. Query recovery is covered through the catalog integration.

- [x] **Step 4: Implement live progress**

Poll the operation resource while accepted/running, also refresh on publication SSE events, and recover latest operation when the curation session opens.

- [x] **Step 5: Run focused bulk-publication tests**

Run existing backend bulk publication tests and focused QuestionCatalog tests.

---

### Task 7: Integration and documentation evidence

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `docs/verification/r2-complete-review-agent.md` (local/ignored)

**Interfaces:**
- Consumes all prior task contracts.
- Produces final focused evidence and browser acceptance notes.

- [x] **Step 1: Run affected backend suites once**

Run coverage, intent, graph, async answer, review routes, repository, curation API, migrations, and schema tests.

- [x] **Step 2: Run affected frontend suites once**

Run shared composer, curation, review conversation/runtime/results/page, current question, bulk progress, and question catalog/library tests.

- [x] **Step 3: Run TypeScript and production build**

Do not run a second full frontend suite unless the first run reveals integration failures.

- [ ] **Step 4: Perform two browser paths**

Path A: Chinese IME → partial answer → auxiliary question → supplement → pass → next question → refresh recovery.

Path B: current-page select → all-filtered select → bulk confirm → one-click publish → progress → stop → refresh → retry failures.

- [x] **Step 5: Update plan and verification evidence**

Record exact tests, operation IDs, widths checked, remaining maturity boundaries, and any real Provider call not exercised.
