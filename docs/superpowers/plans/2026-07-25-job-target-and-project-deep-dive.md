# Job Target and Project Deep-Dive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the first complete “求职目标 → 岗位要求 → 项目深挖 → 项目经历题训练” workflow on the existing Profile, Review, and Agent Runtime foundations.

**Architecture:** Add one `job_targets` domain package that owns target-specific versions, requirements, mappings, analysis work items, project priorities, risks, and deep-dive artifacts. Reuse the existing Profile confirmed-context contract, Session/Execution/Event/Checkpoint runtime, shared Agent workspace, and Review question lifecycle; all model-produced writes remain private proposals until deterministic, confirmed domain writes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLite, LangGraph, React 19, TypeScript 5.7, TanStack Query, Vitest, Playwright.

## Global Constraints

- `R4` is only an internal roadmap label; UI copy, API names, architecture headings, and commit messages use business terms.
- One Job Target has at most one current immutable JD/reference version in the first release.
- Global Profile projects and confirmed narratives are referenced, never copied into Job Target storage.
- Agent code has only bounded read tools and cannot directly confirm requirements, update Profile/narratives, publish questions, or create formal todos.
- Project deep dive uses bounded stages, explicit minimal `state_schema`, domain offload, pause/stop/recovery, and no Time Travel or free-form write ReAct.
- One user Message may have multiple Execution attempts; retry does not create a duplicate user message.
- Long tasks expose persisted stage, counts, elapsed time, latest progress, saved outputs, and recovery controls.
- API/database timestamps remain UTC; UI uses the shared Asia/Shanghai formatter.
- Targeted tests run per task. Full backend/frontend regression runs once after cross-layer integration and once only if the final acceptance fixes changed broad shared code.
- Browser work runs one minimal happy path before final documentation and one complete acceptance pass at closure; affected scenarios alone are repeated after fixes.
- Do not modify `docs/my_idea.md`.

---

## File and Responsibility Map

### New backend units

- `backend/app/job_targets/models.py`: immutable domain records and literals.
- `backend/app/job_targets/repository.py`: SQLite persistence, optimistic concurrency, idempotency receipts, short transactions.
- `backend/app/job_targets/service.py`: target/JD/requirement/project/narrative/gap invariants and derived readiness.
- `backend/app/job_targets/application.py`: cross-domain orchestration with Profile, Review, and Execution services.
- `backend/app/job_targets/projection.py`: API-safe resources and progress projections.
- `backend/app/job_targets/errors.py`: typed domain conflicts and not-found errors.
- `backend/app/schemas/job_targets.py`: FastAPI command/resource contracts.
- `backend/app/api/routes_job_targets.py`: `/api/job-targets` routes.
- `backend/app/agents/job_target_contracts.py`: structured model output contracts.
- `backend/app/agents/job_target_agents.py`: `job_analysis` and `project_deep_dive` model runnables.
- `backend/app/agents/prompts/job_target_prompts.py`: versioned prompts and deterministic input renderers.
- `backend/app/graphs/job_analysis.py`: bounded, recoverable analysis graph.
- `backend/app/graphs/project_deep_dive.py`: explicit deep-dive state and stage graph.
- `backend/app/tools/job_target_tools.py`: scoped read-only tools.

### New frontend units

- `frontend/src/features/jobTargets/jobTargetTypes.ts`: API and view-state types.
- `frontend/src/features/jobTargets/jobTargetApi.ts`: target, analysis, deep-dive, proposal, and question API client.
- `frontend/src/features/jobTargets/JobTargetPage.tsx`: route-level target list/detail state.
- `frontend/src/features/jobTargets/JobTargetList.tsx`: active/archive/recycle list.
- `frontend/src/features/jobTargets/JobTargetWorkspace.tsx`: fixed target header and four tabs.
- `frontend/src/features/jobTargets/JobTargetOverview.tsx`: actionable preparation overview.
- `frontend/src/features/jobTargets/RequirementWorkbench.tsx`: queue/detail requirement confirmation.
- `frontend/src/features/jobTargets/ProjectPriorityPanel.tsx`: core/supplementary project selection.
- `frontend/src/features/jobTargets/JobAnalysisStatus.tsx`: long-task facts and controls.
- `frontend/src/features/jobTargets/DeepDiveWorkspace.tsx`: shared Agent workspace composition.
- `frontend/src/features/jobTargets/DeepDiveContextPanel.tsx`: scope, draft, gaps, runtime, Token/context.
- `frontend/src/features/jobTargets/NarrativeDiffPanel.tsx`: section-level proposal confirmation.
- `frontend/src/features/jobTargets/ProjectQuestionCandidates.tsx`: project-question candidate review.

### Existing integration points

- Runtime: `backend/app/application/session_service.py`, `backend/app/application/execution_service.py`, `backend/app/application/graph_factory.py`, `backend/app/application/workspace_runtime.py`.
- Profile: `backend/app/profile/service.py`, `backend/app/profile/repository.py`, `backend/app/profile/models.py`.
- Review: `backend/app/review/models.py`, `backend/app/review/repository.py`, `backend/app/review/application.py`, `backend/app/review/service.py`.
- Settings: `backend/app/schemas/settings.py`, `frontend/src/features/settings/providerTypes.ts`, `frontend/src/features/settings/ModelBindings.tsx`.
- App shell: `backend/app/main.py`, `frontend/src/app/layout/AppShell.tsx`, `frontend/src/app/navigation/navigationItems.ts`.
- Shared Agent UI: `frontend/src/shared/agent/AgentWorkspaceShell.tsx`, `AgentMessage.tsx`, `AgentProcessCard.tsx`, `AgentComposer.tsx`.

---

### Task 1: Persistence contracts, model roles, and runtime attempt links

**Files:**
- Create: `backend/app/db/migrations/runtime/030_job_target_project_training.sql`
- Create: `backend/app/db/migrations/app/004_job_target_model_roles.sql`
- Create: `backend/app/job_targets/__init__.py`
- Create: `backend/app/job_targets/models.py`
- Create: `backend/app/job_targets/errors.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/schemas/settings.py`
- Modify: `frontend/src/features/settings/providerTypes.ts`
- Modify: `frontend/src/features/settings/ModelBindings.tsx`
- Test: `backend/tests/test_job_target_migration.py`
- Test: `backend/tests/test_execution_message_attempts.py`
- Modify test: `backend/tests/test_app_database.py`
- Modify test: `frontend/src/features/settings/ModelBindings.test.tsx`

**Interfaces:**
- Produces: `JobTargetRecord`, `JobDocumentVersionRecord`, `JobRequirementRecord`, `JobAnalysisRunRecord`, `JobAnalysisWorkItemRecord`, `ProjectDeepDiveRecord`, `ProjectNarrativeSectionRecord`, `ProjectGapRecord`, `ProjectQuestionCandidateRecord`.
- Produces: `ProductRepository.append_user_message(...)`, `ExecutionService.prepare_for_message(...)`, `ProductRepository.resolve_message(...)`.
- Produces model roles: `job_analysis`, `project_deep_dive`.

- [x] **Step 1: Write migration tests that prove the additive schema and binding backfill**

```python
def test_job_target_migration_adds_domain_and_attempt_links(connection):
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "job_targets",
        "job_document_versions",
        "job_requirements",
        "job_requirement_evidence_links",
        "job_analysis_runs",
        "job_analysis_work_items",
        "job_target_project_priorities",
        "project_deep_dives",
        "project_narrative_sections",
        "project_deep_dive_artifacts",
        "project_gaps",
        "project_question_candidates",
    } <= tables
    run_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(agent_runs)")
    }
    message_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(agent_messages)")
    }
    catalog_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(review_question_catalog)")
    }
    assert {"input_message_id", "retry_of_execution_id"} <= run_columns
    assert {"replaces_message_id", "resolution_status"} <= message_columns
    assert {"question_type", "project_claim_id", "project_dimension"} <= catalog_columns


def test_model_role_migration_backfills_from_existing_roles(app_connection):
    rows = dict(
        app_connection.execute(
            "SELECT role, provider_model_id FROM workspace_model_bindings "
            "WHERE workspace_id = 'w1'"
        )
    )
    assert rows["job_analysis"] == rows["profile_assessment"]
    assert rows["project_deep_dive"] == rows["agent_chat"]
```

- [x] **Step 2: Run the migration tests and confirm RED**

Run:

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_target_migration.py backend/tests/test_app_database.py -q
```

Expected: failure because migration 030, app migration 004, and the new columns/tables do not exist.

- [x] **Step 3: Add domain tables, constraints, and indexes**

The runtime migration must use constrained fields and stable foreign keys. The core shapes are:

```sql
ALTER TABLE agent_runs ADD COLUMN input_message_id TEXT
    REFERENCES agent_messages(id) ON DELETE SET NULL;
ALTER TABLE agent_runs ADD COLUMN retry_of_execution_id TEXT
    REFERENCES agent_runs(id) ON DELETE SET NULL;
ALTER TABLE agent_messages ADD COLUMN replaces_message_id TEXT
    REFERENCES agent_messages(id) ON DELETE SET NULL;
ALTER TABLE agent_messages ADD COLUMN resolution_status TEXT NOT NULL DEFAULT 'active'
    CHECK (resolution_status IN ('active', 'unresolved', 'replaced', 'abandoned'));

CREATE TABLE job_targets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    company_name TEXT,
    role_name TEXT NOT NULL,
    seniority TEXT NOT NULL,
    source_url TEXT,
    lifecycle_status TEXT NOT NULL
        CHECK (lifecycle_status IN ('active', 'archived', 'recycled')),
    current_document_version_id TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE job_document_versions (
    id TEXT PRIMARY KEY,
    job_target_id TEXT NOT NULL REFERENCES job_targets(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('jd_text', 'direction_reference')),
    body TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_target_id, ordinal)
);

ALTER TABLE review_question_candidates
    ADD COLUMN question_type TEXT NOT NULL DEFAULT 'technical'
    CHECK (question_type IN ('technical', 'project_experience'));
ALTER TABLE review_question_candidates ADD COLUMN project_claim_id TEXT;
ALTER TABLE review_question_candidates ADD COLUMN project_dimension TEXT;
ALTER TABLE review_question_candidates ADD COLUMN source_job_target_id TEXT;
ALTER TABLE review_question_candidates ADD COLUMN source_deep_dive_id TEXT;

ALTER TABLE review_question_catalog
    ADD COLUMN question_type TEXT NOT NULL DEFAULT 'technical'
    CHECK (question_type IN ('technical', 'project_experience'));
ALTER TABLE review_question_catalog ADD COLUMN project_claim_id TEXT;
ALTER TABLE review_question_catalog ADD COLUMN project_dimension TEXT;
ALTER TABLE review_question_catalog ADD COLUMN source_job_target_id TEXT;
ALTER TABLE review_question_catalog ADD COLUMN source_deep_dive_id TEXT;
```

Add the remaining tables named by the test with Workspace/Target/Project ownership, JSON byte bounds enforced in repository code, status CHECK constraints copied from the accepted spec, and indexes for `(workspace_id, lifecycle_status)`, `(job_target_id, status)`, `(analysis_run_id, status)`, and `(project_claim_id, status)`.

- [x] **Step 4: Add the two model roles with non-breaking backfill**

`004_job_target_model_roles.sql` rebuilds `workspace_model_bindings`, preserves six existing roles, and inserts:

```sql
INSERT INTO workspace_model_bindings (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'job_analysis', provider_model_id
FROM workspace_model_bindings
WHERE role = 'profile_assessment';

INSERT INTO workspace_model_bindings (
    workspace_id, role, provider_model_id
)
SELECT workspace_id, 'project_deep_dive', provider_model_id
FROM workspace_model_bindings
WHERE role = 'agent_chat';
```

Update backend/frontend role unions, labels, empty bindings, and validation text from six to eight roles.

- [x] **Step 5: Implement one-message-to-many-executions**

Add these repository/service signatures:

```python
def append_user_message(
    self,
    session_id: str,
    *,
    content: str,
    replaces_message_id: str | None = None,
) -> MessageRecord: ...

def resolve_message(
    self,
    message_id: str,
    *,
    expected: tuple[str, ...],
    target: Literal["active", "unresolved", "replaced", "abandoned"],
) -> MessageRecord: ...

async def prepare_for_message(
    self,
    session: SessionRecord,
    *,
    input_message_id: str,
    input: dict[str, Any],
    retry_of_execution_id: str | None = None,
    configuration: dict[str, Any] | None = None,
) -> ExecutionRecord:
    return await self.prepare(
        session,
        input=input,
        project_input_message=False,
        configuration={
            **(configuration or {}),
            "inputMessageId": input_message_id,
            "retryOfExecutionId": retry_of_execution_id,
        },
    )
```

`create_execution` persists both IDs. It validates that the message belongs to the same Session and that the retry parent belongs to the same Session.

- [x] **Step 6: Verify targeted GREEN**

Run:

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_target_migration.py backend/tests/test_execution_message_attempts.py backend/tests/test_app_database.py -q
cd frontend && npm test -- --run src/features/settings/ModelBindings.test.tsx
```

Expected: all selected tests pass.

- [x] **Step 7: Commit the persistence boundary**

```bash
git add backend/app/db/migrations/runtime/030_job_target_project_training.sql backend/app/db/migrations/app/004_job_target_model_roles.sql backend/app/job_targets backend/app/application/session_service.py backend/app/application/execution_service.py backend/app/schemas/settings.py backend/tests/test_job_target_migration.py backend/tests/test_execution_message_attempts.py backend/tests/test_app_database.py frontend/src/features/settings/providerTypes.ts frontend/src/features/settings/ModelBindings.tsx frontend/src/features/settings/ModelBindings.test.tsx
git commit -m "feat(runtime): support job training state and message retries"
```

---

### Task 2: Job Target, immutable JD, and requirement confirmation API

**Files:**
- Create: `backend/app/job_targets/repository.py`
- Create: `backend/app/job_targets/service.py`
- Create: `backend/app/job_targets/projection.py`
- Create: `backend/app/schemas/job_targets.py`
- Create: `backend/app/api/routes_job_targets.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Test: `backend/tests/test_job_target_service.py`
- Test: `backend/tests/test_job_target_api.py`

**Interfaces:**
- Produces: `JobTargetService.create_target`, `archive_target`, `recycle_target`, `restore_target`, `deletion_impact`, `delete_target`.
- Produces: `create_document_version`, `confirm_document_version`, `decide_requirements`, `set_project_priorities`.
- Produces REST resources under `/api/job-targets`.

- [x] **Step 1: Write service tests for ownership, versions, and confirmation**

```python
def test_new_jd_version_does_not_replace_current_until_confirmed(service):
    target = service.create_target(
        role_name="高级后端工程师",
        seniority="5-8 年",
        company_name="示例公司",
        source_url=None,
        idempotency_key="create-1",
    )
    first = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="负责高并发服务设计",
        idempotency_key="jd-1",
    )
    service.confirm_document_version(
        target.id,
        first.id,
        expected_version=service.get_target(target.id).version,
    )
    second = service.create_document_version(
        target.id,
        source_kind="jd_text",
        body="负责高并发服务设计与稳定性治理",
        idempotency_key="jd-2",
    )
    assert service.get_target(target.id).current_document_version_id == first.id
    assert second.id != first.id


def test_inferred_requirement_is_excluded_from_safe_bulk_confirmation(service):
    result = service.decide_requirements(
        target_id="target-1",
        decisions=({"requirementId": "source-1", "decision": "confirm"},),
        confirm_safe_filter=True,
        idempotency_key="bulk-1",
    )
    assert result.confirmed_ids == ("source-1",)
    assert result.excluded_ids == ("inferred-1",)
```

- [x] **Step 2: Run RED**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_target_service.py backend/tests/test_job_target_api.py -q
```

Expected: import failures for the new repository/service/routes.

- [x] **Step 3: Implement deterministic domain operations**

Expose these commands and invariants:

```python
class JobTargetService:
    def create_target(self, *, role_name: str, seniority: str,
                      company_name: str | None, source_url: str | None,
                      idempotency_key: str) -> JobTargetRecord: ...

    def create_document_version(self, target_id: str, *,
                                source_kind: Literal["jd_text", "direction_reference"],
                                body: str, idempotency_key: str
                                ) -> JobDocumentVersionRecord: ...

    def decide_requirements(self, target_id: str, *,
                            decisions: tuple[RequirementDecision, ...],
                            confirm_safe_filter: bool,
                            idempotency_key: str
                            ) -> RequirementDecisionReceipt: ...

    def set_project_priorities(self, target_id: str, *,
                               core_project_id: str,
                               supplementary_project_ids: tuple[str, ...],
                               expected_version: int,
                               idempotency_key: str
                               ) -> ProjectPriorityReceipt: ...
```

Validate:

- one core and at most two supplementary projects;
- every project is a confirmed Profile `project` Claim in the same Workspace;
- only confirmed requirements affect readiness;
- inferred/conflicted/missing-source requirements cannot enter safe bulk confirmation;
- document bodies are immutable;
- metadata edits use target optimistic version without creating a document version.

- [x] **Step 4: Add API commands and resources**

Implement:

```text
POST   /api/job-targets
GET    /api/job-targets
GET    /api/job-targets/{target_id}
PATCH  /api/job-targets/{target_id}
POST   /api/job-targets/{target_id}/archive
POST   /api/job-targets/{target_id}/recycle
POST   /api/job-targets/{target_id}/restore
GET    /api/job-targets/{target_id}/deletion-impact
DELETE /api/job-targets/{target_id}
POST   /api/job-targets/{target_id}/document-versions
POST   /api/job-targets/{target_id}/document-versions/{version_id}/confirm
POST   /api/job-targets/{target_id}/requirements/decisions
PUT    /api/job-targets/{target_id}/project-priorities
```

All mutations require `Idempotency-Key`. Every target lookup checks the route Workspace and domain Workspace before returning data.

- [x] **Step 5: Verify targeted GREEN**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_target_service.py backend/tests/test_job_target_api.py backend/tests/test_profile_context_api.py -q
```

Expected: all selected tests pass; existing confirmed-profile contract remains green.

- [x] **Step 6: Commit the target domain**

```bash
git add backend/app/job_targets backend/app/schemas/job_targets.py backend/app/api/routes_job_targets.py backend/app/main.py backend/app/application/workspace_runtime.py backend/tests/test_job_target_service.py backend/tests/test_job_target_api.py
git commit -m "feat(targets): add job targets and requirement confirmation"
```

---

### Task 3: Recoverable job analysis and scoped read tools

**Files:**
- Create: `backend/app/agents/job_target_contracts.py`
- Create: `backend/app/agents/job_target_agents.py`
- Create: `backend/app/agents/prompts/job_target_prompts.py`
- Create: `backend/app/graphs/job_analysis.py`
- Create: `backend/app/tools/job_target_tools.py`
- Create: `backend/app/job_targets/application.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/api/routes_job_targets.py`
- Modify: `backend/app/profile/service.py`
- Test: `backend/tests/test_job_analysis_graph.py`
- Test: `backend/tests/test_job_analysis_recovery.py`
- Test: `backend/tests/test_job_target_tools.py`

**Interfaces:**
- Produces: `JobAnalysisApplication.start`, `pause`, `resume`, `terminate`, `retry_work_item`, `resource`.
- Produces: `JobRequirementExtraction`, `RequirementEvidenceSuggestion`, `ProjectRelevanceSuggestion`.
- Consumes: `ProfileService.confirmed_profile_context(purpose="job_target_analysis")`.

- [x] **Step 1: Write recovery and scope tests**

```python
@pytest.mark.asyncio
async def test_resume_skips_completed_work_items(application, model):
    run = await application.start("target-1", idempotency_key="analysis-1")
    model.fail_project("project-2")
    await application.wait(run.execution_id)
    assert application.resource(run.id)["progress"]["completed"] == 2
    model.clear_failure()
    resumed = await application.resume(run.id, idempotency_key="resume-1")
    await application.wait(resumed.execution_id)
    assert model.calls_for("requirement_extraction") == 1
    assert model.calls_for("project-1") == 1
    assert model.calls_for("project-2") == 2


def test_job_tool_rejects_unrelated_project(tool, runtime_context):
    with pytest.raises(ToolScopeViolation):
        tool.invoke(
            {"projectId": "project-from-other-workspace"},
            config={"configurable": runtime_context},
        )
```

- [x] **Step 2: Run RED**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_analysis_graph.py backend/tests/test_job_analysis_recovery.py backend/tests/test_job_target_tools.py -q
```

Expected: missing Graph, contracts, tools, and analysis application.

- [x] **Step 3: Implement structured agents and prompts**

Use strict contracts:

```python
class JobRequirementSuggestion(BaseModel):
    stable_key: str
    requirement_type: Literal["responsibility", "skill", "experience", "project"]
    priority: Literal["must_have", "nice_to_have"]
    text: str
    source_quote: str
    source_start: int | None
    source_end: int | None
    inferred: bool


class ProjectRelevanceSuggestion(BaseModel):
    project_claim_id: str
    requirement_ids: list[str]
    claim_version_ids: list[str]
    rationale: str
    unresolved: list[str]
```

`job_analysis` performs one requirement extraction call and bounded project batches. A malformed result gets one repair call, then a retryable work-item failure.

Extend the confirmed-profile purpose allowlist with `job_target_analysis`; retain the existing sensitive-field exclusion, Claim type validation, and maximum item limit.

- [x] **Step 4: Implement persistent work-item orchestration**

The application creates stable keys:

```python
work_items = (
    ("requirement_extraction", document_version.content_hash),
    ("profile_mapping", profile_context.profile_version),
    *(
        (f"project_mapping:{project.claim_id}", project.claim_version_id)
        for project in confirmed_projects
    ),
    ("final_projection", analysis_input_digest),
)
```

Provider calls happen outside transactions. Each completed output is committed in a short repository transaction. Resume skips `completed` items whose input digest matches.

- [x] **Step 5: Wire runtime controls and resources**

Implement:

```text
POST /api/job-targets/{target_id}/analysis-runs
GET  /api/job-targets/{target_id}/analysis-runs/current
POST /api/job-targets/{target_id}/analysis-runs/{run_id}/pause
POST /api/job-targets/{target_id}/analysis-runs/{run_id}/resume
POST /api/job-targets/{target_id}/analysis-runs/{run_id}/terminate
POST /api/job-targets/{target_id}/analysis-runs/{run_id}/work-items/{item_id}/retry
GET  /api/job-targets/{target_id}/events
```

The resource includes:

```python
{
    "stage": "mapping_projects",
    "progress": {"completed": 4, "total": 7, "activeWorkers": 1},
    "timing": {"currentElapsedMs": 18000, "cumulativeElapsedMs": 42000},
    "latestProgressAt": "2026-07-25T08:00:00Z",
    "savedOutputs": {"requirements": 12, "projectMappings": 2},
    "controls": {"canPause": True, "canResume": False, "canTerminate": True},
}
```

- [x] **Step 6: Verify targeted GREEN**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_analysis_graph.py backend/tests/test_job_analysis_recovery.py backend/tests/test_job_target_tools.py backend/tests/test_agent_restart_v2.py -q
```

Expected: selected tests pass with no repeated completed work-item calls.

- [x] **Step 7: Commit recoverable analysis**

```bash
git add backend/app/agents/job_target_contracts.py backend/app/agents/job_target_agents.py backend/app/agents/prompts/job_target_prompts.py backend/app/graphs/job_analysis.py backend/app/tools/job_target_tools.py backend/app/job_targets/application.py backend/app/application/graph_factory.py backend/app/application/workspace_runtime.py backend/app/application/execution_service.py backend/app/api/routes_job_targets.py backend/tests/test_job_analysis_graph.py backend/tests/test_job_analysis_recovery.py backend/tests/test_job_target_tools.py
git commit -m "feat(targets): add recoverable job analysis"
```

---

### Task 4: Target list, requirement workbench, and project priorities

**Files:**
- Create: `frontend/src/features/jobTargets/jobTargetTypes.ts`
- Create: `frontend/src/features/jobTargets/jobTargetApi.ts`
- Create: `frontend/src/features/jobTargets/JobTargetPage.tsx`
- Create: `frontend/src/features/jobTargets/JobTargetList.tsx`
- Create: `frontend/src/features/jobTargets/JobTargetWorkspace.tsx`
- Create: `frontend/src/features/jobTargets/JobTargetOverview.tsx`
- Create: `frontend/src/features/jobTargets/RequirementWorkbench.tsx`
- Create: `frontend/src/features/jobTargets/ProjectPriorityPanel.tsx`
- Create: `frontend/src/features/jobTargets/JobAnalysisStatus.tsx`
- Create: `frontend/src/features/jobTargets/jobTargets.css`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/navigation/navigationItems.ts`
- Test: `frontend/src/features/jobTargets/JobTargetPage.test.tsx`
- Test: `frontend/src/features/jobTargets/RequirementWorkbench.test.tsx`
- Test: `frontend/src/features/jobTargets/JobAnalysisStatus.test.tsx`
- Modify test: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes Task 2/3 REST resources.
- Produces route `/targets` and target tabs `overview`, `requirements`, `deep-dive`, `review`.

- [x] **Step 1: Write UI behavior tests**

```tsx
it("keeps inferred requirements out of safe select-all", async () => {
  render(<RequirementWorkbench requirements={requirements} onDecide={onDecide} />);
  await user.click(screen.getByRole("button", { name: "选择可安全确认项" }));
  expect(screen.getByRole("checkbox", { name: /负责高并发服务/ })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: /可能需要带团队/ })).not.toBeChecked();
  expect(screen.getByText("1 条推断建议需要单独核对")).toBeVisible();
});

it("renders persisted long-task facts instead of an indefinite spinner", () => {
  render(<JobAnalysisStatus analysis={analysisFixture} />);
  expect(screen.getByText("正在分析项目相关性")).toBeVisible();
  expect(screen.getByText("已完成 4 / 7")).toBeVisible();
  expect(screen.getByText("已保存 12 条岗位要求")).toBeVisible();
  expect(screen.getByRole("button", { name: "暂停分析" })).toBeEnabled();
});
```

- [x] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run src/features/jobTargets/JobTargetPage.test.tsx src/features/jobTargets/RequirementWorkbench.test.tsx src/features/jobTargets/JobAnalysisStatus.test.tsx src/app/App.test.tsx
```

Expected: missing job-target feature modules and `/targets` route.

- [x] **Step 3: Implement typed API and route state**

Define discriminated unions:

```ts
export type RequirementPreparationStatus =
  | "reliable_evidence"
  | "needs_deep_dive"
  | "profile_incomplete"
  | "no_experience";

export type TargetDerivedStatus =
  | "requirements_pending"
  | "project_selection_pending"
  | "deep_dive_in_progress"
  | "high_risk_open"
  | "core_preparation_complete";
```

Use TanStack Query keys rooted at `["job-targets", workspaceId]`. Mutations invalidate the specific target and list; progress polling runs only for active persisted states.

- [x] **Step 4: Implement the workspace layout**

`JobTargetWorkspace` uses:

```tsx
<section className="job-target-workspace">
  <header className="job-target-workspace__header">{header}</header>
  <nav className="job-target-workspace__tabs">{tabs}</nav>
  <div className="job-target-workspace__content">{activeTab}</div>
</section>
```

CSS owns the available height:

```css
.job-target-workspace {
  min-height: 0;
  height: 100%;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
}

.job-target-workspace__content {
  min-height: 0;
  overflow: hidden;
}
```

Requirements use queue/detail on desktop and list/detail navigation on mobile. The document never becomes the workbench scroll owner.

- [x] **Step 5: Implement safe bulk confirmation and project selection**

The fixed action bar shows selected, confirmable, and excluded counts. Partial failure clears successful selections and retains failed selections. Project selection enforces one core and at most two supplementary projects before sending.

- [x] **Step 6: Verify targeted GREEN and TypeScript**

```bash
cd frontend && npm test -- --run src/features/jobTargets/JobTargetPage.test.tsx src/features/jobTargets/RequirementWorkbench.test.tsx src/features/jobTargets/JobAnalysisStatus.test.tsx src/app/App.test.tsx
cd frontend && npx tsc --noEmit
```

Expected: selected tests and TypeScript pass.

- [x] **Step 7: Commit the target workbench**

```bash
git add frontend/src/features/jobTargets frontend/src/app/layout/AppShell.tsx frontend/src/app/navigation/navigationItems.ts frontend/src/app/App.test.tsx
git commit -m "feat(targets): add job preparation workspace"
```

---

### Task 5: Bounded project deep-dive Graph and retry lifecycle

**Files:**
- Create: `backend/app/graphs/project_deep_dive.py`
- Modify: `backend/app/agents/job_target_contracts.py`
- Modify: `backend/app/agents/job_target_agents.py`
- Modify: `backend/app/agents/prompts/job_target_prompts.py`
- Modify: `backend/app/job_targets/repository.py`
- Modify: `backend/app/job_targets/service.py`
- Modify: `backend/app/job_targets/application.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/api/routes_job_targets.py`
- Test: `backend/tests/test_project_deep_dive_graph.py`
- Test: `backend/tests/test_project_deep_dive_api.py`
- Test: `backend/tests/test_project_deep_dive_retry.py`

**Interfaces:**
- Produces: `ProjectDeepDiveState`, `DeepDiveTurnResult`, `DeepDiveApplication`.
- Consumes Task 1 `prepare_for_message` and Task 3 scoped read tools.

- [x] **Step 1: Write state and retry tests**

```python
def test_deep_dive_state_contains_only_control_and_stable_refs():
    assert set(ProjectDeepDiveState.__annotations__) == {
        "job_target_id",
        "project_claim_id",
        "session_id",
        "execution_id",
        "current_stage",
        "current_question_id",
        "completed_stage_ids",
        "follow_up_ids",
        "waiting_for_input",
        "pause_requested",
        "end_requested",
    }


@pytest.mark.asyncio
async def test_retry_reuses_message_and_excludes_failed_partial_output(application):
    first = await application.answer("session-1", "我负责核心链路", idempotency_key="a1")
    await application.fail_execution(first.execution_id, partial="未完成的模型文本")
    retry = await application.retry(first.execution_id, idempotency_key="retry-1")
    messages = application.list_messages("session-1")
    assert [m.content for m in messages if m.role == "user"] == ["我负责核心链路"]
    assert retry.input_message_id == first.input_message_id
    assert retry.retry_of_execution_id == first.execution_id
    assert "未完成的模型文本" not in application.active_context("session-1")
```

- [x] **Step 2: Run RED**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_deep_dive_graph.py backend/tests/test_project_deep_dive_api.py backend/tests/test_project_deep_dive_retry.py -q
```

Expected: missing state, Graph, application methods, and routes.

- [x] **Step 3: Implement explicit bounded state and stages**

```python
class ProjectDeepDiveState(TypedDict, total=False):
    job_target_id: str
    project_claim_id: str
    session_id: str
    execution_id: str
    current_stage: Literal[
        "background",
        "role",
        "solution",
        "difficulty",
        "outcome",
        "tradeoff",
        "target_follow_up",
        "finished",
    ]
    current_question_id: str
    completed_stage_ids: tuple[str, ...]
    follow_up_ids: tuple[str, ...]
    waiting_for_input: bool
    pause_requested: bool
    end_requested: bool
```

The Graph receives `state_schema=ProjectDeepDiveState`. It permits at most one bounded follow-up for an incomplete core dimension before advancing, unless the user explicitly asks to continue the same topic.

- [x] **Step 4: Implement one main model call per answer**

```python
class DeepDiveTurnResult(BaseModel):
    answer_evaluation: AnswerEvaluation
    narrative_delta: list[NarrativeSectionDelta]
    target_findings: list[TargetFinding]
    gaps: list[GapSuggestion]
    next_question: NextQuestion | None
    stage_complete: bool
```

One invocation returns the full result. A single repair invocation is allowed only for schema-invalid output.

- [x] **Step 5: Implement message resolution endpoints**

```text
POST /api/job-targets/{target_id}/projects/{project_id}/deep-dives
GET  /api/job-targets/{target_id}/projects/{project_id}/deep-dives/current
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/messages
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/executions/{execution_id}/retry
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/messages/{message_id}/replace
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/messages/{message_id}/abandon
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/pause
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/resume
POST /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/terminate
GET  /api/job-targets/{target_id}/deep-dives/{deep_dive_id}/events
```

Normal send returns 409 while an unresolved input exists. Retry and replace resolve the specific message; no route accepts a model-supplied Workspace or scope.

- [x] **Step 6: Verify targeted GREEN**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_deep_dive_graph.py backend/tests/test_project_deep_dive_api.py backend/tests/test_project_deep_dive_retry.py backend/tests/test_agent_restart_v2.py -q
```

Expected: selected tests pass; restart restores current stage and unresolved action.

- [x] **Step 7: Commit the deep-dive runtime**

```bash
git add backend/app/graphs/project_deep_dive.py backend/app/agents/job_target_contracts.py backend/app/agents/job_target_agents.py backend/app/agents/prompts/job_target_prompts.py backend/app/job_targets backend/app/application/graph_factory.py backend/app/application/workspace_runtime.py backend/app/api/routes_job_targets.py backend/tests/test_project_deep_dive_graph.py backend/tests/test_project_deep_dive_api.py backend/tests/test_project_deep_dive_retry.py
git commit -m "feat(training): add recoverable project deep dives"
```

---

### Task 6: Project deep-dive Agent workspace

**Files:**
- Create: `frontend/src/features/jobTargets/DeepDiveWorkspace.tsx`
- Create: `frontend/src/features/jobTargets/DeepDiveContextPanel.tsx`
- Create: `frontend/src/features/jobTargets/DeepDiveSessionList.tsx`
- Create: `frontend/src/features/jobTargets/DeepDiveProcessCard.tsx`
- Modify: `frontend/src/features/jobTargets/JobTargetWorkspace.tsx`
- Modify: `frontend/src/features/jobTargets/jobTargetApi.ts`
- Modify: `frontend/src/features/jobTargets/jobTargetTypes.ts`
- Modify: `frontend/src/features/jobTargets/jobTargets.css`
- Test: `frontend/src/features/jobTargets/DeepDiveWorkspace.test.tsx`
- Test: `frontend/src/features/jobTargets/DeepDiveContextPanel.test.tsx`
- Test: `frontend/src/features/jobTargets/DeepDiveSessionList.test.tsx`

**Interfaces:**
- Consumes Task 5 deep-dive resources and SSE.
- Reuses: `AgentWorkspaceShell`, `AgentMessage`, `AgentProcessCard`, `AgentComposer`.

- [x] **Step 1: Write interaction and layout tests**

```tsx
it("shows one unresolved message with retry, replace, and abandon actions", () => {
  render(<DeepDiveWorkspace resource={failedResource} />);
  expect(screen.getAllByText("我负责核心链路")).toHaveLength(1);
  expect(screen.getByText("本次处理未完成")).toBeVisible();
  expect(screen.getByRole("button", { name: "按原内容重试" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "修改后重试" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "放弃并继续" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
});

it("does not send while the IME is composing", async () => {
  render(<DeepDiveWorkspace resource={idleResource} />);
  const textbox = screen.getByRole("textbox");
  fireEvent.compositionStart(textbox);
  fireEvent.keyDown(textbox, { key: "Enter", isComposing: true });
  expect(sendMessage).not.toHaveBeenCalled();
});
```

- [x] **Step 2: Run RED**

```bash
cd frontend && npm test -- --run src/features/jobTargets/DeepDiveWorkspace.test.tsx src/features/jobTargets/DeepDiveContextPanel.test.tsx src/features/jobTargets/DeepDiveSessionList.test.tsx
```

Expected: missing deep-dive UI modules.

- [x] **Step 3: Compose the shared Agent workspace**

```tsx
<AgentWorkspaceShell
  header={header}
  conversation={<DeepDiveConversation />}
  context={<DeepDiveContextPanel />}
  contextLabel="本次依据"
  storageKey="project-deep-dive-context-panel"
/>
```

Do not introduce an Agent-specific page shell. The message timeline uses shared time/Markdown/process components. The composer receives the persisted Execution snapshot and SSE overlay keyed by `sessionId + executionId`.

- [x] **Step 4: Implement process and recovery presentation**

One Execution renders at most one process card. Running shows stage and live elapsed time; completed folds to duration and saved-result counts; failed/stopped stays open with the exact recovery actions.

The right panel order is:

```text
本次参考范围
当前项目与阶段
项目讲解草稿
待处理建议
运行状态
技术详情（默认折叠）
```

Technical details include model, calls, Token, current/threshold context, estimated marker, and compaction status.

- [x] **Step 5: Implement responsive ownership**

At `>=1200px`, context width is `320px`; at `768-1199px`, it is a side panel; below `768px`, it is a bottom sheet or independent detail. The document does not scroll:

```css
.deep-dive-workspace {
  min-height: 0;
  height: 100%;
}

.deep-dive-workspace .agent-workspace-shell {
  min-height: 0;
  height: 100%;
}
```

- [x] **Step 6: Verify targeted GREEN and build**

```bash
cd frontend && npm test -- --run src/features/jobTargets/DeepDiveWorkspace.test.tsx src/features/jobTargets/DeepDiveContextPanel.test.tsx src/features/jobTargets/DeepDiveSessionList.test.tsx src/shared/agent/AgentComposer.test.tsx src/shared/agent/AgentMessage.test.tsx
cd frontend && npm run build
```

Expected: selected tests and production build pass.

- [x] **Step 7: Commit the training workspace**

```bash
git add frontend/src/features/jobTargets frontend/src/shared/agent
git commit -m "feat(training): add project deep-dive workspace"
```

---

### Task 7: Narrative proposals, gap actions, and project-question candidates

**Files:**
- Modify: `backend/app/job_targets/repository.py`
- Modify: `backend/app/job_targets/service.py`
- Modify: `backend/app/job_targets/application.py`
- Modify: `backend/app/profile/service.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/schemas/job_targets.py`
- Modify: `backend/app/api/routes_job_targets.py`
- Test: `backend/tests/test_project_narrative_proposals.py`
- Test: `backend/tests/test_project_gap_actions.py`
- Test: `backend/tests/test_project_question_candidates.py`
- Create: `frontend/src/features/jobTargets/NarrativeDiffPanel.tsx`
- Create: `frontend/src/features/jobTargets/ProjectQuestionCandidates.tsx`
- Modify: `frontend/src/features/jobTargets/DeepDiveContextPanel.tsx`
- Test: `frontend/src/features/jobTargets/NarrativeDiffPanel.test.tsx`
- Test: `frontend/src/features/jobTargets/ProjectQuestionCandidates.test.tsx`

**Interfaces:**
- Produces: section-level narrative proposal decisions.
- Produces: gap actions for Profile proposal, narrative continuation, question candidate, and target risk.
- Produces: `project_experience` question candidate metadata without direct publication.

- [x] **Step 1: Write backend tests for confirmation and ownership**

```python
def test_confirming_one_narrative_section_creates_a_new_project_owned_version(app):
    proposal = app.get_artifact("artifact-1")
    receipt = app.confirm_narrative_sections(
        proposal.id,
        section_ids=("solution",),
        expected_project_version=3,
        idempotency_key="confirm-solution-1",
    )
    assert receipt.confirmed_section_ids == ("solution",)
    assert app.profile_project_version("project-1") == 4
    assert app.get_artifact("artifact-1").pending_section_ids == ("outcome",)


def test_project_question_candidate_is_private_until_confirmed(app):
    candidate = app.generate_project_questions(
        "deep-dive-1", idempotency_key="questions-1"
    )[0]
    assert candidate.question_type == "project_experience"
    assert candidate.status == "review_pending"
    assert app.review_repository.list_active_questions("w1") == ()
```

- [x] **Step 2: Run RED**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_narrative_proposals.py backend/tests/test_project_gap_actions.py backend/tests/test_project_question_candidates.py -q
```

Expected: missing narrative confirmation, gap dispatch, and project-question metadata.

- [x] **Step 3: Implement section-level proposal confirmation**

Add deterministic service operations:

```python
def confirm_narrative_sections(
    self,
    artifact_id: str,
    *,
    section_ids: tuple[str, ...],
    edited_values: dict[str, str],
    expected_project_version: int,
    idempotency_key: str,
) -> NarrativeDecisionReceipt: ...
```

Confirmed common sections write a new Profile project/narrative version with source Session/Message IDs. Target-specific findings remain in Job Target tables.

- [x] **Step 4: Implement four gap dispatches**

```python
match gap.kind:
    case "profile":
        result = profile_service.create_conversation_proposal(...)
    case "expression":
        result = repository.create_narrative_artifact(...)
    case "knowledge":
        result = repository.create_project_question_candidate(...)
    case "experience":
        result = repository.create_target_risk(...)
```

No branch directly confirms Profile or publishes a question.

- [x] **Step 5: Extend question candidates with formal project metadata**

Persist:

```python
question_type: Literal["technical", "project_experience"]
project_claim_id: str | None
project_dimension: Literal[
    "background_role",
    "architecture_solution",
    "difficulty_problem_solving",
    "outcome",
    "tradeoff_failure_retrospective",
    "target_specific",
] | None
source_job_target_id: str | None
source_deep_dive_id: str | None
```

Deduplicate within the same project before creating a candidate. Reuse existing candidate confirmation/publication invariants.

- [x] **Step 6: Implement Diff and candidate review UI**

`NarrativeDiffPanel` displays confirmed/current/suggested sections and allows section checkboxes, edits, and safe bulk confirmation. `ProjectQuestionCandidates` groups by project dimension, shows duplicate resolution, and requires explicit confirmation before calling the existing publication flow.

- [x] **Step 7: Verify targeted GREEN**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_narrative_proposals.py backend/tests/test_project_gap_actions.py backend/tests/test_project_question_candidates.py backend/tests/test_profile_action_plans.py backend/tests/test_review_repository.py -q
cd frontend && npm test -- --run src/features/jobTargets/NarrativeDiffPanel.test.tsx src/features/jobTargets/ProjectQuestionCandidates.test.tsx
```

Expected: selected backend/frontend tests pass.

- [x] **Step 8: Commit project assets and candidates**

```bash
git add backend/app/job_targets backend/app/profile/service.py backend/app/review backend/app/schemas/job_targets.py backend/app/api/routes_job_targets.py backend/tests/test_project_narrative_proposals.py backend/tests/test_project_gap_actions.py backend/tests/test_project_question_candidates.py frontend/src/features/jobTargets
git commit -m "feat(training): confirm narratives and create project questions"
```

---

### Task 8: Project-question library, evaluation, and readiness projection

**Files:**
- Modify: `backend/app/agents/review_round_contracts.py`
- Modify: `backend/app/agents/review_round_agents.py`
- Modify: `backend/app/agents/prompts/review_round_prompts.py`
- Modify: `backend/app/graphs/review_round.py`
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/service.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/job_targets/service.py`
- Modify: `backend/app/job_targets/projection.py`
- Test: `backend/tests/test_project_question_review.py`
- Test: `backend/tests/test_job_target_readiness.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Modify: `frontend/src/features/review/QuestionLibrary.tsx`
- Modify: `frontend/src/features/review/QuestionCatalog.tsx`
- Modify: `frontend/src/features/review/ReviewConversation.tsx`
- Modify: `frontend/src/features/jobTargets/JobTargetOverview.tsx`
- Test: `frontend/src/features/review/QuestionCatalog.test.tsx`
- Test: `frontend/src/features/review/ReviewConversation.test.tsx`
- Test: `frontend/src/features/jobTargets/JobTargetOverview.test.tsx`

**Interfaces:**
- Consumes confirmed `project_experience` questions from Task 7.
- Produces four-dimensional evaluation and `pending/basic/stable` project mastery.
- Produces derived Job Target readiness without a stored percentage.

- [x] **Step 1: Write project-question evaluation tests**

```python
@pytest.mark.asyncio
async def test_project_answer_uses_project_contract_and_blocks_stable_on_conflict(review):
    result = await review.evaluate_project_answer(
        question_id="q-project-1",
        answer="我独立完成了全部架构",
        confirmed_project_context={"role": "协作完成核心模块"},
    )
    assert result.dimensions == {
        "factual_consistency": "conflict",
        "specificity": "basic",
        "structural_completeness": "basic",
        "follow_up_resilience": "pending",
    }
    assert result.mastery == "pending"
    assert result.conflict.requires_user_resolution is True


def test_readiness_requires_explicitly_accepted_must_have_risks(service):
    target = service.readiness("target-1")
    assert target.status == "high_risk_open"
    service.accept_risk("target-1", "risk-1", idempotency_key="accept-1")
    assert service.readiness("target-1").status == "core_preparation_complete"
```

- [x] **Step 2: Run RED**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_question_review.py backend/tests/test_job_target_readiness.py -q
```

Expected: project evaluation contract and readiness projection are absent.

- [x] **Step 3: Add project-specific evaluation without a new Runtime**

Select prompt/contract by `question_type`:

```python
if question.question_type == "project_experience":
    result = await agents.evaluate_project_answer(
        question=question,
        answer=answer,
        confirmed_project_context=project_context,
    )
else:
    result = await agents.evaluate_technical_answer(...)
```

Persist four dimensions and mastery values `pending`, `basic`, `stable`. An unresolved fact conflict forces `pending`.

- [x] **Step 4: Add conflict resolution**

Support:

```text
misspoke        → retain confirmed project facts
new_fact        → create Profile conversation proposal
contextualize   → create narrative context proposal
```

The Review Execution resumes after a deterministic choice receipt; it does not directly alter Profile.

- [x] **Step 5: Project-aware library and target entry points**

Question library hierarchy:

```text
项目经历题
→ 项目
→ 能力维度
→ 题目
```

Keep technical question grouping unchanged. From Target “复习任务”, start a round filtered to the target’s high-risk project question IDs.

- [x] **Step 6: Implement derived readiness**

```python
def derive_readiness(snapshot: JobTargetPreparationSnapshot) -> str:
    if snapshot.unconfirmed_requirement_count:
        return "requirements_pending"
    if snapshot.core_project_id is None:
        return "project_selection_pending"
    if snapshot.active_deep_dive:
        return "deep_dive_in_progress"
    if snapshot.unaccepted_must_have_risks or snapshot.untrained_high_risk_questions:
        return "high_risk_open"
    return "core_preparation_complete"
```

No match/readiness percentage is persisted or returned.

- [x] **Step 7: Verify targeted GREEN**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_project_question_review.py backend/tests/test_job_target_readiness.py backend/tests/test_review_async_answer.py -q
cd frontend && npm test -- --run src/features/review/QuestionCatalog.test.tsx src/features/review/ReviewConversation.test.tsx src/features/jobTargets/JobTargetOverview.test.tsx
```

Expected: selected tests pass; technical review behavior remains green.

- [x] **Step 8: Commit the review loop**

```bash
git add backend/app/agents/review_round_contracts.py backend/app/agents/review_round_agents.py backend/app/agents/prompts/review_round_prompts.py backend/app/graphs/review_round.py backend/app/review backend/app/job_targets backend/tests/test_project_question_review.py backend/tests/test_job_target_readiness.py frontend/src/features/review frontend/src/features/jobTargets/JobTargetOverview.tsx frontend/src/features/jobTargets/JobTargetOverview.test.tsx
git commit -m "feat(review): train and track project experience questions"
```

---

### Task 9: Cross-layer acceptance, recovery hardening, and stage documentation

**Files:**
- Create: `docs/verification/job-target-project-training.md`
- Create local only: `docs/learning/job-target-project-training/README.md`
- Create local only: `docs/learning/job-target-project-training/architecture.md`
- Create local only: `docs/learning/job-target-project-training/domain-model.md`
- Create local only: `docs/learning/job-target-project-training/runtime.md`
- Create local only: `docs/learning/job-target-project-training/frontend.md`
- Create local only: `docs/learning/job-target-project-training/testing.md`
- Create local only: `docs/learning/job-target-project-training/exercises.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify affected implementation/test files only when acceptance finds a concrete defect.

**Interfaces:**
- Verifies the complete accepted specification.
- Produces the final user guide, ownership pack, and closure evidence.

- [x] **Step 1: Run targeted cross-layer integration before broad regression**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests/test_job_target_api.py backend/tests/test_job_analysis_recovery.py backend/tests/test_project_deep_dive_retry.py backend/tests/test_project_question_review.py backend/tests/test_agent_restart_v2.py -q
cd frontend && npm test -- --run src/features/jobTargets src/features/review/QuestionCatalog.test.tsx src/features/review/ReviewConversation.test.tsx src/app/App.test.tsx
```

Expected: all selected integration tests pass.

- [x] **Step 2: Run the one planned full automated regression**

```bash
/Users/miracle778/Project/cyber-interview-agent-new/.venv/bin/python -m pytest backend/tests -q
cd frontend && npm test -- --run
cd frontend && npm run build
```

Expected: backend and frontend suites pass; build succeeds. Record exact counts and warnings in the verification document.

- [x] **Step 3: Perform one minimal browser happy path**

Use one disposable target:

```text
创建方向目标
→ 生成并确认两条要求
→ 选择核心项目
→ 开始深挖并回答一题
→ 停止
→ 刷新
→ 按原消息重试
→ 确认一个讲解章节
→ 生成并确认一条项目经历题
→ 完成一次项目题回答
```

Record Target, Session, Message, Execution, question IDs and screenshots in the local verification assets. Confirm only one user message exists after retry.

- [ ] **Step 4: Perform the complete browser acceptance matrix**

Widths: `390 / 768 / 1024 / 1200 / 1440`.

Scenarios:

```text
目标创建、归档、恢复、删除影响
JD 新版本和差异确认
岗位方向参考标识
逐项与安全批量确认
分析暂停、刷新、恢复、终止、失败项重试
画像更新后的过期与差异重分析
核心/补充项目限制
深挖跳过、暂停、恢复、提前整理
失败原消息重试、修改后重试、放弃
讲解章节 Diff 和部分确认
四类差距去向
项目题去重、确认入库、训练、冲突处理
准备状态与已接受风险
外部模型隐私提示和每次参考范围
北京时间、实时耗时、Token、上下文与压缩状态
页面高度、横向溢出、滚动所有权、键盘路径
```

Re-run only scenarios affected by concrete fixes.

- [x] **Step 5: Write verification and learning artifacts**

`docs/verification/job-target-project-training.md` becomes the final user guide with:

```text
启动方式
测试数据准备
完整用户路径
运行/恢复操作
安全与数据删除边界
自动测试证据
浏览器证据
已知成熟度边界
```

Generate the seven local learning files using the stage risk profile, and compare coverage with the R3 ownership pack.

- [x] **Step 6: Run final static/document gates**

```bash
git diff --check
rg -n "T[B]D|T[O]DO|feat\\(r[4]\\)|R[4] Agent" docs/superpowers/specs/2026-07-25-job-target-and-project-deep-dive-design.md docs/superpowers/architecture-decisions/2026-07-25-job-target-project-training-runtime-boundaries.md docs/superpowers/plans/2026-07-25-job-target-and-project-deep-dive.md
python3 scripts/check_stage_docs.py --verification docs/verification/job-target-project-training.md --learning docs/learning/job-target-project-training/ --plan docs/superpowers/plans/2026-07-25-job-target-and-project-deep-dive.md
```

Expected: `git diff --check` and documentation gate pass; placeholder/naming scan returns no matches.

- [x] **Step 7: Commit stage closure**

Only formal documents under `docs/superpowers/` are committed. `docs/verification/` and `docs/learning/` remain local and are explicitly synchronized after merge according to repository policy.

```bash
git add docs/superpowers/specs/2026-07-25-job-target-and-project-deep-dive-design.md docs/superpowers/architecture-decisions/2026-07-25-job-target-project-training-runtime-boundaries.md docs/superpowers/plans/2026-07-25-job-target-and-project-deep-dive.md
git commit -m "docs(targets): close job preparation delivery"
```

---

### Task 10: Real-model and interaction remediation after user acceptance

**Why this task exists:** The first Task 1–9 pass marked the job Agent and deep-dive
runtime complete while production still used deterministic extraction/questions and
several UI controls only changed local status. Real-page acceptance exposed the gap.

**Files:**
- Modify: `backend/app/agents/job_target_*`
- Modify: `backend/app/application/{graph_factory,workspace_runtime,execution_service}.py`
- Modify: `backend/app/job_targets/*`
- Modify: `backend/app/api/routes_job_targets.py`
- Modify: `frontend/src/features/jobTargets/*`
- Modify: `frontend/src/shared/agent/*`

- [x] **Step 1: Make JD-first creation the default**

Persist JD immediately, then use one structured `job_analysis` call to extract company,
role, seniority and atomic requirements. Preserve a manual no-JD path.

- [x] **Step 2: Wire real production Agents**

Create and inject `job_analysis` and `project_deep_dive` Agents through the Workspace
runtime. Keep deterministic behavior only for isolated tests without Agent bindings.

- [x] **Step 3: Separate Session and Execution controls**

Pause/resume/end control the deep-dive Session. Composer Stop cancels only the active
Execution. Failure and stop keep one unresolved user Message and retry creates a new
Execution against that Message.

- [x] **Step 4: Normalize API resources and runtime facts**

Return camelCase Message/Execution resources, Beijing-displayable timestamps, execution
duration inputs, real model usage, context usage and compaction state.

- [x] **Step 5: Correct the target and Agent workspaces**

Make overview summaries and steps navigable, add JD/manual mode selection, show safe
recognition placeholders, reuse the established Agent composer, and replace the empty
gray runtime panel with a structured status/summary/detail hierarchy.

- [x] **Step 6: Focused verification**

Run only the two current backend target tests, the target component test, TypeScript,
production build and one real browser critical path on the user’s local service.

---

## Plan Self-Review Checklist

Coverage audit:

| Spec sections | Implementation Tasks |
|---|---|
| 1–4 Product goal, ownership, scope | 1, 2, 4, 9 |
| 5 Target lifecycle | 2, 4, 9 |
| 6–8 JD, requirements, Profile versioning | 2, 3, 4 |
| 9 Project relevance and priority | 2, 3, 4 |
| 10–12 Deep dive, narrative, gaps | 5, 6, 7 |
| 13 Project experience questions | 7, 8 |
| 14 Message/Execution retry | 1, 5, 6, 9 |
| 15–17 State, Tool, privacy, recovery | 1, 3, 5, 6, 9 |
| 18 Information architecture and layout | 4, 6, 9 |
| 19 Readiness | 8, 9 |
| 20 Model roles and budgets | 1, 3, 5, 8 |
| 21–22 Acceptance and maturity | 9 |

No uncovered accepted requirement remains.

- [x] Every accepted spec section maps to at least one Task.
- [x] Domain ownership and deletion behavior are tested in Tasks 2, 7, and 9.
- [x] Job analysis recovery and no-repeat work items are tested in Task 3.
- [x] Message-to-Execution retry, replace, and abandon are tested in Tasks 1, 5, 6, and 9.
- [x] Project deep-dive state contains no domain documents or complete message history.
- [x] Project questions are a formal type and reuse Review Runtime without direct publication.
- [x] Profile writes, narrative writes, and question publication all require deterministic confirmation paths.
- [x] UI reuses shared Agent and workspace shells with explicit scroll ownership.
- [x] Model roles, privacy manifest, Token/context, UTC/Asia-Shanghai, and real-time duration are covered.
- [x] No implementation task uses stage-only naming in UI or commit messages.
- [x] Full regression and browser passes respect the project’s bounded test policy.
