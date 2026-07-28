# 简历单版本永久删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为个人画像增加安全的简历单版本永久删除，同时保留整份简历删除能力。

**Architecture:** 复用现有删除计划、影响预检、乐观锁和 Item Receipt，将删除计划扩展为 `material` / `material_version` 两种目标。版本删除的清理影响只计算目标版本 Evidence，但安全门禁使用 Workspace 待确认总数：任一待确认 Proposal 存在时，预检与执行阶段都硬阻断所有版本删除。前端增加独立的版本删除弹窗与当前版本替换选择。

**Tech Stack:** FastAPI、Pydantic、SQLite migration、Python domain service/repository、React、TypeScript、TanStack Query、Vitest。

## Global Constraints

- Workspace 存在任意 `pending` Claim Proposal 时，所有版本都禁止预检和执行。
- 不根据 Proposal 当前是否直接引用目标版本判断安全；待确认信息处理完成后才能恢复版本删除。
- 当前版本删除必须选择同材料的剩余版本作为替代。
- 唯一版本只能使用整份简历删除。
- 删除只清理目标版本及其 Evidence，不影响其他版本。
- 所有执行使用删除计划、重新预检、乐观锁和幂等键。
- 现有整份简历删除接口和行为保持兼容。

---

### Task 1: 扩展删除计划与版本删除领域服务

**Files:**
- Create: `backend/app/db/migrations/runtime/036_profile_material_version_deletion.sql`
- Modify: `backend/app/profile/models.py`
- Modify: `backend/app/profile/errors.py`
- Modify: `backend/app/profile/repository.py`
- Modify: `backend/app/profile/service.py`
- Test: `backend/tests/test_profile_claim_service.py`
- Test: `backend/tests/test_runtime_migrations.py`

**Interfaces:**
- Produces: `ProfileService.preview_material_version_deletion(version_id, expected_version, idempotency_key)`
- Produces: `ProfileService.permanently_delete_material_version(version_id, deletion_plan_id, expected_version, replacement_version_id, claim_choices, active_publication_action, idempotency_key)`
- Produces: deletion-plan impact keys `targetKind`, `targetVersionId`, `pendingProposalIds`, `replacementCandidates`

- [x] **Step 1: Write failing repository/service tests**

Add focused tests that create a material with two versions and prove:

```python
plan = service.preview_material_version_deletion(
    old_version.id,
    expected_version=material.version,
    idempotency_key="preview-version-delete-1",
)
assert plan.impact["versionIds"] == [old_version.id]
assert newer_version.id not in plan.impact["versionIds"]
```

Add separate failing tests for:

- pending Proposal belongs to the target, another version, or another material → `ProfileMaterialVersionHasPendingProposals`;
- preview 后新增任意 pending Proposal → execution 再次返回同一稳定错误码；
- deleting current version without a valid replacement → `ProfileDeletionPlanConflict`;
- deleting the only version → `ProfileDeletionPlanConflict`;
- successful deletion tombstones only target Evidence and switches current version;
- stale material version or changed impact → conflict;
- idempotent replay returns the same result.

- [x] **Step 2: Verify RED**

Run:

```bash
cd backend
uv run pytest -q \
  tests/test_profile_claim_service.py -k "material_version_deletion or pending_proposals" \
  tests/test_runtime_migrations.py -k "version_deletion"
```

Expected: failures because migration, exception and service methods do not exist.

- [x] **Step 3: Add additive migration**

Extend `profile_deletion_plans` with nullable `target_version_id` and a checked `target_kind` defaulting to `material`. Add `profile_material_versions.deleted_at` so tombstone rows remain auditable but disappear from normal version lists. Add indexes for version-target plans and live material versions. Existing rows remain material deletion plans.

- [x] **Step 4: Implement target-version impact calculation**

Add `build_material_version_deletion_impact(version_id, workspace_id)` that:

- resolves the version and owning material inside the Workspace;
- selects only non-tombstoned Evidence from that version;
- computes affected Claims and remaining Evidence using the existing material-impact shape;
- records all pending Proposal IDs in the Workspace as a conservative deletion gate;
- records remaining replacement versions;
- records only the target version artifact refs.

- [x] **Step 5: Implement preview and execution guards**

Preview and execution must both reject:

- any Workspace pending Proposal;
- only one remaining material version;
- stale material aggregate version;
- missing or cross-material replacement;
- deleting current version without replacement;
- changed Evidence/Claim/publication impact.

Execution tombstones target Evidence, clears only target version artifact refs/file name, switches current version when required, and preserves the tombstone version row for audit.

- [x] **Step 6: Verify GREEN**

Run the RED command again plus:

```bash
cd backend
uv run pytest -q tests/test_profile_claim_service.py tests/test_runtime_migrations.py
```

Expected: all selected tests pass.

### Task 2: 暴露版本删除 API

**Files:**
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Test: `backend/tests/test_profile_claim_api.py`

**Interfaces:**
- Produces: `POST /api/profile/material-versions/{versionId}/deletion-preview`
- Produces: `POST /api/profile/material-versions/{versionId}/permanent-delete`
- Consumes: Task 1 service methods and deletion-plan result types.

- [x] **Step 1: Write failing API tests**

Cover:

```python
preview = await client.post(
    f"/api/profile/material-versions/{version_id}/deletion-preview",
    json={"workspaceId": "w1", "expectedVersion": material.version},
    headers={"Idempotency-Key": "preview-version-delete-api-1"},
)
assert preview.status_code == 200
assert preview.json()["versionId"] == version_id
```

Also assert pending Proposal returns a stable 409 error code and permanent delete requires `replacementVersionId` for the current version.

- [x] **Step 2: Verify RED**

Run:

```bash
cd backend
uv run pytest -q tests/test_profile_claim_api.py -k "material_version_deletion"
```

Expected: 404 because endpoints do not exist.

- [x] **Step 3: Add Pydantic commands/resources and routes**

Return the existing affected-Claim structure plus:

- `versionId`;
- `materialId`;
- `materialVersion`;
- `versionNumber`;
- `isCurrentVersion`;
- `pendingProposalCount`;
- `replacementVersions`.

Map stable domain errors through the existing Profile error envelope.

- [x] **Step 4: Verify GREEN**

Run:

```bash
cd backend
uv run pytest -q tests/test_profile_claim_api.py
python -m compileall -q app
```

Expected: API tests and compilation pass.

### Task 3: 增加版本删除入口和影响弹窗

**Files:**
- Create: `frontend/src/features/profile/VersionDeletionImpactDialog.tsx`
- Create: `frontend/src/features/profile/VersionDeletionImpactDialog.test.tsx`
- Modify: `frontend/src/features/profile/profileTypes.ts`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/features/profile/ResumeVersions.tsx`
- Modify: `frontend/src/features/profile/ResumeVersions.test.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/app/global.css`

**Interfaces:**
- Produces: `previewMaterialVersionDeletion(...)`
- Produces: `permanentlyDeleteMaterialVersion(...)`
- Produces: `VersionDeletionImpactDialog`
- Consumes: Task 2 API resources.

- [x] **Step 1: Write failing component tests**

Assert:

- multi-version material shows `删除当前版本 vN`;
- only-version material displays disabled explanatory copy;
- detail `proposalCounts.pending > 0` disables deletion and points to待确认;
- current-version dialog requires a replacement selection;
- non-current version does not require replacement;
- typed phrase `删除此版本` gates submission;
- success refreshes versions and remains on“简历与来源”。

- [x] **Step 2: Verify RED**

Run:

```bash
cd frontend
npm test -- --run \
  src/features/profile/ResumeVersions.test.tsx \
  src/features/profile/VersionDeletionImpactDialog.test.tsx
```

Expected: failure because the dialog/API/entry do not exist.

- [x] **Step 3: Implement API types and client**

Add exact camelCase resources and POST clients using existing `commandKey` / `commandOptions` idempotency behavior.

- [x] **Step 4: Implement the version menu and dialog**

Keep the material action labeled `永久删除整份简历（含 N 个版本）`. Add the separate version action with explicit disabled reasons. Reuse the existing viewport-bound dialog layout and batch Claim handling control.

- [x] **Step 5: Connect ProfilePage refresh behavior**

After success, refetch material, versions, detail, claims and unified profile; select the replacement/current remaining version without changing the active page tab.

- [x] **Step 6: Verify GREEN**

Run:

```bash
cd frontend
npm test -- --run \
  src/features/profile/ResumeVersions.test.tsx \
  src/features/profile/VersionDeletionImpactDialog.test.tsx \
  src/features/profile/DeletionImpactDialog.test.tsx
npx tsc --noEmit
```

Expected: focused UI tests and TypeScript pass.

### Task 4: 跨层回归与实页验收

**Files:**
- Modify: `docs/verification/r3-personal-profile-agent.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: targeted verification evidence and user-facing manual test steps.

- [x] **Step 1: Run targeted cross-layer regression**

```bash
cd backend
uv run pytest -q \
  tests/test_profile_claim_service.py \
  tests/test_profile_claim_api.py \
  tests/test_profile_material_api.py \
  tests/test_runtime_migrations.py

cd ../frontend
npm test -- --run \
  src/features/profile/ResumeVersions.test.tsx \
  src/features/profile/VersionDeletionImpactDialog.test.tsx \
  src/features/profile/DeletionImpactDialog.test.tsx
npx tsc --noEmit
```

- [ ] **Step 2: Run one browser happy path without executing deletion**

On port 5174, verify:

- version and material deletion labels are distinguishable;
- a target version with pending proposals cannot open deletion;
- eligible current-version deletion opens replacement selection;
- dialog stays within viewport at desktop and narrow width;
- no horizontal page overflow or console error.

- [x] **Step 3: Record verification**

Update `docs/verification/r3-personal-profile-agent.md` with commands, results and the explicit note that browser verification stops before the irreversible final submit.

**Initial execution note (2026-07-28):** automated cross-layer verification was complete before local test data existed. At that point the 5174 page had no initialized Workspace, so only application loading could be confirmed.

**Incremental browser note (2026-07-28):** 5174 later已有真实双版本简历。只读打开 v2 删除预检，确认 12 条受影响要点可全选、批量控件随选择启用、单条成果可展开查看结构化正文与依据数量，且弹窗保持视口内滚动；未输入确认词、未执行删除。当前版本替代选择、待确认全局阻断和窄屏验收仍保留在完整人工 happy path 中。
