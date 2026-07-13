# Learning Documentation Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill under-documented ownership packs and enforce risk-based learning-document depth without using word-count quotas.

**Architecture:** `overview.md` declares one of four learning profiles and its stage-specific risk drivers. The deterministic stage-doc checker enforces profile-aware structural evidence, while the template and dual-track workflow retain one final human depth review for semantics the script cannot prove.

**Tech Stack:** Markdown, Python 3 standard library, `unittest`, repository-local documentation gate.

## Global Constraints

- Keep exactly seven required learning files; R1.2 may retain its existing optional `notes.md`.
- Do not use total line or word count as a pass/fail threshold.
- Learning profiles are `foundation`, `stateful`, `integration`, and `experience`; mixed stages select the higher-risk profile.
- `docs/learning/` and `docs/verification/` remain ignored local artifacts and must be explicitly synchronized after merge.
- Only real failures may appear in failure journals.
- User exercises remain non-blocking understanding debt.
- Do not modify `docs/my_idea.md` or product runtime behavior.
- One Agent owns all tasks; use targeted script tests and documentation gates only.

---

## File Map

| File | Responsibility |
|---|---|
| `scripts/check_stage_docs.py` | Parse the learning profile and enforce profile-aware structural evidence. |
| `scripts/test_check_stage_docs.py` | Prove shallow packs fail and concise experience packs pass. |
| `docs/superpowers/templates/stage-learning-pack-template.md` | Authoring contract for all seven learning files and four profiles. |
| `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md` | Stage-close generation and one-time human review workflow. |
| `AGENTS.md`, `CLAUDE.md` | Short operational entry points for the new gate. |
| `docs/learning/<stage>/*.md` | Local ownership content; never staged or committed. |
| `task_plan.md`, `findings.md`, `progress.md` | Current bounded task state and final evidence. |

### Task 1: Add profile-aware documentation gate

**Files:**

- Modify: `scripts/test_check_stage_docs.py`
- Modify: `scripts/check_stage_docs.py`

**Interfaces:**

- Consumes: the existing `check_learning(directory: Path) -> list[CheckIssue]` entry point.
- Produces: `LearningProfile`, `parse_learning_profile(text: str)`, profile-aware `check_learning` diagnostics, with the existing CLI unchanged.

- [x] **Step 1: Expand valid fixtures and add RED tests**

Make `valid_learning_files(profile="foundation")` emit the fixed declaration:

```markdown
## 学习档案

- 类型：`foundation`
- 风险驱动：
  - 持久化状态跨进程恢复；
  - 不可信输入不能获得运行权限。
```

Add tests proving:

```python
def test_missing_or_unknown_learning_profile_fails(): ...
def test_foundation_requires_five_architecture_sections(): ...
def test_foundation_requires_two_code_chains(): ...
def test_foundation_requires_five_interview_questions(): ...
def test_failure_journal_requires_evidence_shape(): ...
def test_experience_profile_accepts_one_chain_and_three_questions(): ...
```

- [x] **Step 2: Run RED**

Run: `python3 -m unittest -q scripts/test_check_stage_docs.py`

Expected: new tests fail because profiles and profile-aware depth are not parsed.

- [x] **Step 3: Implement minimal profile parsing and checks**

Add a string enum and thresholds:

```python
class LearningProfile(str, Enum):
    FOUNDATION = "foundation"
    STATEFUL = "stateful"
    INTEGRATION = "integration"
    EXPERIENCE = "experience"

PROFILE_MINIMUMS = {
    LearningProfile.FOUNDATION: (2, 5),
    LearningProfile.STATEFUL: (2, 5),
    LearningProfile.INTEGRATION: (2, 5),
    LearningProfile.EXPERIENCE: (1, 3),
}
```

Parse the exact `- 类型：` declaration, require two nested risk bullets, require the five architecture headings from the design, count `## 链路` sections and `###` interview questions, and accept either structured failure evidence keywords or an explicit no-real-failure declaration with a verification reference. Keep all existing verification/plan checks.

- [x] **Step 4: Run GREEN and regression**

Run: `python3 -m unittest -q scripts/test_check_stage_docs.py`

Expected: all old and new tests pass.

- [x] **Step 5: Review and commit**

Run: `git diff --check && git diff --stat`

Commit:

```bash
git add scripts/check_stage_docs.py scripts/test_check_stage_docs.py
git commit -m "feat(docs): enforce risk-based learning depth"
```

### Task 2: Update the authoring and stage-close rules

**Files:**

- Modify: `docs/superpowers/templates/stage-learning-pack-template.md`
- Modify: `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**

- Consumes: the fixed profile syntax and thresholds from Task 1.
- Produces: one authoritative generation contract referenced by short startup instructions.

- [x] **Step 1: Rewrite the learning template around profiles**

Add the four profile definitions and copy the exact declaration syntax from the design. For every learning file, specify required evidence, including the five architecture sections, profile-aware chain/question counts, real-failure structure, and evidence-producing exercises. State explicitly that word count is not a gate.

- [x] **Step 2: Update workflow and startup entry points**

In the dual-track workflow, require classification before generation, generation only after implementation stabilizes, one final evidence refresh, one machine gate, and one human comparison against the previous same-profile stage. Keep AGENTS/CLAUDE wording short and point to the template rather than duplicating it.

- [x] **Step 3: Record bounded current state**

Update the three root planning files with the current branch/worktree, four tasks, the finding that structure-only checks allowed depth regression, and the test evidence from Task 1. Keep their combined startup size under 400 lines.

- [x] **Step 4: Validate formal documents**

Run:

```bash
rg -n "TODO|TBD|待补充|待完善" \
  docs/superpowers/templates/stage-learning-pack-template.md \
  docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md \
  AGENTS.md CLAUDE.md
git diff --check
```

Expected: no placeholder or whitespace errors.

- [x] **Step 5: Commit**

```bash
git add AGENTS.md CLAUDE.md task_plan.md findings.md progress.md \
  docs/superpowers/templates/stage-learning-pack-template.md \
  docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md
git commit -m "docs(learning): define profile-aware ownership standard"
```

### Task 3: Backfill local ownership packs

**Files:**

- Modify local: `docs/learning/r1-2-runtime/overview.md`
- Modify local: `docs/learning/r1-3-tool-security/overview.md`
- Modify local: `docs/learning/r1-4-hitl/*.md`
- Modify local: `docs/learning/r1-5-knowledge-publication/overview.md`
- Modify local: `docs/learning/r1-6/*.md`
- Modify local: `docs/learning/pre-r2-experience-stabilization/*.md`
- Modify local: `docs/learning/runtime-middleware-1-0/*.md`
- Create local: `docs/learning/settings-experience-redesign/*.md`

**Interfaces:**

- Consumes: final code, stage specs/plans, verification guides, commit history, and the Task 2 template.
- Produces: seven profile-valid local ownership packs plus retained R1.2 `notes.md`.

- [x] **Step 1: Synchronize the current local packs into the isolated worktree**

Copy only `docs/learning/` from the authoritative main checkout. Verify source and destination file lists match before editing. Do not copy unrelated ignored artifacts.

- [x] **Step 2: Add profile declarations to the three depth baselines**

Declare R1.2 and R1.3 as `foundation`, and R1.5 as `stateful`, with two stage-specific risk drivers each. Do not mechanically rewrite their existing bodies.

- [x] **Step 3: Rebuild R1.4 and R1.6**

Classify R1.4 as `stateful` and R1.6 as `integration`. Use current code symbols and actual recorded failures. R1.4 must explain action/receipt/delivery/run state, interrupt/resume, reconciliation, versioning and idempotency. R1.6 must explain model snapshots, temporary secret resolution, structured/stream calls, draft/HITL/publication, refresh and restart.

- [x] **Step 4: Rebuild Runtime Middleware and selectively deepen Pre-R2**

Classify middleware as `foundation` and Pre-R2 as `integration`. Middleware must document the three layers, onion wrappers, deferred SQLite writes, usage estimation, compaction, title CAS, persistent guard, HITL boundary, trace segments, fail-open and extension recipe. Pre-R2 must document source/draft lifecycles, safe Markdown read/edit behavior, query invalidation, conditional HITL and responsive/accessibility behavior.

- [x] **Step 5: Create the settings experience pack**

Use directory `docs/learning/settings-experience-redesign/` to match the formal implementation plan. Classify it as `experience`; cover overview navigation, stable query keys, save invalidation, dirty-form confirmation, progressive disclosure, keyboard/44px/mobile behavior, actual browser limitations, and real implementation failures only.

- [x] **Step 6: Run each pack through the new learning checker**

Use a small temporary valid verification/checked plan fixture or the stage's real verification/plan where both are available. Run all seven directories and fix only reported evidence gaps. Expected: each command prints `Stage documentation gate passed`.

- [x] **Step 7: Confirm ignored-artifact boundary**

Run:

```bash
git check-ignore docs/learning/runtime-middleware-1-0/overview.md
git check-ignore docs/learning/settings-experience-redesign/overview.md
git status --short
```

Expected: both learning paths are ignored and no learning file is staged.

### Task 4: Final review, evidence, and handoff

**Files:**

- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Local verification only: `docs/learning/**`

**Interfaces:**

- Consumes: Tasks 1–3 and the approved design.
- Produces: final test evidence, a clean formal diff, and an explicit main-sync manifest for ignored learning packs.

- [x] **Step 1: Run final script regression**

Run: `python3 -m unittest -q scripts/test_check_stage_docs.py`

Expected: all documentation-gate tests pass.

- [x] **Step 2: Run all learning gates once**

Run the checker for R1.2, R1.3, R1.4, R1.5, R1.6, Pre-R2, Runtime Middleware, and settings experience using their checked stage plans. If a historical plan lacks the current browser checkbox shape, use a temporary checked plan fixture for learning-only validation and record that distinction rather than editing historical evidence.

- [x] **Step 3: Perform one human depth review**

Compare architecture, code walkthrough, failure journal, questions, and exercises across the four profiles. Confirm that state ownership, visible-result chains, real failures and boundaries are present without duplicated padding.

- [x] **Step 4: Update task evidence and commit formal files**

Record exact test counts, directories validated, local sync requirement and remaining non-blocking learning debt. Run `git diff --check` and commit only tracked formal files:

```bash
git add task_plan.md findings.md progress.md
git commit -m "docs(learning): record ownership pack remediation"
```

- [ ] **Step 5: Integration handoff**

Before merging, list tracked commits and local learning directories. After a fast-forward merge, explicitly copy the final ignored `docs/learning/` directories to the main checkout and compare file lists plus hashes. The task is not closed until the main checkout passes the script regression and all learning gates.

## Verification Budget

- Documentation script regression: once per code task and once final.
- All-pack gate: once after backfill and once after main synchronization.
- Human depth review: once.
- Backend/frontend/browser regression: zero; product code is unchanged.
- Agent handoff/subagents: zero.
- Same unchanged failure: stop after two attempts and diagnose.
- Tool output: default under approximately 4,000 tokens.

## Completion Boundary

This slice is complete when the tracked checker/template/workflow changes are committed, all eight local ownership-pack directories pass the profile-aware gate, ignored learning artifacts are explicitly synchronized into `main`, and the final report separates product status from user ownership. Completion does not mean the user has completed any exercise.
