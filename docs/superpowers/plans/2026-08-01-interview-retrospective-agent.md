# Interview Retrospective Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete “文字记录 → 说话人确认 → 渐进逐题复盘 → 候选审核 → 复习/画像/Knowledge 沉淀” workflow under an existing or lightweight Job Target.

**Architecture:** Add one `interview_retrospectives` domain that owns immutable source, cleanup, question, analysis, action-item, and candidate records. Reuse the existing Job Target, Profile, Review, Knowledge, Session/Execution/Trace, HITL, and shared Agent UI foundations; all model-produced cross-domain changes remain reviewable candidates and are committed through deterministic adapters with receipts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, LangGraph, React 19, TypeScript 5.7, TanStack Query, Vitest, Playwright.

## Global Constraints

- `R5` is internal only; UI, API, Agent Registry, and commit messages use “面试复盘” or `interview_retrospective` business names.
- Every persisted retrospective has one `job_target_id`; inline creation may create a lightweight target with only `role_name`.
- One interview round is one retrospective; multiple rounds aggregate only through Job Target projections.
- Source, cleanup, and analysis versions are immutable; active pointers change only after a complete valid replacement exists.
- Model output never directly confirms questions, writes Profile/Project/Review resources, or publishes Knowledge.
- Unconfirmed inferred questions may have draft analysis but cannot produce formal candidates or target risks.
- Source text is capped at 500,000 Unicode characters and only `.txt`/`.md` file uploads are accepted.
- No audio/video transcription, OCR, web research, automatic redaction, global Todo, application tracking, or overall score.
- Long tasks reuse Session/Execution/Checkpoint/Event/Trace and preserve completed work items across stop, refresh, restart, and retry.
- API/database timestamps remain UTC; UI uses shared Asia/Shanghai formatting.
- Targeted tests run per task. The frontend baseline regression already ran once at worktree creation (`335 passed`); do not repeat full frontend regression until final closure unless shared-code fixes require it.
- Run one backend full regression after cross-layer integration and at most one final rerun if broad acceptance fixes require it.
- Run one minimal browser happy path before final documentation and one complete browser acceptance pass at closure.
- Do not modify `docs/my_idea.md`.

---

## File and Responsibility Map

### Backend domain and persistence

- `backend/app/db/migrations/runtime/045_interview_retrospectives.sql`: domain tables, immutable versions, active pointers, indexes, and receipts.
- `backend/app/db/migrations/app/010_interview_retrospective_model_roles.sql`: `retrospective_analysis` and `retrospective_chat` model bindings with safe backfill.
- `backend/app/interview_retrospectives/models.py`: literals and immutable domain records.
- `backend/app/interview_retrospectives/errors.py`: stable domain errors and public codes.
- `backend/app/interview_retrospectives/repository.py`: Workspace-scoped SQL, optimistic concurrency, work-item claiming, fingerprints, and receipts.
- `backend/app/interview_retrospectives/service.py`: lifecycle, version, confirmation, source-clear, question-decision, action, and deletion invariants.
- `backend/app/interview_retrospectives/projection.py`: list/detail/report resources without accidental source-body expansion.
- `backend/app/interview_retrospectives/application.py`: cleanup/analysis orchestration and deterministic cross-domain adapters.

### Backend Agent and API

- `backend/app/agents/interview_retrospective_contracts.py`: strict Cleanup, Question, Analysis, Summary, Candidate, and Chat correction outputs.
- `backend/app/agents/interview_retrospective_agents.py`: analysis and chat model runnables.
- `backend/app/agents/prompts/interview_retrospective_prompts.py`: versioned prompts and bounded renderers.
- `backend/app/graphs/interview_retrospective_cleanup.py`: normalize, window, cleanup, reduce, and review gate.
- `backend/app/graphs/interview_retrospective_analysis.py`: question extraction, per-question work, gap verification, and finalization.
- `backend/app/tools/interview_retrospective_tools.py`: bounded read-only retrospective/target/profile/question/knowledge tools for chat.
- `backend/app/schemas/interview_retrospectives.py`: camelCase commands and resources.
- `backend/app/api/routes_interview_retrospectives.py`: `/api/interview-retrospectives` routes and SSE-compatible run controls.

### Frontend

- `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`: API and view-state types.
- `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`: CRUD, import, cleanup, analysis, candidate, action, chat, and publication calls.
- `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`: route-level list/detail/create state.
- `frontend/src/features/interviewRetrospectives/RetrospectiveList.tsx`: cross-target history and filters.
- `frontend/src/features/interviewRetrospectives/RetrospectiveCreateFlow.tsx`: target selection/inline creation and text input.
- `frontend/src/features/interviewRetrospectives/CleanupWorkbench.tsx`: speaker review, bulk swap, segment edit/ignore, and confirm.
- `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`: report-first shell and responsive pane state.
- `frontend/src/features/interviewRetrospectives/AnalysisProgress.tsx`: persisted stage, count, current item, stop, and retry.
- `frontend/src/features/interviewRetrospectives/QuestionTimeline.tsx`: ordered questions and progressive states.
- `frontend/src/features/interviewRetrospectives/QuestionAnalysisPanel.tsx`: evidence, result, gaps, outline, and answer draft.
- `frontend/src/features/interviewRetrospectives/RetrospectiveCandidates.tsx`: question/profile/project/summary decisions and receipts.
- `frontend/src/features/interviewRetrospectives/RetrospectiveActions.tsx`: local action checklist.
- `frontend/src/features/interviewRetrospectives/RetrospectiveConversation.tsx`: secondary chat panel and correction proposals.
- `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`: 1440/1024/768/390 layouts using existing tokens.

---

## Slice 1 — Capture, cleanup, and confirmation

### Task 1: Persistence contracts and model roles

**Files:**
- Create: `backend/app/db/migrations/runtime/045_interview_retrospectives.sql`
- Create: `backend/app/db/migrations/app/010_interview_retrospective_model_roles.sql`
- Create: `backend/app/interview_retrospectives/__init__.py`
- Create: `backend/app/interview_retrospectives/models.py`
- Create: `backend/app/interview_retrospectives/errors.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `frontend/src/features/settings/providerTypes.ts`
- Modify: `frontend/src/features/settings/ModelBindings.tsx`
- Test: `backend/tests/test_interview_retrospective_migration.py`
- Modify test: `backend/tests/test_app_database.py`
- Modify test: `frontend/src/features/settings/ModelBindings.test.tsx`

**Interfaces:**
- Produces: `RetrospectiveRecord`, `SourceVersionRecord`, `CleanupVersionRecord`, `SegmentRecord`, `QuestionUnitRecord`, `AnalysisRunRecord`, `QuestionAnalysisRecord`, `AssetCandidateRecord`, `ActionItemRecord`.
- Produces model roles: `retrospective_analysis`, `retrospective_chat`.

- [x] **Step 1: Write migration and model-role tests**

```python
def test_retrospective_migration_adds_versioned_domain(connection):
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "interview_retrospectives",
        "interview_source_versions",
        "interview_cleanup_versions",
        "interview_cleanup_work_items",
        "interview_segments",
        "interview_question_units",
        "interview_analysis_runs",
        "interview_analysis_work_items",
        "interview_question_analyses",
        "interview_gaps",
        "interview_asset_candidates",
        "interview_action_items",
        "interview_write_receipts",
    } <= tables


def test_retrospective_model_roles_backfill(app_connection):
    bindings = dict(
        app_connection.execute(
            "SELECT role, provider_model_id FROM workspace_model_bindings "
            "WHERE workspace_id = 'w1'"
        )
    )
    assert bindings["retrospective_analysis"] == bindings["job_analysis"]
    assert bindings["retrospective_chat"] == bindings["project_deep_dive"]
```

- [x] **Step 2: Run RED tests**

Run:

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_migration.py tests/test_app_database.py
```

Expected: FAIL because migration 045, app migration 010, and new roles do not exist.

- [x] **Step 3: Add constrained additive migrations**

The runtime migration must define the following ownership and unique constraints:

```sql
CREATE TABLE interview_retrospectives (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    round_label TEXT NOT NULL,
    interview_date TEXT,
    outcome TEXT NOT NULL DEFAULT 'unrecorded'
        CHECK (outcome IN ('pending','passed','failed','cancelled','unrecorded')),
    note TEXT NOT NULL DEFAULT '',
    lifecycle_status TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_status IN ('active','archived','recycled')),
    active_source_version_id TEXT,
    active_cleanup_version_id TEXT,
    active_analysis_run_id TEXT,
    analysis_session_id TEXT NOT NULL REFERENCES agent_sessions(id),
    chat_session_id TEXT NOT NULL REFERENCES agent_sessions(id),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE interview_source_versions (
    id TEXT PRIMARY KEY,
    retrospective_id TEXT NOT NULL
        REFERENCES interview_retrospectives(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('transcript','recollection')),
    file_name TEXT,
    body TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    cleared_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(retrospective_id, ordinal)
);
```

Add the remaining named tables with:

- immutable `(retrospective_id, ordinal)` versions and resumable cleanup window work items;
- `(cleanup_version_id, ordinal)` ordered segments;
- question provenance `original/inferred` and decision `pending/confirmed/rejected/superseded`;
- analysis/work-item status CHECK constraints;
- candidate kind `review_question/profile_claim/project_narrative/summary`;
- action kind and state CHECK constraints;
- unique fingerprints and `(retrospective_id, idempotency_key)` receipts;
- indexes for workspace/lifecycle, target/date, cleanup/order, analysis/status, question/order, candidate/status, and action/status.

App migration 009 rebuilds the binding role constraint, preserves existing rows, and backfills:

```sql
INSERT INTO workspace_model_bindings(workspace_id, role, provider_model_id)
SELECT workspace_id, 'retrospective_analysis', provider_model_id
FROM workspace_model_bindings WHERE role = 'job_analysis';

INSERT INTO workspace_model_bindings(workspace_id, role, provider_model_id)
SELECT workspace_id, 'retrospective_chat', provider_model_id
FROM workspace_model_bindings WHERE role = 'project_deep_dive';
```

- [x] **Step 4: Add exact domain literals and frozen records**

```python
SourceKind = Literal["transcript", "recollection"]
SpeakerRole = Literal["candidate", "interviewer", "unknown"]
QuestionOrigin = Literal["original", "inferred"]
QuestionDecision = Literal["pending", "confirmed", "rejected", "superseded"]
QuestionKind = Literal[
    "technical_knowledge", "project_experience", "system_design",
    "behavioral_collaboration", "motivation_hr", "unknown",
]
AnalysisVerdict = Literal[
    "strong", "improvable", "high_risk", "insufficient_evidence"
]
GapKind = Literal["material", "expression", "knowledge", "experience"]
```

Every dataclass uses `@dataclass(frozen=True, slots=True)` and carries stable IDs, ownership IDs, version/ordinal, and UTC timestamps matching the migration.

- [x] **Step 5: Extend settings role contracts and UI labels**

Add both roles to backend `ModelRole`, model-role tuples, frontend `ModelRole`, and settings cards:

```ts
retrospective_analysis: {
  title: "面试复盘分析",
  description: "整理转写、还原问题并生成结构化逐题分析。",
},
retrospective_chat: {
  title: "面试复盘对话",
  description: "围绕已生成复盘解释结论并提出修正建议。",
},
```

- [x] **Step 6: Run GREEN tests and static checks**

Run:

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_migration.py tests/test_app_database.py
pnpm test -- ModelBindings.test.tsx
pnpm typecheck
git diff --check
```

Expected: all selected tests and typecheck pass.

- [x] **Step 7: Commit Task 1**

```bash
git add backend/app/db/migrations backend/app/interview_retrospectives backend/app/schemas/settings.py backend/tests frontend/src/features/settings
git commit -m "feat: add interview retrospective domain schema"
```

### Task 2: Lifecycle, source versions, cleanup versions, and deletion invariants

**Files:**
- Create: `backend/app/interview_retrospectives/repository.py`
- Create: `backend/app/interview_retrospectives/service.py`
- Create: `backend/app/interview_retrospectives/projection.py`
- Test: `backend/tests/test_interview_retrospective_repository.py`
- Test: `backend/tests/test_interview_retrospective_service.py`

**Interfaces:**
- Consumes: Task 1 records and constraints.
- Produces: `InterviewRetrospectiveService.create(...)`, `add_source_version(...)`, `create_cleanup_version(...)`, `replace_segments(...)`, `confirm_cleanup(...)`, `clear_source(...)`, `archive(...)`, `recycle(...)`, `restore(...)`, `deletion_impact(...)`, `delete_permanently(...)`.

- [x] **Step 1: Write RED lifecycle and ownership tests**

```python
def test_create_requires_same_workspace_target(service, other_workspace_target):
    with pytest.raises(RetrospectiveTargetRequired):
        service.create(
            job_target_id=other_workspace_target.id,
            title="后端一面复盘",
            round_label="一面",
            analysis_session_id="analysis-session",
            chat_session_id="chat-session",
            idempotency_key="create-1",
        )


def test_add_source_is_immutable_and_idempotent(service, retrospective):
    first = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍一下项目\n我：……",
        file_name=None,
        idempotency_key="source-1",
    )
    replay = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="面试官：介绍一下项目\n我：……",
        file_name=None,
        idempotency_key="source-1",
    )
    assert replay.id == first.id
    assert replay.ordinal == 1
```

Also cover 500,000/500,001 characters, `.txt`/`.md` file names, conflicting idempotency replay, expected-version conflicts, cross-workspace IDs, active-run deletion blocking, target cascade, and downstream receipt preservation.

- [x] **Step 2: Run RED tests**

Run: `./.venv/bin/pytest -q tests/test_interview_retrospective_repository.py tests/test_interview_retrospective_service.py`

Expected: FAIL because repository/service modules do not exist.

- [x] **Step 3: Implement Workspace-scoped repository methods**

Repository queries always join or filter `workspace_id`. Transactions are short and deterministic. Provide exact methods:

```python
create_retrospective(...)-> RetrospectiveRecord
get_retrospective(retrospective_id: str) -> RetrospectiveRecord
list_retrospectives(*, job_target_id: str | None, lifecycle: str) -> tuple[RetrospectiveRecord, ...]
insert_source_version(...)-> SourceVersionRecord
insert_cleanup_version(...)-> CleanupVersionRecord
replace_cleanup_segments(cleanup_version_id: str, segments: tuple[dict, ...]) -> tuple[SegmentRecord, ...]
confirm_cleanup(cleanup_version_id: str, *, expected_version: int) -> CleanupVersionRecord
active_execution_ids(retrospective_id: str) -> tuple[str, ...]
save_receipt(scope: str, idempotency_key: str, request_hash: str, result_json: str) -> None
```

- [x] **Step 4: Implement service invariants**

The service validates target ownership, lifecycle, source size/type, body hash, version preconditions, cleanup/source relationships, and deletion blockers. `clear_source` performs one transaction that empties source body and stored excerpts, sets `cleared_at`, and preserves hashes and structured results.

- [x] **Step 5: Add body-safe projections**

List resources include counts and active status but never source body. Source body is returned only by an explicit detail method. Cleared sources return `bodyAvailable=false`, `body=null`, and `clearedAt`.

- [x] **Step 6: Run GREEN tests**

Run:

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_repository.py tests/test_interview_retrospective_service.py tests/test_job_target_repository.py
./.venv/bin/python -m compileall -q app
git diff --check
```

- [x] **Step 7: Commit Task 2**

```bash
git add backend/app/interview_retrospectives backend/tests/test_interview_retrospective_*.py
git commit -m "feat: add retrospective lifecycle and version services"
```

### Task 3: Cleanup Agent, background execution, and API

**Files:**
- Create: `backend/app/agents/interview_retrospective_contracts.py`
- Create: `backend/app/agents/interview_retrospective_agents.py`
- Create: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Create: `backend/app/graphs/interview_retrospective_cleanup.py`
- Create: `backend/app/interview_retrospectives/application.py`
- Create: `backend/app/schemas/interview_retrospectives.py`
- Create: `backend/app/api/routes_interview_retrospectives.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/observability/registry.py`
- Test: `backend/tests/test_interview_retrospective_agents.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`
- Test: `backend/tests/test_interview_retrospective_api.py`

**Interfaces:**
- Consumes: Task 2 service.
- Produces: `POST /api/interview-retrospectives`, source import, cleanup start/detail/update/confirm, archive/recycle/restore/delete routes.
- Produces Agent Registry key `interview_retrospective` and execution capability metadata.

- [x] **Step 1: Write strict contract RED tests**

```python
def test_cleanup_output_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CleanupOutput.model_validate({
            "segments": [{
                "ordinal": 1,
                "speakerRole": "candidate",
                "displayName": "我",
                "text": "回答",
                "sourceStart": 0,
                "sourceEnd": 2,
                "confidence": 0.9,
                "unexpected": True,
            }]
        })
```

Cover ascending offsets, non-overlap, role enums, confidence `[0,1]`, bounded names/text, source-window ownership, and input-type prompt identity.

- [x] **Step 2: Write cleanup execution RED tests**

Prove create makes one visible chat Session and one system analysis Session, start cleanup returns immediately with Execution ID, completed windows reduce by source offset, restart resumes pending windows, stop preserves completed windows, and Trace failure does not fail cleanup.

- [x] **Step 3: Implement prompts, contracts, and Agent factory bindings**

Define stable prompt IDs:

```python
RETROSPECTIVE_CLEANUP_PROMPT = PromptSpec(
    id="interview_retrospective.cleanup",
    version="2026-08-01",
    system="只整理当前文字，不补写缺失对话；输出必须保留源 offset。",
)
```

Use `retrospective_analysis` binding and no tools. Agent output must be a strict `CleanupOutput`.

- [x] **Step 4: Implement bounded cleanup Graph and reducer**

Nodes are `normalize_source`, `create_windows`, `cleanup_window`, `reduce_segments`, `persist_review`. Windows are at most 24,000 characters with 1,000-character overlap. The reducer rejects offset regression and deduplicates overlap by `(source_start, source_end, normalized_text)`.

- [x] **Step 5: Implement application orchestration**

`create_retrospective` creates the two Sessions, then the domain record. `start_cleanup` validates source availability, creates CleanupVersion plus work items, prepares an Execution, and schedules background processing. `confirm_cleanup` verifies all included segments have known roles and atomically activates the version.

- [x] **Step 6: Add camelCase schemas and routes**

Required endpoints:

```text
GET    /api/interview-retrospectives
POST   /api/interview-retrospectives
GET    /api/interview-retrospectives/{id}
PATCH  /api/interview-retrospectives/{id}
POST   /api/interview-retrospectives/{id}/sources
GET    /api/interview-retrospectives/{id}/sources/{versionId}
POST   /api/interview-retrospectives/{id}/cleanup-runs
GET    /api/interview-retrospectives/{id}/cleanup-runs/{versionId}
PATCH  /api/interview-retrospectives/{id}/cleanup-runs/{versionId}/segments
POST   /api/interview-retrospectives/{id}/cleanup-runs/{versionId}/confirm
POST   /api/interview-retrospectives/{id}/archive
POST   /api/interview-retrospectives/{id}/recycle
POST   /api/interview-retrospectives/{id}/restore
GET    /api/interview-retrospectives/{id}/deletion-impact
DELETE /api/interview-retrospectives/{id}
```

All writes require `Idempotency-Key`; versioned writes require `expectedVersion`.

- [x] **Step 7: Register Runtime and observability metadata**

Registry display name is “面试复盘”; task titles use target/round metadata. Add `WorkspaceRuntime.interview_retrospectives` application/service access without changing existing constructors’ public behavior.

- [x] **Step 8: Run Task 3 GREEN tests**

Run:

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_agents.py tests/test_interview_retrospective_cleanup.py tests/test_interview_retrospective_api.py tests/test_agent_observability_registry.py
./.venv/bin/python -m compileall -q app
git diff --check
```

- [x] **Step 9: Commit Task 3**

```bash
git add backend/app backend/tests/test_interview_retrospective_*.py
git commit -m "feat: add retrospective cleanup workflow"
```

### Task 4: Capture and cleanup workbench UI

**Files:**
- Create: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Create: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Create: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveList.tsx`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveCreateFlow.tsx`
- Create: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.tsx`
- Create: `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`
- Modify: `frontend/src/app/navigation/navigationItems.ts`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/features/jobTargets/JobTargetWorkspace.tsx`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveCreateFlow.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`
- Modify test: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: Task 3 API.
- Produces: `/retrospectives` top-level route and Job Target deep link.

- [x] **Step 1: Write RED component tests**

Cover target required/inline creation, source-kind selection, 500,000-character counter, `.txt`/`.md` validation, IME-safe shared composer behavior, persisted cleanup progress, uncertain-segment focus, bulk speaker swap, segment ignore, expected-version conflict refresh, and confirm gate.

Slice 1 has no message composer; IME behavior remains assigned to Task 9 when continuing chat is introduced. The capture textarea, lifecycle recovery and cleanup controls are covered here.

- [x] **Step 2: Run RED tests**

Run: `pnpm test -- RetrospectiveCreateFlow.test.tsx CleanupWorkbench.test.tsx InterviewRetrospectivePage.test.tsx`

Expected: FAIL because components do not exist.

- [x] **Step 3: Add typed API client and Query keys**

Use stable keys `['retrospectives', workspaceId, filters]`, `['retrospective', id]`, `['cleanup', id, versionId]`. Mutations invalidate only affected list/detail/cleanup keys.

- [x] **Step 4: Implement list and create flow**

The top-level page shows active/archive/recycle tabs, target filter using shared `SelectControl`, recent rows, result/date/round metadata, and one primary “新建复盘” action. The create flow uses a visible two-choice input type and target selection with inline lightweight target creation.

- [x] **Step 5: Implement CleanupWorkbench**

Render source-aligned segments, role chips, uncertainty reasons, inline role/name edit, ignore toggle, global swap, progress/stop/retry, and a sticky confirm action. Confirm remains disabled while included segments have `unknown` roles or cleanup is incomplete.

- [x] **Step 6: Add dual navigation**

Add `/retrospectives` with a dedicated navigation icon and add a target-scoped link that passes `jobTargetId` as a URL search parameter. Both routes render the same resources.

- [x] **Step 7: Run focused UI checks**

Run:

```bash
pnpm test -- RetrospectiveCreateFlow.test.tsx CleanupWorkbench.test.tsx InterviewRetrospectivePage.test.tsx App.test.tsx
pnpm typecheck
pnpm build
git diff --check
```

- [x] **Step 8: Minimal browser Slice 1 path**

At 1440 and 390 widths: create a lightweight target, paste a transcript, start fake-provider cleanup, correct one uncertain speaker, confirm cleanup, refresh, and verify the confirmed version remains selected. Confirm no horizontal overflow and no console warning/error.

- [x] **Step 9: Update Slice 1 verification and commit**

Update local `docs/verification/interview-retrospective.md` with commands and screenshots, then commit product/formal files only:

```bash
git add frontend/src backend/app backend/tests docs/superpowers
git commit -m "feat: add interview capture and cleanup workbench"
```

---

## Slice 2 — Progressive analysis and report

### Task 5: Question extraction, per-question analysis, and progressive API

**Files:**
- Modify: `backend/app/agents/interview_retrospective_contracts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Create: `backend/app/graphs/interview_retrospective_analysis.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/interview_retrospectives/projection.py`
- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Test: `backend/tests/test_interview_retrospective_analysis.py`
- Test: `backend/tests/test_interview_question_decisions.py`
- Modify test: `backend/tests/test_interview_retrospective_api.py`

**Interfaces:**
- Consumes: confirmed CleanupVersion.
- Produces: question list, progressive AnalysisRun, question decision, partial retry, stop/resume, and report endpoints.

- [x] **Step 1: Write RED analysis tests**

Prove: unconfirmed cleanup is rejected; questions persist before analysis completion; original/inferred provenance survives projection; inferred questions default pending; completed question work survives stop/restart; finalizer excludes pending inferred questions; no overall score exists; same digest is idempotent.

- [x] **Step 2: Define strict outputs**

```python
class QuestionAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["strong", "improvable", "high_risk", "insufficient_evidence"]
    strengths: list[BoundedPoint]
    improvements: list[BoundedPoint]
    omissions: list[BoundedPoint]
    gaps: list[GapOutput]
    evidence_level: Literal[
        "internal_evidence", "profile_conflict", "model_judgment", "insufficient"
    ]
    confidence: float = Field(ge=0, le=1)
    improvement_outline: list[str] = Field(max_length=8)
    suggested_answer: str = Field(max_length=6000)
```

Question extraction output carries ordered segment IDs, origin, inference evidence, kind, and confidence.

- [x] **Step 3: Implement analysis work items**

Create stable work keys:

```text
question_extraction
question_analysis:{question_unit_id}
gap_verification
candidate_generation
final_projection
```

The application persists question units after extraction, then creates one work item per question. A single reducer writes final ordering and aggregate summary. Stop prevents new claims; critical sections persist one completed item atomically.

- [x] **Step 4: Implement frozen bounded context**

Freeze target ID/document version, confirmed Profile context version, relevant question IDs, Knowledge refs, and prompt/model identity in the run input digest. Provider payload uses bounded excerpts rather than storage paths or full Profile documents.

- [x] **Step 5: Implement question decisions and partial rerun**

`decide_question(question_id, decision, edited_text, expected_version, idempotency_key)` confirms/rejects/supersedes. Confirming or editing an inferred question schedules only that question plus aggregate/candidate finalizers. Changing segment boundaries invalidates affected question units and requires a new CleanupVersion.

- [x] **Step 6: Add analysis endpoints**

```text
POST /{id}/analysis-runs
GET  /{id}/analysis-runs/{runId}
POST /{id}/analysis-runs/{runId}/stop
POST /{id}/analysis-runs/{runId}/resume
POST /{id}/analysis-runs/{runId}/retry
GET  /{id}/questions
POST /{id}/questions/{questionId}/decision
GET  /{id}/report
```

Report returns progressive items with `pending/running/completed/failed/blocked` state and never synthesizes missing results client-side.

- [x] **Step 7: Run GREEN tests**

Run:

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_analysis.py tests/test_interview_question_decisions.py tests/test_interview_retrospective_api.py tests/test_execution_cancellation.py
./.venv/bin/python -m compileall -q app
git diff --check
```

- [x] **Step 8: Commit Task 5**

```bash
git add backend/app backend/tests/test_interview_*.py
git commit -m "feat: add progressive interview analysis"
```

### Task 6: Report-first progressive workspace

**Files:**
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`
- Create: `frontend/src/features/interviewRetrospectives/AnalysisProgress.tsx`
- Create: `frontend/src/features/interviewRetrospectives/QuestionTimeline.tsx`
- Create: `frontend/src/features/interviewRetrospectives/QuestionAnalysisPanel.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Modify: `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`
- Test: `frontend/src/features/interviewRetrospectives/AnalysisProgress.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/QuestionTimeline.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/QuestionAnalysisPanel.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.test.tsx`

**Interfaces:**
- Consumes: Task 5 progressive resources.
- Produces: report-first detail route and advanced run-detail deep link with return context.

- [ ] **Step 1: Write RED UI tests**

Cover real progress counts, completed questions appearing before finalization, failed-item emphasis and default selection, inferred badges/decision controls, evidence-level language, absent overall score, source-cleared state, stop/resume/retry, and return URL to the selected retrospective/question.

- [ ] **Step 2: Implement persisted polling/event refresh**

Poll only while run status is active; stop after terminal/review state. Preserve selected question ID in URL search params. Do not reset selection when new progressive items arrive unless the selected item disappears.

- [ ] **Step 3: Implement report-first responsive shell**

At desktop widths, use a bounded question rail and flexible detail pane. Failed questions use the error palette; pending inferred questions use warning palette. On initial load select the first failed question, otherwise the first high-risk question, otherwise the first completed question.

- [ ] **Step 4: Implement analysis content**

Show verdict text, confidence, evidence level, strengths, improvements, omissions, four gap kinds, improvement outline, suggested answer, source excerpt, and “模型判断，建议核对” where applicable. Do not render empty cards.

- [ ] **Step 5: Add advanced run-detail navigation**

Pass `returnTo=/retrospectives/{id}?questionId={questionId}`. The business page keeps a visible “查看运行详情” action without hiding it in a collapsed technical section.

- [ ] **Step 6: Run focused checks and commit**

```bash
pnpm test -- AnalysisProgress.test.tsx QuestionTimeline.test.tsx QuestionAnalysisPanel.test.tsx RetrospectiveWorkspace.test.tsx
pnpm typecheck
pnpm build
git diff --check
git add frontend/src/features/interviewRetrospectives frontend/src/app
git commit -m "feat: add progressive retrospective report"
```

---

## Slice 3 — Candidate review, practice, and publication

### Task 7: Deterministic candidate adapters and receipts

**Files:**
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/interview_retrospectives/projection.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Modify: `backend/app/knowledge/document_types.py`
- Modify: `backend/app/knowledge/workspace_layout.py`
- Modify: `backend/app/knowledge/frontmatter.py`
- Test: `backend/tests/test_interview_retrospective_candidates.py`
- Test: `backend/tests/test_interview_retrospective_publication.py`
- Test: `backend/tests/test_interview_retrospective_review_adapter.py`

**Interfaces:**
- Consumes: completed confirmed question analyses.
- Produces: candidate list/decision, Review/Profile/Project adapters, immediate practice launch, action items, and Knowledge draft/publication selection.

- [ ] **Step 1: Write RED candidate safety tests**

Prove pending inferred questions cannot produce candidates; model output only inserts retrospective candidate rows; similar questions return match choices; cross-workspace targets fail; same receipt does not duplicate writes; partial failure preserves failed candidates; rejected fingerprint is not re-proposed.

- [ ] **Step 2: Implement candidate generation and matching**

Generate candidates only after all eligible question work completes. Use existing Review similarity, Profile candidate matching, and project narrative lookup. Store match IDs and scores as suggestions; do not auto-merge.

- [ ] **Step 3: Implement deterministic adapters**

Exact actions:

```text
review_question: link_existing | supplement_existing | create_new | reject
profile_claim: link_existing | propose_update | propose_new | reject
project_narrative: link_existing | propose_update | propose_new | reject
summary: include | exclude
```

Each adapter validates candidate kind, current version, target Workspace, and action payload; calls the owning service; then saves one immutable write receipt with target resource ID.

- [ ] **Step 4: Add immediate-practice bridge**

Only a confirmed Review question resource can start a Review round. Return a stable `/review?questionId=...&source=retrospective&id=...` link and never create a second question during launch.

- [ ] **Step 5: Add action item commands**

Create action items during finalization with source question/gap IDs. Expose only `pending → completed/dismissed`; retries with the same expected version are idempotent.

- [ ] **Step 6: Add Knowledge document type and safe projection**

Register:

```python
DocumentTypeDefinition(
    name="interview_retrospective",
    directory="60_interview_retrospectives",
)
```

The Markdown renderer receives only selected confirmed fields and stable links. Tests assert raw source bodies, pending inferred questions, chat messages, prompt text, and provider responses are absent.

- [ ] **Step 7: Add candidate/action/publication endpoints**

```text
GET  /{id}/candidates
POST /{id}/candidates/{candidateId}/decision
POST /{id}/candidates/batch-decision
GET  /{id}/actions
POST /{id}/actions/{actionId}/decision
POST /{id}/publication-drafts
```

- [ ] **Step 8: Run GREEN tests and commit**

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_candidates.py tests/test_interview_retrospective_publication.py tests/test_interview_retrospective_review_adapter.py tests/test_question_similarity.py
./.venv/bin/python -m compileall -q app
git diff --check
git add backend/app backend/tests/test_interview_*.py
git commit -m "feat: connect retrospective findings to preparation assets"
```

### Task 8: Candidate, action, and publication UI

**Files:**
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveCandidates.tsx`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveActions.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Modify: `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveCandidates.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveActions.test.tsx`

**Interfaces:**
- Consumes: Task 7 APIs.
- Produces: visible three-group review queue, matching choices, immediate practice, action checklist, and summary publication flow.

- [ ] **Step 1: Write RED UI tests**

Cover counts from server, pending-inference blockers, existing/new match choices, batch preflight, partial-failure retention, immediate-practice link, action state, selected summary fields, and raw-transcript exclusion copy.

- [ ] **Step 2: Implement grouped review queue**

Use three primary groups: “复习题”“项目与画像”“复盘总结”. Keep all tabs visible after selection. Each row shows source question, match status, decision, and resulting resource link.

- [ ] **Step 3: Implement batch and partial failure behavior**

Batch submission sends explicit candidate IDs and actions. Successful rows leave pending queue; failed rows remain selected with stable reason and retry action.

- [ ] **Step 4: Implement action and publication panels**

Action items are compact checklist rows, not cards per item. Publication shows selectable sections, preview, Knowledge confirmation, and success link; no transcript option exists.

- [ ] **Step 5: Run focused tests and commit**

```bash
pnpm test -- RetrospectiveCandidates.test.tsx RetrospectiveActions.test.tsx RetrospectiveWorkspace.test.tsx
pnpm typecheck
pnpm build
git diff --check
git add frontend/src/features/interviewRetrospectives
git commit -m "feat: add retrospective review and publication UI"
```

---

## Slice 4 — Conversation, local recomputation, aggregation, and closure

### Task 9: Bounded chat, correction proposals, and local recomputation

**Files:**
- Create: `backend/app/tools/interview_retrospective_tools.py`
- Modify: `backend/app/agents/interview_retrospective_contracts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveConversation.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`
- Test: `backend/tests/test_interview_retrospective_chat.py`
- Test: `backend/tests/test_interview_retrospective_reanalysis.py`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveConversation.test.tsx`

**Interfaces:**
- Consumes: chat Session from Task 2 and analysis versions from Task 5.
- Produces: explanation messages, typed correction proposals, proposal confirmation, affected-question rerun, and full-rerun command.

- [ ] **Step 1: Write RED tool and chat tests**

Assert tools only read the current retrospective and bounded authorized contexts, arbitrary IDs and paths fail, chat cannot write domains, explanation does not create a version, correction confirmation creates a version, and one-question correction schedules only one question plus finalizers.

- [ ] **Step 2: Implement read-only tool allowlist**

Provide exact tools:

```text
read_retrospective_summary
read_question_analysis
read_source_excerpt
search_target_requirements
search_confirmed_profile
search_review_questions
search_active_knowledge
```

Each returns at most 20 items and 2,000 characters per excerpt; Workspace/retrospective IDs come from `AgentContext`, never model arguments.

- [ ] **Step 3: Implement typed chat result**

Chat output is either explanation text or one of:

```text
question_text_correction
question_segment_rebind
speaker_correction
analysis_reconsideration
```

Correction proposals persist with source version and expected version. Confirming invokes deterministic application commands; rejecting only updates proposal state.

- [ ] **Step 4: Implement secondary conversation panel**

Reuse shared `AgentComposer`, keyboard hook, message rendering, stop/retry, and execution summary. The panel opens without replacing report selection. Correction proposals use explicit before/after and confirm/reject actions.

- [ ] **Step 5: Run GREEN tests and commit**

```bash
./.venv/bin/pytest -q tests/test_interview_retrospective_chat.py tests/test_interview_retrospective_reanalysis.py tests/test_agent_tool_guards.py
pnpm test -- RetrospectiveConversation.test.tsx
pnpm typecheck
git diff --check
git add backend/app backend/tests frontend/src/features/interviewRetrospectives
git commit -m "feat: add retrospective discussion and corrections"
```

### Task 10: Target aggregation, source clearing, deletion, and cross-layer acceptance

**Files:**
- Modify: `backend/app/job_targets/projection.py`
- Modify: `backend/app/api/routes_job_targets.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Modify: `frontend/src/features/jobTargets/JobTargetOverview.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`
- Test: `backend/tests/test_job_target_retrospective_projection.py`
- Test: `backend/tests/test_interview_retrospective_source_clear.py`
- Test: `backend/tests/test_interview_retrospective_deletion.py`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveLifecycle.test.tsx`
- Test: `frontend/src/features/jobTargets/JobTargetComponents.test.tsx`
- Modify: `README.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Create local: `docs/verification/interview-retrospective.md`
- Create local: `docs/learning/interview-retrospective/` seven-file ownership pack

**Interfaces:**
- Consumes: all previous tasks.
- Produces: target summary counts/timeline, safe source-clear UX, deletion impact, final user guide, and closure evidence.

- [ ] **Step 1: Write lifecycle and aggregation RED tests**

Cover cross-round repeated gap counts, target filter, actual outcome updates without analysis mutation, source clear removing all excerpts, cleared-source reanalysis refusal, active-run delete blocker, target cascade, and preservation of external receipt targets.

- [ ] **Step 2: Implement target aggregation**

Expose retrospective count, latest round/date/outcome, unresolved action count, and gap counts by kind. Do not aggregate overall score or copy report bodies into Job Target tables.

- [ ] **Step 3: Implement source clear and deletion UX**

Source-clear dialog lists lost capabilities. Deletion impact separates private records removed from external assets preserved. Require explicit confirmation text only for permanent deletion, not archive/recycle.

- [ ] **Step 4: Run integrated automated verification**

Run targeted affected tests first, then the one planned backend full regression:

```bash
./.venv/bin/pytest -q tests/test_interview_*.py tests/test_job_target_retrospective_projection.py
./.venv/bin/pytest -q
pnpm test -- RetrospectiveLifecycle.test.tsx JobTargetComponents.test.tsx
pnpm typecheck
pnpm build
git diff --check
```

Do not repeat the frontend full suite here because the worktree baseline already consumed that stage-wide run; run it only if shared frontend acceptance fixes require it.

- [ ] **Step 5: Run complete browser acceptance**

Using isolated feature ports/data, verify:

1. create/select target and import transcript;
2. cleanup, uncertain speaker correction, confirm, refresh;
3. progressive analysis, stop, resume, failed-item default selection;
4. inferred question confirm/edit/reject and local rerun;
5. candidate link/update/new choices and immediate Review launch;
6. action completion and selected summary publication;
7. conversation explanation and correction proposal;
8. source clear degradation;
9. multi-round target aggregation;
10. archive/recycle/delete impact;
11. run-center advanced-detail navigation and return;
12. 1440/1024/768/390 layout, keyboard, IME, focus, and console checks.

- [ ] **Step 6: Update user guide and ownership material**

Reshape `docs/verification/interview-retrospective.md` as the final user guide, create the seven-file learning pack using the appropriate risk profile, compare with the previous same-profile stage, and update README/formal roadmap status without modifying `docs/my_idea.md`.

- [ ] **Step 7: Run documentation gate**

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/interview-retrospective.md \
  --learning docs/learning/interview-retrospective/ \
  --plan docs/superpowers/plans/2026-08-01-interview-retrospective-agent.md
```

Expected: PASS with browser acceptance checked and evidence internally consistent.

- [ ] **Step 8: Final commit**

```bash
git add backend frontend README.md task_plan.md findings.md progress.md docs/superpowers
git commit -m "feat: complete interview retrospective workflow"
```

Do not add `docs/learning/` or `docs/verification/` to Git; explicitly synchronize them into the main repository after merge as required by the collaboration rules.

---

## Plan Self-Review

- Spec coverage: Tasks 1–4 cover target binding, input types, immutable source/cleanup versions, speaker confirmation, lifecycle, dual entry, responsive capture, and background cleanup. Tasks 5–6 cover original/inferred questions, progressive analysis, four gap kinds, no total score, evidence levels, answer improvement, stop/retry, and report-first UX. Tasks 7–8 cover candidate generation, dedupe choices, Review/Profile/Project/Knowledge adapters, immediate practice, local actions, and selective publication. Tasks 9–10 cover continuing chat, confirmed versioned corrections, local rerun, target aggregation, source clearing, deletion, observability navigation, acceptance, and ownership documentation.
- Placeholder scan: the plan contains no deferred `TBD`, unspecified “handle errors,” or unnamed test steps. Every task names files, interfaces, commands, expected state, and commit boundary.
- Type consistency: `retrospective_analysis` and `retrospective_chat` are the only new model roles; `SourceVersion → CleanupVersion → AnalysisRun`, question provenance/decision enums, four gap kinds, four verdicts, candidate actions, and action states match the accepted spec and ADR.
- Execution choice: repository rules require one Agent to own the slice end-to-end. Execute inline with `superpowers:executing-plans`; do not dispatch subagents because domain, Runtime, migration, and cross-domain receipt state overlap across tasks.
