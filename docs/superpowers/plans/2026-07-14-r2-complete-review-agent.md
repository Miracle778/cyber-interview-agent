# R2 Complete Review Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Keep one Agent on the slice end-to-end; do not dispatch subagents unless the user explicitly requests independent parallel work.

**Goal:** Deliver the complete Web review experience from source-backed question curation through a recoverable multi-question round, follow-up evaluation, per-round reports, confirmed global mastery, and derived discussion sessions.

**Architecture:** Add review-domain records and an additive runtime migration without replacing generation-2 data. Deterministic services own selection, snapshots, progress, idempotency, mastery and publication side effects; role-specific LangChain agents run inside explicit LangGraph nodes, while the existing application/session/execution/HITL infrastructure remains the only runtime boundary. The Web client consumes review resources and existing Agent SSE/action resources; WeChat and Feishu native chat remain R8.

**Tech Stack:** Python 3.14, FastAPI, SQLite/aiosqlite, Pydantic v2, LangChain `create_agent`, LangGraph checkpoint/interrupt, React 19, TypeScript, TanStack Query, Vitest, Playwright.

## Global Constraints

- Preserve `review.single` as a regression and quick-review path; add `question.curate`, `review.round`, and `review.discussion` explicitly.
- Do not add a project Agent loop, model gateway, tool registry, Graph registry, middleware pipeline, or product copy of checkpoint state.
- Use one long-lived execution for a review round. Answer and follow-up pauses use `waiting_for_input`; publication approval continues to use `waiting_for_approval`.
- Question order, snapshot hash, current index, input request version, follow-up limit, attempts and mastery calculation are deterministic domain facts.
- Only published question drafts enter the active catalog. Only confirmed mastery reports affect later selection.
- Keep secrets, reference answers, user answers, source content and report bodies out of product event payloads and OpenTelemetry attributes.
- Use targeted tests during Tasks 1–3. Run the full backend/frontend regression no more than twice: once after cross-layer integration if needed and once before final acceptance.
- Run one minimal browser happy path after Task 3 and one complete browser/restart acceptance pass in Task 4.
- Run R2 acceptance with Langfuse unconfigured and not started. Do not require Langfuse login, trace lookup, normal-export evidence or unreachable-endpoint testing in this stage.
- Responsive Web remains a UI quality gate, not evidence that the R8 WeChat/Feishu Channel requirement is complete.
- Do not modify `docs/my_idea.md`.

---

## Planned File Structure

### Review domain

- `backend/app/review/models.py`: immutable question batch, catalog, round, attempt, input request and mastery records.
- `backend/app/review/repository.py`: SQLite persistence and compare-and-set transitions for R2 domain facts.
- `backend/app/review/selector.py`: deterministic four-mode question selection and frozen snapshots.
- `backend/app/review/service.py`: question curation, round commands, input idempotency, skip/cancel and mastery projection.
- `backend/app/review/errors.py`: stable domain conflicts used by API error handlers.

### Agent and Graph

- `backend/app/agents/question_curation.py`: question generation/rewrite Agent.
- `backend/app/agents/review_round.py`: evaluation, follow-up, report and discussion role Agents.
- `backend/app/agents/r2_contracts.py`: strict structured outputs and compact Graph state.
- `backend/app/graphs/question_curation.py`: source refs to question draft batch.
- `backend/app/graphs/review_round.py`: long-lived answer/follow-up interrupt loop and report draft creation.
- `backend/app/graphs/review_discussion.py`: isolated child discussion session.
- `backend/app/application/review_application.py`: application orchestration over domain services and existing execution/HITL services.

### Product API and Web

- `backend/app/api/routes_review.py`: question batch/catalog/round/answer/skip/cancel/discussion resources.
- `backend/app/schemas/review.py`: public camelCase commands and resources.
- `frontend/src/features/review/reviewApi.ts`: typed R2 API client.
- `frontend/src/features/review/reviewTypes.ts`: R2 resource types.
- `frontend/src/features/review/ReviewShell.tsx`: 一级导航、模块上下文和响应式侧栏/抽屉。
- `frontend/src/features/review/ReviewSetup.tsx`: filters, modes and round creation.
- `frontend/src/features/review/ReviewRound.tsx`: current question, answer/follow-up, progress and runtime cards.
- `frontend/src/features/review/ReviewResults.tsx`: attempts, session/mastery drafts and publication state.
- `frontend/src/features/review/ReviewHistory.tsx`: session/round history and derived discussion entry.
- `frontend/src/features/review/QuestionCatalog.tsx`: 题库摘要、批次进度、筛选和候选题列表工作台。
- `frontend/src/features/review/QuestionDetailPanel.tsx`: 渲染预览、Markdown 编辑、AI 建议、重复对比和按需确认。
- `frontend/src/features/review/ReviewPage.tsx`: state-based composition only; no durable round state in component arrays.

---

### Task 1: Establish question catalog and durable review-round facts

**Files:**
- Create: `backend/app/db/migrations/runtime/002_r2_review.sql`
- Modify: `backend/app/infrastructure/runtime_database.py`
- Create: `backend/app/review/__init__.py`
- Create: `backend/app/review/errors.py`
- Create: `backend/app/review/models.py`
- Create: `backend/app/review/repository.py`
- Create: `backend/app/review/selector.py`
- Create: `backend/app/review/service.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/knowledge/publication_handler.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_review_repository.py`
- Test: `backend/tests/test_review_selector.py`
- Test: `backend/tests/test_review_service.py`

**Interfaces:**
- Produces `ReviewRepository(connection)` with `create_batch`, `save_candidate`, `activate_question`, `create_round`, `get_round`, `create_input_request`, `resolve_input`, `save_attempt`, `advance_round`, `cancel_round`, and mastery compare-and-set methods.
- Produces `QuestionSelector.select(catalog, mastery, settings, seed) -> tuple[QuestionSnapshot, ...]`.
- Produces `ReviewDomainService` for later Graph and API tasks.
- `KnowledgePublishActionHandler` receives an optional `after_publication(draft, publication)` callback so published question/mastery drafts update rebuildable projections after the existing publication transaction succeeds.

- [x] **Step 1: Write additive migration tests**

Add tests proving a fresh database and an existing generation-2 database both receive migration version 2 without backup/replacement:

```python
def test_existing_generation_two_database_applies_r2_migration(tmp_path):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('keep', 'w1', 'review.single', 1, 'keep me')"
    )
    connection.commit()
    connection.close()

    reopened = connect_runtime_database(tmp_path)
    tables = {
        row[0]
        for row in reopened.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert reopened.execute(
        "SELECT title FROM agent_sessions WHERE id = 'keep'"
    ).fetchone()[0] == "keep me"
    assert {
        "review_question_batches",
        "review_question_candidates",
        "review_question_catalog",
        "review_rounds",
        "review_attempts",
        "review_input_requests",
        "review_mastery_projection",
    } <= tables
```

Run:

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short tests/test_runtime_migrations.py
```

Expected: the new test fails because migration history and R2 tables do not exist.

- [x] **Step 2: Add migration history and R2 tables**

Keep `CURRENT_SCHEMA_GENERATION = 2`. Add an internal `runtime_schema_migrations` table after the generation check, register the baseline as version 1, and apply ordered SQL files whose version has not been recorded. Do not classify a database as replaceable when it already has `runtime_schema_metadata`.

The R2 migration must define:

```sql
CREATE TABLE review_question_batches (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    source_refs_json TEXT NOT NULL,
    rewrite_of_batch_id TEXT REFERENCES review_question_batches(id),
    status TEXT NOT NULL CHECK (status IN ('generating', 'review_pending', 'completed', 'failed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE review_question_candidates (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES review_question_batches(id) ON DELETE CASCADE,
    draft_id TEXT UNIQUE REFERENCES knowledge_drafts(id) ON DELETE SET NULL,
    question_json TEXT NOT NULL,
    duplicate_of_question_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'review_pending', 'rejected', 'published')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE review_question_catalog (
    question_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    draft_id TEXT NOT NULL UNIQUE REFERENCES knowledge_drafts(id) ON DELETE RESTRICT,
    publication_id TEXT NOT NULL UNIQUE REFERENCES publication_runs(id) ON DELETE RESTRICT,
    question_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Also define round, attempt, input-request and mastery tables with foreign keys, JSON checks at the service boundary, unique `(round_id, ordinal)`, unique `(round_id, request_id)`, and unique `(input_request_id, idempotency_key)`. Add `waiting_for_input` to the recreated development schema's session/run status checks using a table rebuild inside the migration.

Run the migration test again; expected: PASS and the preserved session remains present.

- [x] **Step 3: Define strict domain records**

In `models.py`, define frozen dataclasses and literals. Required public shapes:

```python
ReviewMode = Literal[
    "weak-point", "random-mixed", "topic-focused", "recent-mistake"
]
RoundStatus = Literal[
    "waiting_for_input", "running", "report_pending",
    "completed", "failed", "cancelled"
]
InputKind = Literal["answer", "follow_up"]

@dataclass(frozen=True, slots=True)
class QuestionSnapshot:
    question_id: str
    document_id: str
    content_hash: str
    title: str
    question_text: str
    reference_answer: str
    topics: tuple[str, ...]
    difficulty: Literal["easy", "medium", "hard"]
    key_points: tuple[str, ...]
    follow_ups: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ReviewRoundSettings:
    topics: tuple[str, ...]
    difficulties: tuple[str, ...]
    mode: ReviewMode
    question_count: int
    allow_follow_up: bool
    seed: int
    answer_model_id: str
    reasoning_effort: Literal["none", "low", "medium", "high"]
```

Reject question counts outside 1–50, empty topic filters for `topic-focused`, missing reference answers, empty model IDs, unsupported reasoning-effort values, and malformed snapshot hashes before persistence. The application layer must additionally verify that the model ID belongs to an enabled model available to the current Workspace.

- [x] **Step 4: Test deterministic selection**

Cover all four modes:

- fixed seed produces the same order;
- weak-point prioritizes confirmed weak/partial mastery;
- recent-mistake uses confirmed attempt/report evidence;
- topic-focused never leaks another topic;
- random-mixed deduplicates IDs;
- insufficient inventory raises `InsufficientQuestionsError(available, requested)`;
- a snapshot remains unchanged after catalog content changes.

Run:

```bash
.venv/bin/python -m pytest -q --tb=short   tests/test_review_selector.py tests/test_review_repository.py
```

Expected before implementation: collection/import failure. Expected after implementation: PASS.

- [x] **Step 5: Implement repository and selector**

Use canonical JSON (`ensure_ascii=False`, sorted keys, compact separators) and explicit `BEGIN IMMEDIATE` around compare-and-set transitions. `resolve_input` must return the existing receipt for the same idempotency key and raise `InputAlreadyResolvedError` for a different key.

The selector must consume only active catalog rows and confirmed mastery projection. Freeze all selected questions into `review_rounds.question_snapshots_json`; later catalog edits never alter an existing round.

- [x] **Step 6: Test publication projection and mastery compare-and-set**

Add tests proving:

- publishing a question candidate activates exactly one catalog row;
- edited approval projects the final draft version/hash;
- rejected drafts never enter the catalog;
- republishing the same receipt is idempotent;
- mastery update requires the expected projection version;
- unconfirmed mastery drafts never affect selection.

- [x] **Step 7: Implement domain service and publication callback**

`ReviewDomainService.create_round` must select and freeze questions, create the `review.round` product session through an injected callback, create one round record, and return the first input request without invoking a model.

Before selection, `create_round` calls `refresh_mastery_from_recent_reports(limit=3)`.
With no confirmed report it keeps an empty `unknown` projection; otherwise it deterministically
merges the latest three confirmed session-report evidence sets and compare-and-set updates the
global projection. The selector must consume that refreshed version and record it as `mastery_before`.

`activate_published_draft` parses the stored structured candidate, verifies draft/publication IDs and hashes, then updates question or mastery projection. It must not parse arbitrary Vault Markdown as authoritative structured state.

- [x] **Step 8: Run Task 1 verification and commit**

```bash
.venv/bin/python -m pytest -q --tb=short   tests/test_runtime_migrations.py   tests/test_review_repository.py   tests/test_review_selector.py   tests/test_review_service.py   tests/test_publication_service.py
git diff --check
git add backend/app backend/tests
git commit -m "feat(review): add durable question and round domain"
```

Expected: targeted tests pass; no existing Runtime row is lost.

---

### Task 2: Build question curation and long-lived review Graphs

**Files:**
- Create: `backend/app/agents/r2_contracts.py`
- Create: `backend/app/agents/question_curation.py`
- Create: `backend/app/agents/review_round.py`
- Create: `backend/app/graphs/question_curation.py`
- Create: `backend/app/graphs/review_round.py`
- Create: `backend/app/graphs/review_discussion.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/application/event_projector.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/middleware/defaults.py`
- Modify: `backend/app/agents/factory.py`
- Modify: `backend/app/agents/model_resolver.py`
- Test: `backend/tests/test_question_curation_graph.py`
- Test: `backend/tests/test_review_round_graph.py`
- Test: `backend/tests/test_review_input_resume.py`
- Test: `backend/tests/test_review_discussion_graph.py`
- Test: `backend/tests/test_review_round_middleware.py`

**Interfaces:**
- Produces `QuestionCandidateBatch`, `AnswerEvaluationV2`, `FollowUpDecision`, `SessionReportOutput`, and compact `ReviewRoundState`.
- Adds `AgentExecutionService.resume_input(execution_id, *, request_id, value, receipt_id)`.
- Adds explicit factory support for `question.curate`, `review.round`, and `review.discussion`.
- Emits `review.input.required`, `review.input.resolved`, `review.attempt.completed`, `review.progress.changed`, `review.report.draft_created`, and round terminal events.

- [x] **Step 1: Write structured Agent contract tests**

Use Pydantic `extra="forbid"`. The evaluation contract must include score, evidence, missing points, optional follow-up reason and mastery suggestion; it must never expose hidden reasoning.

```python
class AnswerEvaluationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str
    follow_up_required: bool
    follow_up_prompt: str | None
    mastery_suggestion: Literal["weak", "partial", "stable", "strong"]
```

Question candidates must include title, question text, corrected reference answer, topics, difficulty, key points, follow-ups, source refs and a concise correction note.

- [x] **Step 2: Implement role Agents with isolated threads**

Create role-specific agents through the existing `AgentFactory`:

- `question_generation` uses `<session>:question_generation`;
- `answer_evaluation` uses `<session>:answer_evaluation`;
- `report_summarization` uses `<session>:report_summarization`;
- `agent_chat` uses `<discussion_session>:agent_chat`.

Question generation may use only safe source-reader tools. Evaluation has no tools. Report generation reads structured attempts and at most three confirmed reports. Discussion receives the frozen question and selected attempt evidence, never the parent checkpoint/messages.

`AgentFactory` accepts a validated immutable session override for `answer_evaluation` containing `provider_model_id` and `reasoning_effort`. `ModelResolver` resolves the model through the existing Provider repository and maps the normalized effort to Provider-specific constructor/call options; `none` omits the option. Unknown, disabled or unsupported model/effort combinations fail before the round starts. Do not put Provider URL, API key or arbitrary model strings in Graph state.

- [x] **Step 3: Write the multi-interrupt Graph test**

The test must execute one compiled Graph through this sequence:

```text
start
-> input interrupt(answer q1)
-> resume(answer)
-> evaluation requests follow-up
-> input interrupt(follow_up q1)
-> resume(follow_up)
-> persist attempt and advance
-> input interrupt(answer q2)
-> resume(answer)
-> persist attempt
-> generate report/mastery drafts
-> publication approval interrupt
```

Assert one execution ID, stable outer thread ID, increasing input request versions, exactly one attempt per ordinal and isolated role thread IDs.

- [x] **Step 4: Implement the deterministic Graph loop**

`ReviewRoundState` stores only round ID, settings, frozen snapshots, current index, current request, compact current answer/evaluation/follow-up, attempt IDs, report draft IDs and status.

Graph nodes:

```text
load_round
request_answer
evaluate_answer
decide_follow_up
request_follow_up
persist_attempt
advance_round
generate_reports
save_report_drafts
request_publication
finish_round
```

`request_answer` and `request_follow_up` create domain input requests before calling `interrupt({"inputRequestId": ..., "kind": ...})`. The model cannot advance `current_index`, choose question count or decide whether a round is complete.

- [x] **Step 5: Separate input and approval recovery**

Update execution status literals and transition checks:

- interrupt containing `inputRequestId` -> `waiting_for_input`, publish `review.input.required`;
- interrupt containing `actionId` -> `waiting_for_approval`, retain existing action behavior;
- unknown interrupt shape -> fail with stable `unsupported_interrupt`.

`resume_input` validates the unresolved domain request and then resumes the same checkpoint with:

```python
Command(resume={
    "inputRequestId": request_id,
    "value": value,
    "receiptId": receipt_id,
})
```

A duplicate idempotency key returns the previous receipt without calling `graph.astream` again.

- [x] **Step 6: Add round-aware middleware profiles**

Allow `build_default_middleware` to accept an immutable budget profile while retaining current defaults. Add a `review_round` profile with per-call run limits, long-thread limits and a round fingerprint containing round ID, current index and input request ID. Do not add a second pipeline.

Test a ten-question fake-model round that triggers at least one summary, records usage, avoids false no-progress detection across similar questions, and stops at a deterministic hard budget.

- [x] **Step 7: Implement report, mastery and discussion completion**

Generate two drafts at round completion:

- `session_report`: human-readable per-round evidence;
- `mastery_report`: deterministic mastery proposal plus Agent explanation.

Use `round_id + report_kind` as the idempotency identity. Publishing the mastery report invokes Task 1 projection compare-and-set. Derived discussion creates a child `review.discussion` session with `parent_session_id`, snapshot and attempt refs; it cannot update the parent round.

If a round already has a published report and the user requests regeneration, create a new draft
version and a deterministic merge proposal. Non-conflicting sections merge automatically; conflicting
mastery evidence remains in a pending action preview and requires the user's versioned decision.

- [x] **Step 8: Run Task 2 verification and commit**

```bash
.venv/bin/python -m pytest -q --tb=short   tests/test_question_curation_graph.py   tests/test_review_round_graph.py   tests/test_review_input_resume.py   tests/test_review_discussion_graph.py   tests/test_review_round_middleware.py   tests/test_review_agent_graph.py   tests/test_agent_restart_v2.py
git diff --check
git add backend/app backend/tests
git commit -m "feat(review): add complete review agent graphs"
```

Expected: multi-interrupt execution, restart recovery, middleware profile and discussion isolation tests pass.

---

### Task 3: Expose the review API and complete the Web experience

**Files:**
- Create: `backend/app/application/review_application.py`
- Create: `backend/app/api/routes_review.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/application/session_service.py`
- Test: `backend/tests/test_review_api_v2.py`
- Test: `backend/tests/test_review_api_restart.py`
- Create: `frontend/src/features/review/reviewApi.ts`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Create: `frontend/src/features/review/ReviewShell.tsx`
- Create: `frontend/src/features/review/ReviewSetup.tsx`
- Create: `frontend/src/features/review/ReviewRound.tsx`
- Create: `frontend/src/features/review/ReviewResults.tsx`
- Create: `frontend/src/features/review/ReviewHistory.tsx`
- Create: `frontend/src/features/review/QuestionCatalog.tsx`
- Create: `frontend/src/features/review/QuestionDetailPanel.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Test: `frontend/src/features/review/reviewApi.test.ts`
- Test: `frontend/src/features/review/ReviewPage.test.tsx`
- Test: `frontend/src/features/review/ReviewRound.test.tsx`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Test: `frontend/src/features/review/QuestionDetailPanel.test.tsx`
- Test: `tests/e2e/r2-review-happy-path.spec.ts`

**Interfaces:**
- `POST /api/review/question-batches`
- `GET /api/review/question-batches?workspaceId=&status=`
- `GET /api/review/question-batches/{batch_id}`
- `GET /api/review/question-candidates?workspaceId=&query=&topic=&difficulty=&sourceId=&status=&page=`
- `GET /api/review/question-candidates/{candidate_id}`
- `PATCH /api/review/question-candidates/{candidate_id}`
- `POST /api/review/question-candidates/{candidate_id}/rewrite`
- `GET /api/review/questions?workspaceId=&topic=&difficulty=` (published active catalog only)
- `POST /api/review/rounds`
- `GET /api/review/rounds?workspaceId=`
- `GET /api/review/rounds/{round_id}`
- `POST /api/review/rounds/{round_id}/answers`
- `POST /api/review/rounds/{round_id}/skip`
- `POST /api/review/rounds/{round_id}/cancel`
- `POST /api/review/rounds/{round_id}/discussions`

- [x] **Step 1: Write API contract tests**

Define camelCase commands:

```python
class CreateReviewRoundCommand(ReviewModel):
    workspace_id: str
    selected_topics: list[str]
    difficulties: list[Literal["easy", "medium", "hard"]]
    mode: ReviewMode
    question_count: int = Field(ge=1, le=50)
    allow_follow_up: bool = True
    seed: int | None = None
    answer_model_id: str
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"

class SubmitReviewInputCommand(ReviewModel):
    input_request_id: str
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)
    value: str = Field(min_length=1, max_length=20000)
```

Tests must cover batch list/detail and restart-visible progress; candidate search/filter/detail/edit/rewrite; active catalog exclusion of unpublished candidates; round creation with a valid enabled model/effort snapshot; rejection of unknown, disabled or unsupported combinations; list/detail, answer, duplicate answer, conflicting answer, skip, cancel, insufficient questions, missing round, derived discussion and safe error bodies.

- [x] **Step 2: Implement application composition and routes**

Add `ReviewApplication` to each `WorkspaceRuntime` using the same SQLite connection, session service, execution service, draft service, publication callbacks and product event stream.

Route handlers must resolve workspace and round server-side. They must not accept internal session ID, execution ID, checkpoint config, workspace path or scope from answer commands.

Map stable domain errors to 404/409/422 in `main.py`, without returning reference answers, provider errors or raw exception strings.

- [x] **Step 3: Write frontend state-view tests**

Cover exactly three main states:

- no active round -> setup and question availability;
- waiting/running -> current question, ordinal/total, answer or follow-up, usage/context and controls;
- report/completed -> attempt summary, mastery changes, drafts and publication state.

Also cover:

- 一级导航将“题库整理”和“开始复习”作为独立入口，切换后保留各自 Query/resource 上下文；
- 题库列表的搜索、topic/难度/来源/状态筛选、真实批次进度与服务端计数；
- 选中候选默认显示渲染后的 Markdown，只有进入编辑或选择“Markdown 原文”才显示源码；
- AI 建议、重复对比和 pending decision 绑定当前候选，无不确定项时确认卡完全不渲染；
- history switching、page refresh、pending action on demand、model failure preserving typed input、duplicate submit conflict 和 missing-session cleanup。

- [x] **Step 4: Implement typed API and components**

Use TanStack Query for server resources and mutation invalidation. Keep only unsent text、筛选/面板开合和 transient control state locally. Do not reconstruct progress、catalog counts 或 batch status from SSE arrays.

按照 spec 11 的 UI 契约实现统一 `ReviewShell`：桌面端保持稳定深色应用侧栏，一级入口为“题库整理”和“开始复习”；题库模块的二级导航是分类/待确认计数，复习模块的二级导航是轮次历史/派生讨论。窄屏将二级导航降级为抽屉，不把桌面三栏压缩到 375px。

题库整理桌面端必须形成“应用导航 + 题目列表 + 详情面板”工作台：

- 页头操作为“导入文档”和“AI 整理”；摘要、解析进度、搜索与组合筛选位于列表上方；
- 列表行展示题目、分类、难度、来源与状态，选择行只加载详情，不触发发布；
- 详情面板默认渲染 Markdown，提供原文/编辑入口、AI 建议、重复对比、保存草稿和确认入库；
- 人工确认只在当前候选存在 pending decision 时渲染，普通已整理题目不预留空卡片。

复习桌面端形成“会话导航 + 对话式答题 + 运行状态”三栏：题目、回答、结构化评价和追问在中央消息流中；模型/思考强度、usage/context、掌握度与产物在右栏；普通 input request 不显示审批 UI。

`ReviewPage` composes:

```tsx
<QuestionCatalog />
<ReviewHistory />
{round == null ? <ReviewSetup /> : null}
{round?.status === "waiting_for_input" || round?.status === "running"
  ? <ReviewRound />
  : null}
{round?.status === "report_pending" || round?.status === "completed"
  ? <ReviewResults />
  : null}
```

History appears in the existing page layout; derived discussion is an explicit action on an attempt. Approval UI renders only when the current action is pending.

模型与思考强度由创建轮次命令写入 session/round 配置，并在进行中只读展示；不得只在组件内切换下拉值而不影响后续模型调用。若本阶段支持中途修改，必须新增显式命令、审计生效边界并测试“从下一次调用生效”。

- [x] **Step 5: Connect question curation to Knowledge**

Uploading a source only registers the source. The user selects one or more sources and requests a question batch. Display candidate title, corrected answer, classification, duplicate warning and source evidence through the existing draft review/publish flow. `KnowledgePage` 保留 source/知识文档能力；题目候选的整理、筛选与确认集中在 `QuestionCatalog` 工作台，不能让用户在两个页面重复处理同一 candidate。

Active question counts and topics come from `GET /api/review/questions`, not component-held uploaded draft state.

- [x] **Step 6: Make SSE refresh domain resources**

Add R2 event types to `useAgentEvents`. On progress/input/report events, invalidate the current round and history queries. Keep cursor deduplication and missing-session termination from `06cd5d3`.

No event payload may contain the full answer, reference answer, source text or report Markdown.

- [ ] **Step 7: Run cross-layer tests and minimal browser path**

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short   tests/test_review_api_v2.py tests/test_review_api_restart.py   tests/test_agent_routes_v2.py tests/test_draft_routes.py
cd ../frontend
./node_modules/.bin/vitest run   src/features/review/reviewApi.test.ts   src/features/review/ReviewPage.test.tsx   src/features/review/ReviewRound.test.tsx   src/features/review/QuestionCatalog.test.tsx   src/features/review/QuestionDetailPanel.test.tsx   --reporter=dot
npm run build
cd ..
frontend/node_modules/.bin/playwright test   --config playwright.config.ts tests/e2e/r2-review-happy-path.spec.ts   --reporter=line
```

Expected happy path: enter “题库整理”, import/select sources, inspect rendered candidate detail, resolve one duplicate/pending decision, publish question candidates, switch to “开始复习”, create a two-question round, answer once, handle one follow-up, complete, approve the report and see the Vault target path. Capture desktop evidence for both reference layouts; compare information hierarchy and behavior, not screenshot pixels.

- [x] **Step 8: Commit Task 3**

```bash
git add backend/app backend/tests frontend/src tests/e2e
git commit -m "feat(review): complete the multi-question Web experience"
```

---

### Task 4: Prove complete review usability and close R2

**Files:**
- Modify: `docs/verification/r2-complete-review-agent.md` (local, explicitly synchronize after merge)
- Create: `docs/learning/r2-complete-review-agent/overview.md` (local)
- Create: `docs/learning/r2-complete-review-agent/architecture.md` (local)
- Create: `docs/learning/r2-complete-review-agent/code-walkthrough.md` (local)
- Create: `docs/learning/r2-complete-review-agent/failure-journal.md` (local)
- Create: `docs/learning/r2-complete-review-agent/exercises.md` (local)
- Create: `docs/learning/r2-complete-review-agent/interview-questions.md` (local)
- Create: `docs/learning/r2-complete-review-agent/presentation-script.md` (local)
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Final evidence proves the Web review requirements in `docs/my_idea.md` section 3.
- R8 WeChat/Feishu native chat remains explicitly pending and is not claimed by responsive Web evidence.

- [x] **Step 1: Run a real ten-question Provider acceptance**

Use one OpenAI-compatible structured question/evaluation call and one Anthropic-compatible streamed follow-up/report or discussion call. Complete at least ten questions and verify:

- corrected/classified question candidates;
- one necessary follow-up and one skip;
- native and estimated usage visibility;
- at least one role-thread summary;
- later selection reflects confirmed mastery;
- the complete round works with no Langfuse environment variables or services.

Record Provider type, model ID, session ID and round ID; never record API keys or content. A Langfuse trace ID is not required for current R2 evidence.

- [x] **Step 2: Run restart and failure acceptance**

Cover:

- refresh while waiting for an answer;
- backend restart while waiting for answer;
- backend restart while waiting for report approval;
- duplicate answer with same idempotency key;
- conflicting duplicate with a different key;
- model failure and retry without index advance;
- cancel during an active round;
- discussion child session without parent message/checkpoint mutation.

Run these scenarios in the default environment with Langfuse unconfigured. Do not add a separate “Langfuse service unavailable” scenario in R2.

Re-run only the failed scenario after a fix.

- [ ] **Step 3: Run the complete browser acceptance once**

Verify the full user journey:

1. upload loosely formatted question material;
2. generate multiple corrected/classified candidates;
3. use search/filters, rendered preview, Markdown edit, duplicate comparison and on-demand confirmation to edit/reject/rewrite/publish candidates;
4. create a ten-question round using a selected strategy;
5. answer, follow up, skip, leave and continue;
6. finish and inspect per-round/mastery reports;
7. approve, edit and reject publication paths;
8. create a derived discussion and return to the unchanged parent round;
9. start another round and confirm weak-point selection uses confirmed mastery;
10. verify desktop layout and baseline responsive Web quality.

桌面验收使用 spec 中两张效果图做结构参照：题库页核对“导航 + 列表 + 详情”，复习页核对“会话 + 对话 + 状态”；允许 token、真实数据和组件细节不同，但一级入口、区域职责、主要操作顺序与状态显隐不得偏离。375px 单独验证抽屉/顺序降级，不要求复刻桌面三栏。

Do not claim this satisfies WeChat/Feishu Channel acceptance.

- [x] **Step 4: Run final regression once**

```bash
cd backend
.venv/bin/python -m pytest -q --tb=short
cd ../frontend
./node_modules/.bin/vitest run --reporter=dot
npm run build
cd ..
git diff --check
```

Record exact fresh counts from these commands.

- [ ] **Step 5: Finalize verification and learning documents**

Reshape verification into a user guide, then generate the seven `foundation` learning files only after implementation is stable. Include the status-ownership table for Graph checkpoint, Runtime SQLite, Vault and Query cache. Mention OpenTelemetry/Langfuse only as optional observability outside the current acceptance evidence.

Run:

```bash
python3 scripts/check_stage_docs.py   --verification docs/verification/r2-complete-review-agent.md   --learning docs/learning/r2-complete-review-agent/   --plan docs/superpowers/plans/2026-07-14-r2-complete-review-agent.md
```

Expected: documentation gate passes with real browser evidence and current test counts.

- [ ] **Step 6: Commit stage closure**

```bash
git add backend frontend tests docs/superpowers task_plan.md findings.md progress.md
git commit -m "docs(review): close R2 complete review agent"
```

After merging, explicitly synchronize ignored `docs/verification/r2-complete-review-agent.md` and `docs/learning/r2-complete-review-agent/` into the authoritative main worktree and compare their hashes.

---

## Plan Self-Review

- Spec coverage: question curation, four selection modes, long-lived round, answer/follow-up input, skip/cancel/restart, reports, mastery, discussion, middleware, API, Web UI, Provider, default no-Langfuse operation and browser acceptance are each assigned to a task.
- Original idea coverage: corrected/classified question bank, 10/20-question rounds, configurable strategy, logical follow-up, session history/title, derived discussion, per-session report, conflict review, recent-three confirmed reports and global mastery feedback are explicit.
- Boundary check: Web responsive quality is retained but does not claim R8 Channel completion.
- Runtime check: migration is additive on generation 2; no new Agent loop, registry, gateway or pipeline is introduced.
- Type check: `inputRequestId`, `version`, `idempotencyKey`, `waiting_for_input` and `review.round` names remain stable across domain, Graph, API and Web tasks.
