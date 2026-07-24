# Profile Workbench Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan inline. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Profile source review and proposal review observable, bounded to the desktop viewport, batch-operable, and capable of reading the complete private resume.

**Architecture:** Add one reusable frontend workbench shell, keep Profile domain state in existing Material/Version/Proposal records, expose one Workspace-checked document resource backed by the existing original extracted text and deterministic redaction, and reuse the common Execution cancellation endpoint. Batch decisions continue through the existing idempotent domain service.

**Tech Stack:** React 18, TypeScript, TanStack Query, CSS Grid, FastAPI, Pydantic, SQLite, existing MaterialStorage and Execution Runtime.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-24-application-workspace-layout-guidelines.md`.
- Do not expose storage paths or public file URLs.
- Agent and model inputs continue using redacted content only.
- Do not invent percentage progress.
- Stop preserves uploaded, parsed, redacted, and persisted proposal state; continue starts a new Execution from the last durable business stage.
- One-click confirmation excludes conflicts and structurally incomplete proposals.
- Use targeted tests; do not repeat the full regression in this patch unless a cross-layer failure requires it.

---

### Task 1: Shared Bounded Workbench Layout

**Files:**
- Create: `frontend/src/shared/ui/TaskWorkspace.tsx`
- Modify: `frontend/src/app/global.css`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Test: `frontend/src/features/profile/ProfilePage.test.tsx`

**Interfaces:**
- Produces `TaskWorkspace`, `TaskWorkspacePane`, and `profile-shell--workbench` for Tasks 2 and 3.

- [x] Add a component test proving labelled panes and scroll-region semantics.
- [x] Implement the shared shell with no data ownership or page-specific height arithmetic.
- [x] Make Profile tabs select reading versus workbench mode; desktop workbench consumes the remaining page height and mobile restores document flow.
- [x] Run `npm test -- --run src/features/profile/ProfilePage.test.tsx` and `npx tsc --noEmit`.

### Task 2: Two-Pane Sources and Observable Processing

**Files:**
- Modify: `frontend/src/features/profile/ResumeVersions.tsx`
- Create: `frontend/src/features/profile/ProfileBackgroundTask.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ResumeVersions.test.tsx`
- Test: `frontend/src/features/profile/ProfilePage.test.tsx`

**Interfaces:**
- Consumes existing `ProfileMaterialVersionDetail.execution`.
- Uses `cancelAgentExecution(executionId)` and `retryMaterialVersion(workspaceId, versionId)`.
- Produces a two-pane workbench, live elapsed timer, completed-stage summary, stop/continue controls, and a persistent Profile-tab task banner.

- [x] Add tests for two-pane structure, real stages, elapsed time, stop copy, completion CTA, and no third status rail.
- [x] Move version statistics and actions into the detail header; keep destructive actions in a disclosure.
- [x] Limit preview to a small summary and add “查看完整简历”.
- [x] Add stop mutation and refetch; terminal cancellation must present “继续整理”.
- [x] Run the two affected component tests and TypeScript.

### Task 3: Batch-Oriented Pending Review

**Files:**
- Modify: `frontend/src/features/profile/ClaimReview.tsx`
- Create: `frontend/src/features/profile/ProfileBatchConfirmDialog.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfilePage.test.tsx`

**Interfaces:**
- Consumes existing `batchDecideClaimProposals`.
- Produces row checkboxes, select current filter, clear, accept selected, ignore selected, and safe one-click confirmation.

- [x] Add tests proving every pending row has a checkbox, current-filter selection excludes conflicts/incomplete proposals, and the dialog reports accepted/excluded counts.
- [x] Replace technical detail tables with a readable final-card preview, user-facing change summary, reason, and source.
- [x] Keep list/detail/actions as independent bounded regions.
- [x] Preserve failed/conflicting selections after partial batch completion.
- [x] Run the affected frontend test and TypeScript.

### Task 4: Workspace-Checked Complete Document Reader

**Files:**
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Modify: `backend/app/profile/service.py`
- Test: `backend/tests/test_unified_profile_api.py`
- Modify: `frontend/src/features/profile/profileTypes.ts`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Create: `frontend/src/features/profile/ProfileDocumentReader.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/features/profile/ResumeVersions.tsx`
- Modify: `frontend/src/features/profile/ClaimReview.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfilePage.test.tsx`

**Interfaces:**
- Produces `GET /api/profile/material-versions/{versionId}/document?workspaceId=...`.
- Resource fields: `versionId`, `fileName`, `mimeType`, `versionNumber`, `originalText`, `redactedText`, and bounded outline items with Evidence IDs and locators.
- Reader accepts an optional Evidence ID and focuses the matching outline item.

- [x] Add API tests for original/redacted text, Workspace isolation, missing parsed text, and absence of storage refs.
- [x] Read original extracted text through `MaterialStorage.read_text`; compute redacted text with the same deterministic redactor used by ingest.
- [x] Add frontend query and a full workbench reader with original/redacted tabs, outline, readable content, position focus, and private-content copy.
- [x] Route “查看完整简历”, preview blocks, and proposal Evidence links to the same reader.
- [x] Run targeted backend API tests, affected frontend tests, and TypeScript.

### Task 5: Acceptance and Design-Guideline Evidence

**Files:**
- Modify: `docs/verification/r3-personal-profile-agent.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes Tasks 1–4.
- Produces measured viewport and interaction evidence.

- [x] Run targeted frontend and backend suites plus `git diff --check`.
- [x] At 390/768/1024/1440 verify sources and pending workbenches, batch dialog, document reader, running/terminal processing states, horizontal overflow, and keyboard reachability.
- [x] Confirm desktop workbench document height does not exceed viewport height.
- [x] Run the stage documentation gate.
- [x] Do not commit until the user requests a local commit.

## Self-Review

- Spec coverage: all eleven confirmed grilling decisions map to Tasks 1–5.
- Placeholder scan: no deferred behavior or undefined interface remains.
- Type consistency: the backend document resource maps directly to the TypeScript reader type; cancellation and batch decisions reuse existing stable APIs.
- Execution choice: inline execution, because repository rules prohibit unnecessary subagents and the user asked Codex to continue directly.
