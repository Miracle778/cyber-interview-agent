# Interview Retrospective Long Transcript Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make retrospective cleanup reliable and progressively visible for one-hour-plus transcripts without restarting completed work after a timeout.

**Architecture:** Deterministically split source text at natural boundaries into bounded overlapping work items, bootstrap speaker hints from the earliest completed window, and process later windows with a concurrency limit of two. Provider retries are explicit: hidden SDK retries are disabled, timed-out large windows are atomically replaced with smaller persisted windows, exhausted failures remain retryable for a later user command, and the final reducer alone writes ordered segments.

**Tech Stack:** Python 3.12+, asyncio, SQLite work-item ledger, LangChain structured output, FastAPI/Pydantic, React/TypeScript.

## Global Constraints

- Preserve source text and absolute offsets; model output never overwrites the source.
- Completed work-item output is immutable during stop, retry, refresh, and process restart.
- At most two Provider calls run concurrently for one cleanup execution.
- Parallel workers only persist their own work-item output; final ordered segment writes remain single-threaded.
- No SDK-level automatic retry for cleanup; every application attempt is visible in work-item `attempt_count` and Trace.
- Existing cleanup rows require no destructive migration.

---

### Task 1: Natural windows, adaptive split, and speaker hints

**Files:**
- Modify: `backend/app/graphs/interview_retrospective_cleanup.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`
- Test: `backend/tests/test_interview_retrospective_agents.py`

**Interfaces:**
- Produces: `create_source_windows(body: str, *, window_size=4000, overlap=400)` and `split_source_window(body: str, *, source_start: int, source_end: int)`.
- Produces: `speaker_hints_from_outputs(outputs) -> tuple[dict[str, str], ...]`.
- Extends: `cleanup_window(..., speaker_hints: tuple[dict[str, str], ...])`.

- [x] **Step 1: Write failing boundary, split, hint, and prompt tests**

```python
def test_source_windows_prefer_natural_boundaries_and_cover_long_text():
    body = ("甲" * 3900) + "。\n" + ("乙" * 3900)
    windows = create_source_windows(body)
    assert windows[0].source_end == 3902
    assert windows[-1].source_end == len(body)

def test_timeout_split_keeps_absolute_offsets():
    children = split_source_window("字" * 10000, source_start=2000, source_end=8000)
    assert children[0].source_start == 2000
    assert children[-1].source_end == 8000

def test_speaker_hints_are_bounded_and_stable():
    hints = speaker_hints_from_outputs([...])
    assert hints == ({"rawSpeakerLabel": "说话人1", "speakerRole": "interviewer", "displayName": "面试官"},)
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_cleanup.py tests/test_interview_retrospective_agents.py`

- [x] **Step 3: Implement natural cut selection, one-level adaptive split, bounded hints, and prompt input**

```python
MAX_WINDOW_CHARACTERS = 4_000
WINDOW_OVERLAP_CHARACTERS = 400
ADAPTIVE_SPLIT_MIN_CHARACTERS = 2_500

def split_source_window(body: str, *, source_start: int, source_end: int): ...
def speaker_hints_from_outputs(outputs): ...
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_cleanup.py tests/test_interview_retrospective_agents.py`

### Task 2: Explicit Provider policy and persisted partial-failure scheduler

**Files:**
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Test: `backend/tests/test_interview_retrospective_api.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`

**Interfaces:**
- Produces: cleanup `ModelInvocationPolicy(max_output_tokens=8192, request_timeout_seconds=120, max_retries=0)`.
- Produces: `fail_cleanup_work_item`, `replace_cleanup_work_item_with_windows`, and bounded scheduling with `MAX_CLEANUP_CONCURRENCY = 2`, `MAX_CLEANUP_ATTEMPTS = 2`.

- [x] **Step 1: Write failing tests for concurrency, partial failure continuation, adaptive split, and resume**

```python
async def test_long_cleanup_runs_two_windows_concurrently_and_persists_each_result(): ...
async def test_timeout_splits_only_failed_large_window_and_other_windows_finish(): ...
async def test_exhausted_window_does_not_discard_successful_window_outputs(): ...
async def test_resume_after_restart_claims_only_unfinished_windows(): ...
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_api.py -k 'long_cleanup or timeout_splits or exhausted_window or restart'`

- [x] **Step 3: Implement atomic work-item split and per-item failure transitions**

```python
def replace_cleanup_work_item_with_windows(self, item_id: str, *, windows): ...
def fail_cleanup_work_item(self, item_id: str, *, error_code: str): ...
```

- [x] **Step 4: Implement bootstrap-first and concurrency-two scheduler**

```python
MAX_CLEANUP_CONCURRENCY = 2
MAX_CLEANUP_ATTEMPTS = 2

async def _process_cleanup_item(...): ...
async def _run_cleanup(...): ...
```

- [x] **Step 5: Run focused tests and verify GREEN**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_api.py tests/test_interview_retrospective_cleanup.py`

### Task 3: Progressive UX and real-provider verification boundary

**Files:**
- Modify: `backend/app/interview_retrospectives/projection.py`
- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.tsx`
- Test: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.test.tsx`

**Interfaces:**
- Adds: `activeItems` and `failedItems` to cleanup resources.
- Displays: completed/total windows, concurrent active count, saved partial segments, and failed-window count.

- [x] **Step 1: Write failing resource and component tests**

```typescript
expect(screen.getByText("正在并行处理 2 个文本窗口")).toBeVisible();
expect(screen.getByText("已保存 3 / 8 个文本窗口，1 个窗口待重试")).toBeVisible();
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/CleanupWorkbench.test.tsx`

- [x] **Step 3: Implement resource counts and progressive copy**

```python
"activeItems": sum(item.status == "running" for item in work_items)
"failedItems": sum(item.status == "retryable" for item in work_items)
```

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/CleanupWorkbench.test.tsx`

### Task 4: Documentation and verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-interview-retrospective-agent-design.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [x] **Step 1: Record the implemented long-transcript contract**

Document natural boundary windows, bootstrap speaker hints, concurrency two, explicit retry ownership, adaptive split, immutable completed outputs, and the distinction between connectivity tests and opt-in real Provider task tests.

- [x] **Step 2: Run affected backend regression**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_*.py tests/test_agent_observability_service.py tests/test_agent_observability_routes.py`

- [x] **Step 3: Run frontend regression and production build**

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/CleanupWorkbench.test.tsx src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx && pnpm build`

- [x] **Step 4: Run static and diff checks**

Run: `cd backend && uv run ruff check app tests/test_interview_retrospective_api.py tests/test_interview_retrospective_cleanup.py`

Run: `git diff --check`

- [ ] **Step 5: Complete one minimal browser acceptance pass**

The isolated local services started successfully, but the browser-control URL policy blocked the localhost reload. Do not mark this step complete until a user-driven browser pass confirms the retrospective page loads without new console errors and the progressive Cleanup states are visible.

## Self-Review

- Spec coverage: long input, bounded parallelism, stop/resume, partial failure, ordered reduction, progressive UI, and real Provider verification boundary are assigned to Tasks 1–4.
- Placeholder scan: every implementation step names concrete functions, files, and commands; no deferred implementation remains.
- Type consistency: work-item counts and speaker-hint structures use the same names across Python resources, Pydantic schemas, TypeScript types, and UI tests.
