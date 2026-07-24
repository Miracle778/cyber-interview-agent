# R3 Unified Personal Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing resume/evidence foundation into one readable, editable, multi-source personal profile that remains stable across resume versions and is the confirmed source for Profile Agent and later job-target consumers.

**Architecture:** Keep `profile_claims/profile_claim_versions` as the single profile truth and extend them with typed sources, relationships, presentation metadata, manual confirmed writes, and a grouped `UnifiedProfile` projection. Resume ingest, conversation extraction, and Agent inference create pending proposals; direct user card edits append confirmed versions. Existing Evidence, Action Plan, Tool, checkpoint, Event, and confirmed-profile boundaries remain in place.

**Tech Stack:** Python 3.12, FastAPI, SQLite migrations, Pydantic, LangGraph/LangChain, React 18, TypeScript, TanStack Query, Vitest/Testing Library.

## Global Constraints

- One Workspace has one unified personal profile; no profile copy per resume, Session, or job target.
- Only confirmed profile facts enter ordinary Agent answers and `ConfirmedProfileContext`.
- Direct user card saves are confirmed writes; resume, conversation, and Agent inference remain pending until confirmation.
- Agent roles receive no direct Claim write Tool; mutations continue through validated proposals, Action Plans, deterministic services, optimistic locks, idempotency receipts, and user confirmation.
- Resume Evidence, line numbers, and versions are secondary source details, not the profile home-page content.
- No abstract profile score, job matching, job-specific positioning, project deep-dive reasoning, OCR, general Time Travel, or free ReAct writes.
- Database migrations must not silently delete user data; the authorized local reset is a separate explicit command scoped to one Workspace.
- Do not modify `docs/my_idea.md`.
- Use focused tests per task. Run the complete backend/frontend regression only once after cross-layer integration and once at final acceptance if a fix after integration makes the second run necessary.

---

### Task 1: Extend the Profile Schema for Sources, Relations, and Presentation

**Status:** Completed on 2026-07-24.

**Files:**

- Create: `backend/app/db/migrations/runtime/029_r3_unified_profile.sql`
- Modify: `backend/app/profile/models.py`
- Test: `backend/tests/test_unified_profile_migration.py`
- Test: `backend/tests/test_runtime_migrations.py`

**Interfaces:**

- Consumes: existing `profile_claims`, `profile_claim_versions`, `profile_claim_proposals`, `agent_messages`, and Workspace ownership.
- Produces: `ProfileSourceKind`, `ProfileRelationType`, source-reference records, claim relations, and one Workspace presentation record used by all later tasks.

- [ ] **Step 1: Write the failing migration test**

```python
def test_unified_profile_schema_supports_sources_relations_and_presentation(
    migrated_connection,
) -> None:
    tables = {
        row["name"]
        for row in migrated_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "profile_claim_sources",
        "profile_claim_relations",
        "profile_presentations",
    } <= tables
    columns = {
        row["name"]
        for row in migrated_connection.execute(
            "PRAGMA table_info(profile_claim_proposals)"
        )
    }
    assert {"source_kind", "source_ref_json"} <= columns
```

- [ ] **Step 2: Run the migration test and verify RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_unified_profile_migration.py tests/test_runtime_migrations.py
```

Expected: failure because migration 029 and the three new tables do not exist.

- [ ] **Step 3: Add the migration**

The migration must:

```sql
ALTER TABLE profile_claim_proposals
    ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'resume_extraction'
    CHECK (source_kind IN (
        'resume_extraction', 'user_input', 'conversation', 'agent_inference'
    ));

ALTER TABLE profile_claim_proposals
    ADD COLUMN source_ref_json TEXT NOT NULL DEFAULT '{}'
    CHECK (json_valid(source_ref_json) AND json_type(source_ref_json) = 'object');

CREATE TABLE profile_claim_sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    claim_version_id TEXT NOT NULL
        REFERENCES profile_claim_versions(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK (source_kind IN (
        'resume_extraction', 'user_input', 'conversation', 'agent_inference'
    )),
    source_ref_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(source_ref_json) AND json_type(source_ref_json) = 'object'),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'source_deleted', 'superseded')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(claim_version_id, source_kind, source_ref_json)
);

CREATE TABLE profile_claim_relations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    from_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    to_claim_id TEXT NOT NULL REFERENCES profile_claims(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL
        CHECK (relation_type IN ('belongs_to', 'used_in', 'supported_by')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_claim_id, to_claim_id, relation_type),
    CHECK(from_claim_id <> to_claim_id)
);

CREATE TABLE profile_presentations (
    workspace_id TEXT PRIMARY KEY,
    summary_claim_id TEXT REFERENCES profile_claims(id) ON DELETE SET NULL,
    primary_direction_claim_id TEXT
        REFERENCES profile_claims(id) ON DELETE SET NULL,
    featured_claim_ids_json TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(featured_claim_ids_json)
            AND json_type(featured_claim_ids_json) = 'array'
        ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Rebuild `profile_claims` with its existing columns plus nullable `deleted_at`,
and expand the `claim_type` check to:

```text
skill, project, experience, education, certification, achievement, link,
summary, direction, highlight
```

Copy existing rows before renaming the rebuilt table. Recreate its indexes and foreign-key relationships in the same migration transaction.

- [ ] **Step 4: Add exact domain types**

Add to `backend/app/profile/models.py`:

```python
ProfileSourceKind: TypeAlias = Literal[
    "resume_extraction", "user_input", "conversation", "agent_inference"
]
ProfileRelationType: TypeAlias = Literal[
    "belongs_to", "used_in", "supported_by"
]

@dataclass(frozen=True, slots=True)
class ProfileClaimSourceRecord:
    id: str
    workspace_id: str
    claim_version_id: str
    source_kind: ProfileSourceKind
    source_ref: dict[str, object]
    status: str
    created_at: str

@dataclass(frozen=True, slots=True)
class ProfileClaimRelationRecord:
    id: str
    workspace_id: str
    from_claim_id: str
    to_claim_id: str
    relation_type: ProfileRelationType
    created_at: str

@dataclass(frozen=True, slots=True)
class ProfilePresentationRecord:
    workspace_id: str
    summary_claim_id: str | None
    primary_direction_claim_id: str | None
    featured_claim_ids: tuple[str, ...]
    version: int
    updated_at: str
```

Extend `ClaimType` and `ConfirmedClaimEntry` with the new categories and source summaries without renaming existing stable IDs.

- [ ] **Step 5: Run migration tests and verify GREEN**

Run the Step 2 command.

Expected: migration 029 applies from both a fresh database and the migration-028 baseline; existing Claim rows remain readable.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/migrations/runtime/029_r3_unified_profile.sql \
  backend/app/profile/models.py \
  backend/tests/test_unified_profile_migration.py \
  backend/tests/test_runtime_migrations.py
git commit -m "feat(profile): add unified profile source model"
```

### Task 2: Implement Repository Writes, Relations, Projection Inputs, and Safe Reset

**Status:** Completed on 2026-07-24.

**Files:**

- Modify: `backend/app/profile/repository.py`
- Modify: `backend/app/profile/storage.py`
- Create: `scripts/reset_profile_workspace.py`
- Test: `backend/tests/test_unified_profile_repository.py`
- Test: `backend/tests/test_profile_workspace_reset.py`

**Interfaces:**

- Consumes: Task 1 records and migration.
- Produces:
  - `append_confirmed_claim(command: AppendConfirmedClaimCommand) -> ProfileClaimVersionRecord`
  - `replace_claim_relations(workspace_id, claim_id, relations) -> tuple[ProfileClaimRelationRecord, ...]`
  - `get_profile_presentation(workspace_id) -> ProfilePresentationRecord`
  - `update_profile_presentation(command) -> ProfilePresentationRecord`
  - `profile_snapshot(workspace_id)` enriched with sources and relations.

- [ ] **Step 1: Write repository RED tests**

Cover:

```python
def test_direct_user_write_appends_confirmed_version_without_evidence(repository):
    version = repository.append_confirmed_claim(
        AppendConfirmedClaimCommand(
            workspace_id="w1",
            claim_type="project",
            value={"name": "Personal Project", "result": "released"},
            source_kind="user_input",
            source_ref={"commandId": "cmd-1"},
            expected_claim_version=0,
            idempotency_key="manual-project-1",
        )
    )
    assert version.status == "confirmed"
    assert version.evidence_ids == ()

def test_profile_relation_rejects_foreign_workspace(repository):
    with pytest.raises(ProfileClaimVersionConflict):
        repository.replace_claim_relations(
            "w1",
            claim_id="w1-project",
            relations=(("used_in", "w2-skill"),),
        )
```

Also test idempotent replay, stale expected version, relation replacement, featured order, source status, card-history restoration, and the grouped snapshot inputs.

- [ ] **Step 2: Run repository tests and verify RED**

```bash
cd backend
.venv/bin/python -m pytest -q tests/test_unified_profile_repository.py
```

Expected: failures for missing commands and repository methods.

- [ ] **Step 3: Implement confirmed card writes**

Add commands to `models.py` and repository methods with this transaction:

```python
with self._transaction():
    receipt = self._load_idempotency_receipt(...)
    if receipt is not None:
        return self.get_claim_version(receipt["claimVersionId"])
    claim = self._load_or_create_workspace_claim(...)
    self._assert_expected_claim_version(claim, command.expected_claim_version)
    version = self._append_confirmed_version(
        claim=claim,
        value=command.value,
        source=command.source_kind,
        evidence_ids=(),
    )
    self._insert_claim_source(
        workspace_id=command.workspace_id,
        claim_version_id=version.id,
        source_kind=command.source_kind,
        source_ref=command.source_ref,
    )
    self._store_idempotency_receipt(...)
    return version
```

Manual update and restore must supersede the previous current version and append a new confirmed version. They must never mutate `value_json` in place.

- [ ] **Step 4: Implement relations and presentation**

Validate both relation endpoints through `profile_claims.workspace_id`, reject self-relations, and replace only relations owned by the edited card. Presentation updates use expected `version`, preserve featured order, and reject unknown/non-confirmed featured Claim IDs.

- [ ] **Step 5: Implement safe reset dry-run and execution**

The script interface is:

```bash
python3 scripts/reset_profile_workspace.py \
  --database /absolute/runtime.db \
  --workspace-root /absolute/workspace \
  --workspace-id <exact-id> \
  --dry-run

python3 scripts/reset_profile_workspace.py \
  --database /absolute/runtime.db \
  --workspace-root /absolute/workspace \
  --workspace-id <exact-id> \
  --confirm "RESET PROFILE <exact-id>"
```

Dry-run prints Profile table counts, Profile Session counts, and material refs only. Execution must:

1. begin one immediate transaction;
2. resolve Profile material/version IDs for the exact Workspace;
3. delete Profile Action Plan, Assessment, Proposal, relation, source, Claim, Evidence, version, material, presentation, focus, receipt, and deletion-plan rows in foreign-key-safe order;
4. delete only `agent_sessions` whose Workspace matches and whose `graph_id` is `profile.manage` or whose `visibility='system'` Session ID matches a selected material version;
5. commit;
6. use `MaterialStorage.delete_ref(ref, remaining_references=0)` for now-unreferenced selected blob/text refs;
7. print preserved counts for review, curation, Workspace, and Provider tables.

The script refuses relative database/workspace paths, missing Workspace IDs, active Profile runs, a wrong confirmation phrase, and a Workspace mismatch.

- [ ] **Step 6: Verify reset isolation**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_unified_profile_repository.py \
  tests/test_profile_workspace_reset.py \
  tests/test_profile_repository.py
```

Expected: all pass; reset test proves another Workspace and R2 review rows are unchanged.

- [ ] **Step 7: Commit**

```bash
git add backend/app/profile/models.py backend/app/profile/repository.py \
  backend/app/profile/storage.py scripts/reset_profile_workspace.py \
  backend/tests/test_unified_profile_repository.py \
  backend/tests/test_profile_workspace_reset.py
git commit -m "feat(profile): add versioned profile card writes"
```

### Task 3: Build the Unified Profile Projection and Manual Card Service

**Status:** Completed on 2026-07-24.

**Files:**

- Create: `backend/app/profile/projection.py`
- Modify: `backend/app/profile/service.py`
- Modify: `backend/app/profile/errors.py`
- Test: `backend/tests/test_unified_profile_service.py`
- Test: `backend/tests/test_profile_context.py`

**Interfaces:**

- Consumes: Task 2 repository methods.
- Produces:
  - `ProfileService.unified_profile() -> UnifiedProfile`
  - `ProfileService.create_profile_card(...)`
  - `ProfileService.update_profile_card(...)`
  - `ProfileService.restore_profile_card_version(...)`
  - `ProfileService.delete_profile_card(...)`
  - exact category validators in `profile/projection.py`.

- [ ] **Step 1: Write service RED tests**

The tests must prove:

```python
profile = service.unified_profile()
assert profile.projects[0].title == "Cyber Interview Agent"
assert profile.projects[0].sources[0].label == "本人补充"
assert profile.skills[0].used_in[0].claim_id == profile.projects[0].claim_id
assert "项目缺少量化结果" in {
    item.message for item in profile.actionable_gaps
}
```

Also cover empty profile, manual no-resume creation, category validation, project-to-experience linkage, skill usage, featured order, summary/directions, direct confirmed edits, stale writes, history restore, logical delete, source-deleted labels, pending counts, and confirmed-profile inclusion without Evidence.

- [ ] **Step 2: Run service tests and verify RED**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_unified_profile_service.py \
  tests/test_profile_context.py
```

Expected: missing projection and manual service methods.

- [ ] **Step 3: Implement typed value validation**

`projection.py` defines strict category models:

```python
class ProjectValue(ProfileValueModel):
    name: str = Field(min_length=1, max_length=200)
    period: str | None = Field(default=None, max_length=100)
    background: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=500)
    responsibilities: list[str] = Field(default_factory=list, max_length=30)
    key_actions: list[str] = Field(default_factory=list, max_length=30)
    tech_stack: list[str] = Field(default_factory=list, max_length=50)
    results: list[str] = Field(default_factory=list, max_length=30)
```

Define equivalent bounded models for skill, experience, education, certification, achievement, and link. Unknown fields are rejected for manual edits; ingest normalization maps provider aliases before validation.

- [ ] **Step 4: Implement the grouped projection**

`unified_profile()`:

1. loads current confirmed snapshot, sources, relations, presentation, and pending Proposal counts;
2. groups facts into stable sections;
3. resolves project/work/education links and skill usage;
4. includes only a lightweight source label and source ID, never Evidence text;
5. derives actionable gaps using deterministic missing-field rules;
6. returns `is_usable=True` once at least one confirmed skill, project, experience, education, certification, or achievement exists.

Gap rules are exact:

```python
if project.results == []:
    add_gap(project.id, "项目缺少结果或量化成果")
if experience.period is None:
    add_gap(experience.id, "工作经历缺少起止时间")
if project.role is None:
    add_gap(project.id, "项目缺少你的角色或职责")
```

Do not calculate a numeric score.

- [ ] **Step 5: Implement manual card service operations**

Validate Workspace ownership, category value, relation targets, expected version, and idempotency key. Use `source_kind="user_input"` and `source_ref={"commandId": command_id}`. A manual save is confirmed immediately and emits only safe IDs/category/status in the product Event.

- [ ] **Step 6: Keep confirmed-profile safe and broadened**

Extend allowed categories to certification and achievement. A confirmed manual fact with zero Evidence remains visible unless its value contains a sensitive field. Pending Proposal, deleted card, and Agent inference pending remain excluded.

- [ ] **Step 7: Run service/context tests and verify GREEN**

Run the Step 2 command.

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/profile/projection.py backend/app/profile/service.py \
  backend/app/profile/errors.py backend/tests/test_unified_profile_service.py \
  backend/tests/test_profile_context.py
git commit -m "feat(profile): project an editable unified profile"
```

### Task 4: Convert Resume Ingest into Incremental Multi-Source Proposals

**Status:** Completed on 2026-07-24.

**Files:**

- Modify: `backend/app/agents/profile_contracts.py`
- Modify: `backend/app/agents/prompts/profile_prompts.py`
- Modify: `backend/app/graphs/profile_ingest.py`
- Modify: `backend/app/profile/repository.py`
- Test: `backend/tests/test_profile_ingest_merge.py`
- Test: `backend/tests/test_profile_agents.py`
- Test: `backend/tests/test_profile_ingest_graph.py`

**Interfaces:**

- Consumes: confirmed profile snapshot, typed profile values, source-aware Proposal creation.
- Produces: incremental create/update/conflict/source-link Proposals from a new resume version.

- [ ] **Step 1: Write incremental-ingest RED tests**

Cover:

```python
assert ingest(existing_skill_same_value).new_proposals == 0
assert ingest(existing_skill_same_value).new_source_links == 1
assert ingest(existing_project_changed_result).proposal_type == "update"
assert ingest(resume_missing_old_claim).confirmed_claims_removed == 0
assert ingest(resume_missing_old_claim).missing_source_gaps == 1
assert confirmed_snapshot_before == confirmed_snapshot_after_ingest
```

Also verify richer project fields, certification, achievement, duplicate multi-resume support, conflict preservation, exact Evidence ownership, and no automatic removal.

- [ ] **Step 2: Run ingest tests and verify RED**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_profile_ingest_merge.py \
  tests/test_profile_agents.py \
  tests/test_profile_ingest_graph.py
```

Expected: current ingest emits only create proposals and old project fields.

- [ ] **Step 3: Extend extraction contracts**

`ClaimCategory` becomes:

```python
Literal[
    "skill", "project", "experience", "education",
    "certification", "achievement", "link",
]
```

The extraction input includes a bounded confirmed snapshot with Claim IDs, type, canonical value, version, and source summary. Output retains `target_claim_id/base_claim_version_id` so the server can validate create versus update.

- [ ] **Step 4: Update prompt and deterministic normalizer**

Prompt version increments and explicitly distinguishes:

- direct facts from Evidence;
- inferred capability candidates with `source_kind="agent_inference"`;
- create versus update against supplied confirmed Claim IDs;
- no deletion when a new resume omits an old fact.

The server canonicalizer, not the model, decides exact duplicate/source-link behavior.

- [ ] **Step 5: Implement incremental reducer**

For each validated candidate:

```text
canonical exact match → attach resume source to existing current version
same logical identity, changed value → pending update proposal
new logical identity → pending create proposal
conflicting current value → pending update + conflict edge
missing from new resume → optional review reminder, never delete
```

All proposals store `source_kind="resume_extraction"` and:

```json
{
  "materialVersionId": "<id>",
  "evidenceIds": ["<id>"]
}
```

- [ ] **Step 6: Run ingest tests and verify GREEN**

Run the Step 2 command.

Expected: all pass; confirmed profile is unchanged until decisions.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/profile_contracts.py \
  backend/app/agents/prompts/profile_prompts.py \
  backend/app/graphs/profile_ingest.py backend/app/profile/repository.py \
  backend/tests/test_profile_ingest_merge.py backend/tests/test_profile_agents.py \
  backend/tests/test_profile_ingest_graph.py
git commit -m "feat(profile): merge resume facts into profile proposals"
```

### Task 5: Expose Unified Profile, Manual Editing, History, and Sources APIs

**Status:** Completed on 2026-07-24.

**Files:**

- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Test: `backend/tests/test_unified_profile_api.py`
- Test: `backend/tests/test_profile_claim_api.py`

**Interfaces:**

- Consumes: Task 3 service.
- Produces:

```text
GET    /api/workspaces/{workspaceId}/profile
POST   /api/workspaces/{workspaceId}/profile/cards
PATCH  /api/profile/cards/{claimId}
DELETE /api/profile/cards/{claimId}
GET    /api/profile/cards/{claimId}/versions
POST   /api/profile/cards/{claimId}/restore
PATCH  /api/workspaces/{workspaceId}/profile/presentation
GET    /api/profile/cards/{claimId}/sources
```

- [ ] **Step 1: Write API RED tests**

Test empty profile without materials, manual project creation, edit, stale 409, idempotent replay, relation validation, delete, history, restore, presentation ordering, source listing, pending counts, camelCase resources, Workspace isolation, and no raw Evidence in the unified response.

- [ ] **Step 2: Run API tests and verify RED**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_unified_profile_api.py \
  tests/test_profile_claim_api.py
```

Expected: unified-profile endpoints return 404.

- [ ] **Step 3: Define exact resource schemas**

Core card command:

```python
class ProfileCardCommand(AgentModel):
    workspace_id: str
    category: Literal[
        "skill", "project", "experience", "education",
        "certification", "achievement", "link",
        "summary", "direction", "highlight",
    ]
    value: dict[str, Any]
    expected_version: int = Field(ge=0)
    relations: list[ProfileRelationCommand] = Field(default_factory=list, max_length=100)
```

Unified response contains identity, highlights, grouped card lists, actionable gaps, pending summary, and no `excerpt`, `sanitizedText`, `storageRef`, `textRef`, or raw message content.

- [ ] **Step 4: Implement routes and error mapping**

All writes require `Idempotency-Key`. Stale versions return 409 with stable `profile_claim_version_conflict`. Foreign Workspace resources return 404. Direct card writes do not create Agent Sessions or Executions.

- [ ] **Step 5: Run API tests and verify GREEN**

Run the Step 2 command.

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/profile.py backend/app/api/routes_profile.py \
  backend/tests/test_unified_profile_api.py backend/tests/test_profile_claim_api.py
git commit -m "feat(profile): expose unified profile card APIs"
```

### Task 6: Build “我的画像” and Card Editing

**Status:** Completed on 2026-07-24.

**Files:**

- Create: `frontend/src/features/profile/UnifiedProfileOverview.tsx`
- Create: `frontend/src/features/profile/ProfileCardEditor.tsx`
- Create: `frontend/src/features/profile/ProfileSourceBadge.tsx`
- Create: `frontend/src/features/profile/ProfileActionableGaps.tsx`
- Modify: `frontend/src/features/profile/profileTypes.ts`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/UnifiedProfileOverview.test.tsx`
- Test: `frontend/src/features/profile/ProfileCardEditor.test.tsx`

**Interfaces:**

- Consumes: Task 5 API.
- Produces: default “我的画像” page, empty/manual start, reading-first cards, card editor, source chips, and action-oriented gaps.

- [ ] **Step 1: Write frontend RED tests**

Cover:

- empty profile offers “上传简历” and “从空白开始”;
- first screen answers identity/directions/highlights/experience/projects/skills;
- no generic “简历片段”, Claim, Evidence, snake_case, null, or numeric score;
- cards show “来自简历 v2”, “本人补充”, or “系统归纳”;
- manual card save updates the page without a second confirmation;
- stale save preserves input and offers refresh;
- project editor contains name, period, background, role, responsibilities, key actions, tech stack, and results;
- skill card displays used-in relations without inferred proficiency;
- keyboard and 390 px layout remain usable.

- [ ] **Step 2: Run UI tests and verify RED**

```bash
cd frontend
npm test -- --run \
  src/features/profile/UnifiedProfileOverview.test.tsx \
  src/features/profile/ProfileCardEditor.test.tsx
```

Expected: missing components/API methods.

- [ ] **Step 3: Add frontend types and API functions**

Define discriminated Profile cards and:

```typescript
export function getUnifiedProfile(workspaceId: string, signal?: AbortSignal)
export function createProfileCard(workspaceId: string, input: ProfileCardInput)
export function updateProfileCard(workspaceId: string, card: ProfileCard, input: ProfileCardInput)
export function restoreProfileCardVersion(workspaceId: string, claimId: string, versionId: string)
export function updateProfilePresentation(workspaceId: string, input: ProfilePresentationInput)
```

- [ ] **Step 4: Implement reading-first overview**

Render sections in this order:

```text
概况与能力方向
代表性亮点
工作经历
项目经历
核心技能
教育、认证与成果
待完善
```

Only show an editor after an explicit add/edit action. Source details open via “查看依据”; line numbers never render on the default page.

- [ ] **Step 5: Implement card editors**

Use category-specific fields, not a raw JSON editor. Save sends expected version and one stable idempotency key per user submission. On success invalidate `["unified-profile", workspaceId]`; on 409 preserve the draft and show a compare/refresh action.

- [ ] **Step 6: Run UI tests and TypeScript**

```bash
cd frontend
npm test -- --run \
  src/features/profile/UnifiedProfileOverview.test.tsx \
  src/features/profile/ProfileCardEditor.test.tsx
npx tsc --noEmit
```

Expected: all pass, zero TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/profile/UnifiedProfileOverview.tsx \
  frontend/src/features/profile/ProfileCardEditor.tsx \
  frontend/src/features/profile/ProfileSourceBadge.tsx \
  frontend/src/features/profile/ProfileActionableGaps.tsx \
  frontend/src/features/profile/profileTypes.ts \
  frontend/src/features/profile/profileApi.ts \
  frontend/src/features/profile/ProfilePage.tsx \
  frontend/src/app/global.css \
  frontend/src/features/profile/UnifiedProfileOverview.test.tsx \
  frontend/src/features/profile/ProfileCardEditor.test.tsx
git commit -m "feat(profile): add the unified profile workspace"
```

### Task 7: Reframe Pending Review and Resume Sources

**Status:** Completed on 2026-07-24.

**Files:**

- Create: `frontend/src/features/profile/ProfilePendingReview.tsx`
- Modify: `frontend/src/features/profile/ClaimReview.tsx`
- Modify: `frontend/src/features/profile/ResumeVersions.tsx`
- Modify: `frontend/src/features/profile/EvidenceDetail.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfilePendingReview.test.tsx`
- Test: `frontend/src/features/profile/ResumeVersions.test.tsx`

**Interfaces:**

- Consumes: existing claim decision and material/version APIs plus Task 6 navigation.
- Produces: four user-task tabs: “我的画像 / 待确认 / 简历与来源 / 画像助手”.

- [ ] **Step 1: Write navigation/review RED tests**

Verify default tab, plain-language proposal groups, source badges, accept/edit/reject, explicit batch selection, conflict copy, “查看依据” navigation, source details hidden by default, processing recovery, and no technical vocabulary.

- [ ] **Step 2: Run tests and verify RED**

```bash
cd frontend
npm test -- --run \
  src/features/profile/ProfilePendingReview.test.tsx \
  src/features/profile/ResumeVersions.test.tsx \
  src/features/profile/ProfilePage.test.tsx
```

Expected: old navigation and review copy fail.

- [ ] **Step 3: Implement pending-review facade**

Group proposals by:

```text
来自简历的新信息
根据经历归纳出的能力
对话中整理出的补充
需要核对的冲突
```

Reuse decision mutations and Diff behavior from `ClaimReview`; remove Claim/Evidence/internal-state wording from visible text.

- [ ] **Step 4: Reframe sources**

Rename the page and headings to “简历与来源”. Keep version, retry, archive, delete, and exact Evidence detail. The list shows semantic content titles; page/line/paragraph positions only appear inside source detail or after “查看依据”.

- [ ] **Step 5: Run tests and TypeScript**

Run the Step 2 command and `npx tsc --noEmit`.

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/profile/ProfilePendingReview.tsx \
  frontend/src/features/profile/ClaimReview.tsx \
  frontend/src/features/profile/ResumeVersions.tsx \
  frontend/src/features/profile/EvidenceDetail.tsx \
  frontend/src/features/profile/ProfilePage.tsx \
  frontend/src/app/global.css \
  frontend/src/features/profile/ProfilePendingReview.test.tsx \
  frontend/src/features/profile/ResumeVersions.test.tsx \
  frontend/src/features/profile/ProfilePage.test.tsx
git commit -m "feat(profile): organize review and sources around user tasks"
```

### Task 8: Turn Profile Conversation into a Confirmed-Profile Improvement Loop

**Status:** Completed on 2026-07-24.

**Files:**

- Modify: `backend/app/agents/profile_contracts.py`
- Modify: `backend/app/agents/prompts/profile_prompts.py`
- Modify: `backend/app/graphs/profile_manage.py`
- Modify: `backend/app/tools/profile_tools.py`
- Modify: `backend/app/profile/service.py`
- Modify: `frontend/src/features/profile/ProfileAgentWorkspace.tsx`
- Modify: `frontend/src/features/profile/ProfileConversation.tsx`
- Create: `frontend/src/features/profile/ProfileContextScope.tsx`
- Test: `backend/tests/test_profile_conversation_proposals.py`
- Test: `backend/tests/test_profile_chat_tool_loop.py`
- Test: `frontend/src/features/profile/ProfileAgentWorkspace.test.tsx`

**Interfaces:**

- Consumes: confirmed unified profile projection and source-aware Proposal API.
- Produces: ordinary confirmed-only chat, review-mode pending explanation, visible context scope, and conversation-to-pending-profile-update.

- [ ] **Step 1: Write backend conversation RED tests**

Prove:

- ordinary chat input contains confirmed cards only;
- pending resume and conversation proposals are absent;
- review mode can read only the selected Proposal and source;
- user statements do not mutate the profile;
- an explicit “整理成画像更新建议” produces `source_kind="conversation"` pending proposals referencing the formal user message ID;
- tool scope excludes deselected categories and sensitive fields.

- [ ] **Step 2: Run backend tests and verify RED**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_profile_conversation_proposals.py \
  tests/test_profile_chat_tool_loop.py \
  tests/test_profile_manage_graph.py
```

Expected: conversation proposal contract/context scope missing.

- [ ] **Step 3: Implement bounded conversation proposal output**

Add a strict `ProfileConversationProposalOutput` with the same typed category values as Task 3, `source_kind="conversation"`, and no write Tool. The graph persists validated pending proposals after the model returns; it never appends a confirmed version.

- [ ] **Step 4: Implement context scope**

The request carries selected Claim IDs/categories. The server intersects them with confirmed current Workspace facts and sensitive exclusions. Review mode requires one selected Proposal ID and returns only its bounded safe source context.

- [ ] **Step 5: Write and run frontend scope tests**

The Agent workspace permanently displays current scope (“正在使用：技能、项目经历”), allows expanding and deselecting cards, distinguishes a chat answer from a pending update card, and routes confirmation to “待确认”.

```bash
cd frontend
npm test -- --run src/features/profile/ProfileAgentWorkspace.test.tsx
npx tsc --noEmit
```

Expected: all pass.

- [ ] **Step 6: Run backend tests and verify GREEN**

Run the Step 2 command.

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/profile_contracts.py \
  backend/app/agents/prompts/profile_prompts.py \
  backend/app/graphs/profile_manage.py backend/app/tools/profile_tools.py \
  backend/app/profile/service.py \
  backend/tests/test_profile_conversation_proposals.py \
  backend/tests/test_profile_chat_tool_loop.py \
  frontend/src/features/profile/ProfileAgentWorkspace.tsx \
  frontend/src/features/profile/ProfileConversation.tsx \
  frontend/src/features/profile/ProfileContextScope.tsx \
  frontend/src/features/profile/ProfileAgentWorkspace.test.tsx
git commit -m "feat(profile): turn conversations into confirmed profile improvements"
```

### Task 9: Integrate, Reset the Authorized Test Profile, and Accept the Product

**Status:** Completed on 2026-07-24.

**Files:**

- Create: `frontend/src/features/profile/UnifiedProfileFlow.test.tsx`
- Update: `docs/verification/r3-personal-profile-agent.md`
- Update: `docs/learning/r3-personal-profile-agent/overview.md`
- Update: `docs/learning/r3-personal-profile-agent/architecture.md`
- Update: `docs/learning/r3-personal-profile-agent/code-walkthrough.md`
- Update: `docs/learning/r3-personal-profile-agent/failure-journal.md`
- Update: `docs/learning/r3-personal-profile-agent/interview-questions.md`
- Update: `docs/learning/r3-personal-profile-agent/presentation-script.md`
- Update: `docs/learning/r3-personal-profile-agent/exercises.md`
- Update: `task_plan.md`
- Update: `findings.md`
- Update: `progress.md`

**Interfaces:**

- Consumes: Tasks 1–8.
- Produces: complete cross-layer acceptance, a clean local Profile dataset, current verification/learning artifacts, and the new R3 product baseline.

- [ ] **Step 1: Add the cross-layer frontend flow**

The test covers:

```text
empty profile
→ manual start
→ manual confirmed project
→ upload resume
→ pending proposal
→ accept proposal
→ unified overview refresh
→ source detail
→ conversation update proposal
→ accept
→ confirmed-only Agent scope
```

It also asserts that pending content never appears in confirmed overview or ordinary Agent context.

- [ ] **Step 2: Run the focused cross-layer suites**

```bash
cd backend
.venv/bin/python -m pytest -q \
  tests/test_unified_profile_migration.py \
  tests/test_unified_profile_repository.py \
  tests/test_unified_profile_service.py \
  tests/test_profile_ingest_merge.py \
  tests/test_unified_profile_api.py \
  tests/test_profile_conversation_proposals.py \
  tests/test_profile_workspace_reset.py

cd ../frontend
npm test -- --run \
  src/features/profile/UnifiedProfileFlow.test.tsx \
  src/features/profile/UnifiedProfileOverview.test.tsx \
  src/features/profile/ProfileCardEditor.test.tsx \
  src/features/profile/ProfilePendingReview.test.tsx \
  src/features/profile/ProfileAgentWorkspace.test.tsx
```

Expected: all pass.

- [ ] **Step 3: Run one complete integration regression**

```bash
cd backend
.venv/bin/python -m pytest -q

cd ../frontend
npm test -- --run
npx tsc --noEmit
npm run build
```

Expected: backend and frontend suites pass, zero TypeScript errors, production build succeeds. Record exact counts in verification.

- [ ] **Step 4: Dry-run and execute the authorized local reset**

First resolve the exact current Workspace ID and absolute runtime paths with read-only settings/runtime queries. Run the Task 2 reset script with `--dry-run`, verify only Profile data is selected, then run with the exact confirmation phrase.

After execution verify:

```text
profile materials/claims/proposals/relations/sessions = 0
review questions/curation sessions/review rounds = unchanged
workspace/provider/model bindings = unchanged
selected private profile files = removed
```

- [x] **Step 5: Complete the 12-scenario browser acceptance**

At 1440 and 390 px, verify every acceptance criterion in the correction spec. Also inspect 768 and 1024 px for overflow and task reachability. Capture only redacted screenshots and IDs; never store resume content or Provider payloads.

- [ ] **Step 6: Update verification, learning, and root status**

Document product status, maturity boundary, ownership status, next product task, and non-blocking exercise. The verification guide must explain the four pages, source meanings, direct edit confirmation, pending boundaries, source deletion, Agent scope, and reset evidence.

- [ ] **Step 7: Run the documentation gate**

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r3-personal-profile-agent.md \
  --learning docs/learning/r3-personal-profile-agent/ \
  --plan docs/superpowers/plans/2026-07-24-r3-unified-personal-profile.md
```

Expected: passed.

- [ ] **Step 8: Final reviewer gate**

Compare the code and browser evidence against all 12 correction-spec criteria. Confirm:

- no raw Evidence on profile home;
- no pending content in ordinary Agent/downstream context;
- manual facts work without a resume;
- no direct Agent write path;
- no numeric profile score;
- current test Profile data is clean;
- unrelated R2 data is intact.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/profile/UnifiedProfileFlow.test.tsx \
  docs/superpowers/specs/2026-07-24-r3-unified-personal-profile-correction.md \
  docs/superpowers/architecture-decisions/2026-07-24-unified-profile-and-source-model.md \
  docs/superpowers/plans/2026-07-24-r3-unified-personal-profile.md \
  task_plan.md findings.md progress.md
git commit -m "docs(profile): close unified profile product correction"
```

---

## Self-Review

### Spec coverage

- One Workspace/one profile: Tasks 1–3.
- Resume, user, conversation, inference sources: Tasks 1–4 and 8.
- Direct edit confirmation versus pending suggestions: Tasks 2–5.
- Fixed sections, project depth, skills usage, card history: Tasks 2–6.
- Multi-resume incremental behavior: Task 4.
- Four user-task pages and secondary source detail: Tasks 6–7.
- Confirmed-only Agent and visible scope: Task 8.
- Safe local reset and unrelated-data isolation: Tasks 2 and 9.
- Twelve acceptance criteria and responsive verification: Task 9.

### Placeholder scan

The plan contains no TBD/TODO markers, undefined “appropriate handling”, or references to unspecified tests. Exact new interfaces, paths, commands, states, and validation rules are defined in their producing tasks.

### Type consistency

- Task 1 produces source/relation/presentation records consumed by Task 2.
- Task 2 produces repository methods consumed by Task 3.
- Task 3 produces `UnifiedProfile` and manual service operations consumed by Task 5.
- Task 4 uses the same source kinds and typed values.
- Task 5 API resources map directly to Task 6 TypeScript types.
- Tasks 7–8 reuse the same Proposal and confirmed-profile boundaries.

## Execution Choice

Repository collaboration rules prefer one Agent owning a cross-layer slice end to end and prohibit unnecessary subagents. Execute this plan inline with `superpowers:executing-plans`, using review checkpoints after Tasks 3, 6, and 8. Do not dispatch subagents unless the user later explicitly changes that decision.
