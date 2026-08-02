# Profile, Job Target, and Review Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep review independently usable while making confirmed profile assets, job-target preparation, and target/project-specific review form a clear, traceable journey.

**Architecture:** Reframe existing profile and job-target projections rather than changing their source-of-truth models. Extend review-round settings with an additive question scope that filters existing catalog metadata (`source_job_target_id` and `project_claim_id`), persists in the existing JSON settings payload, and remains backward compatible with historical rounds.

**Tech Stack:** React 19, TypeScript, TanStack Query, React Router, FastAPI, Pydantic, SQLite JSON persistence, Vitest, Pytest.

## Global Constraints

- Ordinary review remains the default and never requires a profile or job target.
- Target/project review can select only confirmed active catalog questions whose existing origin metadata matches the requested scope.
- Historical rounds without scope fields render as ordinary review.
- Do not change Agent prompts, provider calls, review evaluation state machine, Claim/Evidence ownership, project deep-dive execution, or evaluation workbench.
- Do not add a database table or migrate historical data; review settings remain additive JSON.
- Do not make review results automatically change job-target readiness in this slice.
- Reuse the current application layout, tokens, Button, and Lucide components.
- Run targeted tests per task; run only two browser paths after integration.

---

### Task 1: Profile value hierarchy and handoff

**Files:**
- Modify: `frontend/src/features/profile/UnifiedProfileOverview.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/UnifiedProfileOverview.test.tsx`

**Interfaces:**
- Consumes: the existing `UnifiedProfile` projection without new API fields.
- Produces: `onCreateJobTarget(): void` and `onOpenReview(): void` actions from the profile overview.

- [x] **Step 1: Add failing component tests**

Assert that confirmed profile content leads the page, source-health issues live in a secondary area, contradictory empty-state copy is absent, and both handoff actions call their callbacks.

- [x] **Step 2: Run the focused test and verify RED**

Run: `node_modules/.bin/vitest run src/features/profile/UnifiedProfileOverview.test.tsx`

- [x] **Step 3: Implement the hierarchy and navigation callbacks**

Keep all source-health counts and filters available, but present career direction, strengths, projects, and next actions before diagnostic support labels. Wire ProfilePage navigation to `/targets` and `/review` without creating domain records automatically.

- [x] **Step 4: Run the focused test and TypeScript**

Run: `node_modules/.bin/vitest run src/features/profile/UnifiedProfileOverview.test.tsx && node_modules/.bin/tsc --noEmit`

---

### Task 2: Job-target readiness projection and overview

**Files:**
- Modify: `backend/app/job_targets/application.py`
- Modify: `backend/app/schemas/job_targets.py`
- Modify: `backend/tests/test_job_training_workflow.py`
- Modify: `frontend/src/features/jobTargets/jobTargetTypes.ts`
- Modify: `frontend/src/features/jobTargets/JobTargetOverview.tsx`
- Modify: `frontend/src/features/jobTargets/JobTargetPage.tsx`
- Modify: `frontend/src/features/jobTargets/jobTargets.css`
- Modify: `frontend/src/features/jobTargets/JobTargetComponents.test.tsx`

**Interfaces:**
- Produces: readiness counts `pendingRequirements`, `confirmedRequirements`, `rejectedRequirements`, `confirmedProjectQuestions`, plus the existing project-priority IDs.
- Produces: `onStartTargetReview(jobTargetId: string): void`, navigating to `/review?create=1&scope=job-target&jobTargetId=<id>&returnTo=<target-url>` only when confirmed project questions exist.

- [x] **Step 1: Add failing backend and frontend tests**

Prove readiness counts use current target data, incomplete job metadata wins over a deep-dive CTA, confirmed and pending requirements are not conflated, and the target-review CTA is disabled with an explanation when no confirmed project questions exist.

- [x] **Step 2: Run focused tests and verify RED**

Run backend: `../.venv/bin/python -m pytest backend/tests/test_job_training_workflow.py -q`

Run frontend: `node_modules/.bin/vitest run src/features/jobTargets/JobTargetComponents.test.tsx`

- [x] **Step 3: Extend readiness and rebuild the overview**

Use existing job requirement, priority, deep-dive, gap, and project-question tables. Do not expose internal run IDs. Keep reanalysis secondary and explain that accepted decisions remain explicit.

- [x] **Step 4: Run focused tests**

Run the two commands from Step 2 and verify PASS.

---

### Task 3: Durable ordinary, job-target, and project review scopes

**Files:**
- Modify: `backend/app/review/models.py`
- Modify: `backend/app/schemas/review.py`
- Modify: `backend/app/review/selector.py`
- Modify: `backend/app/review/repository.py`
- Modify: `backend/app/review/application.py`
- Modify: `backend/app/api/routes_review.py`
- Modify: `backend/tests/test_review_selector.py`
- Modify: `backend/tests/test_review_api_v2.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`

**Interfaces:**
- Adds `ReviewQuestionScope = ordinary | job_target | project`.
- Adds optional settings fields `question_scope`, `source_job_target_id`, and `project_claim_id`.
- Validation requires exactly the matching ID for scoped review and rejects cross-workspace or empty scopes through the eligible-count path.
- Selector filters `QuestionCatalogRecord.source_job_target_id` or `.project_claim_id` before topic/difficulty selection.

- [x] **Step 1: Add failing selector and route tests**

Cover ordinary review remaining unfiltered, target scope excluding other targets, project scope excluding other projects, missing IDs returning validation errors, insufficient scoped questions using the existing safe error, and historical JSON settings defaulting to ordinary.

- [x] **Step 2: Run focused backend tests and verify RED**

Run: `../.venv/bin/python -m pytest backend/tests/test_review_selector.py backend/tests/test_review_routes.py -q`

- [x] **Step 3: Implement additive scope fields and selection**

Serialize new settings fields into the existing JSON payload. Keep `_settings()` defaults for old records. Do not copy target/profile facts into the round snapshot; only freeze selected questions and stable origin IDs.

- [x] **Step 4: Run focused backend tests**

Run the command from Step 2 and verify PASS.

---

### Task 4: Scoped review creation, labels, and return navigation

**Files:**
- Modify: `frontend/src/features/review/ReviewSetup.tsx`
- Modify: `frontend/src/features/review/ReviewPage.tsx`
- Modify: `frontend/src/features/review/ReviewLanding.tsx`
- Modify: `frontend/src/features/review/ReviewHistory.tsx`
- Modify: `frontend/src/features/review/reviewScope.ts`
- Modify: `frontend/src/features/jobTargets/ProjectQuestionCandidates.tsx`
- Modify: `frontend/src/features/jobTargets/JobTargetPage.tsx`
- Modify: `frontend/src/features/review/review.css`
- Modify: `frontend/src/features/review/ReviewPage.test.tsx`
- Modify: `frontend/src/features/review/ReviewHistory.test.tsx`
- Modify: `frontend/src/features/review/ReviewRound.test.tsx`

**Interfaces:**
- Consumes query parameters `create`, `scope`, `jobTargetId`, `projectClaimId`, `returnTo`, and `returnLabel`.
- Ordinary setup keeps its existing mode controls.
- Scoped setup fixes the question source, shows the matching count and origin label, and does not silently broaden to ordinary questions.
- Round and history labels use stored settings; historical rounds render `自主复习`.

- [x] **Step 1: Add failing UI tests**

Cover ordinary setup unchanged, target scope preselection, project scope preselection, zero-match explanation, source label in active/history views, and one-step return navigation.

- [x] **Step 2: Run focused frontend tests and verify RED**

Run: `node_modules/.bin/vitest run src/features/review/ReviewPage.test.tsx src/features/review/ReviewHistory.test.tsx src/features/review/ReviewRound.test.tsx`

- [x] **Step 3: Implement scoped setup and origin presentation**

Reuse the existing setup card and page shell. Do not create a second review workspace. Keep ordinary review as the default when no valid scoped query is present.

- [x] **Step 4: Run focused tests and TypeScript**

Run: `node_modules/.bin/vitest run src/features/review/ReviewPage.test.tsx src/features/review/ReviewHistory.test.tsx src/features/review/ReviewRound.test.tsx && node_modules/.bin/tsc --noEmit`

---

### Task 5: Integration verification and documentation state

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `docs/verification/job-target-and-project-deep-dive.md` if present; otherwise update the current review verification document that owns these paths.

**Interfaces:**
- Browser path A: `/review` creates an ordinary review and shows `自主复习`.
- Browser path B: a job target with confirmed project questions opens scoped setup, creates a round containing only that target's questions, and returns to the source target.

- [x] **Step 1: Run focused integrated gates**

Run the Task 2–4 backend tests, Task 1–4 frontend tests, `node_modules/.bin/tsc --noEmit`, Python compileall for changed backend packages, and `git diff --check`.

- [x] **Step 2: Run two browser paths on port 5174**

Do not call an external model merely to create test data. Use existing confirmed questions and stop if the current workspace lacks scoped data; record that blocker instead of fabricating success.

- [x] **Step 3: Record evidence and remaining maturity boundary**

State explicitly that review results do not yet aggregate back into job-target readiness and that no Agent or model behavior changed.
