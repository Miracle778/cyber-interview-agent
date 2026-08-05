# Interview Retrospective Segmented Question Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process one-hour-plus retrospective transcripts end to end by extracting questions from persisted segment windows, deterministically merging overlap by evidence anchors, and treating candidate-only recordings as explicit inferred evidence.

**Architecture:** Keep the implementation inside the interview-retrospective domain. Cleanup continues to create confirmed ordered `SegmentRecord` evidence; analysis replaces the single 60,000-character extraction request with persisted segment-window Map items and one deterministic Reduce item. Source versions freeze recording coverage, window outputs use stable segment anchors, and per-question analysis remains unchanged after reduction.

**Tech Stack:** Python 3.12+, asyncio, SQLite runtime migrations, LangChain structured output, FastAPI/Pydantic, React/TypeScript, Vitest.

## Global Constraints

- Do not introduce a generic long-document runtime or modify question-curation behavior.
- Source text and confirmed cleanup segments remain immutable evidence.
- A direct question anchors to its first question segment; a candidate-only inferred question anchors to its first answer segment.
- Identical question text with different anchors remains two interview occurrences.
- Natural-language summaries never become cross-window evidence.
- Completed extraction-window outputs survive refresh, stop, retry, and process restart.
- Do not commit until the user explicitly requests a local commit.

---

### Task 1: Freeze recording coverage on the source version

**Files:**
- Create: `backend/app/db/migrations/runtime/048_interview_source_recording_coverage.sql`
- Modify: `backend/app/interview_retrospectives/models.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/projection.py`
- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `backend/tests/test_interview_retrospective_migration.py`
- Modify: `backend/tests/test_interview_retrospective_api.py`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveCreateFlow.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveCreateFlow.test.tsx`

**Interfaces:**
- Produces: `RecordingCoverage = Literal["full_dialogue", "candidate_only", "mixed_unknown"]`.
- Extends: `add_source_version(..., recording_coverage: RecordingCoverage)` and the source resource field `recordingCoverage`.
- Defaults existing rows and recollections to `mixed_unknown`.

- [x] **Step 1: Write failing migration, API, and component tests**

```python
assert source["recordingCoverage"] == "candidate_only"
assert "recording_coverage" in runtime_columns("interview_source_versions")
```

```typescript
expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
  sourceKind: "transcript",
  recordingCoverage: "candidate_only",
}));
```

- [x] **Step 2: Run tests and verify RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_migration.py tests/test_interview_retrospective_api.py -k 'recording_coverage or capture_cleanup'`

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/RetrospectiveCreateFlow.test.tsx`

- [x] **Step 3: Add migration 048 and pass coverage through source persistence and API**

```sql
ALTER TABLE interview_source_versions
ADD COLUMN recording_coverage TEXT NOT NULL DEFAULT 'mixed_unknown'
CHECK (recording_coverage IN ('full_dialogue', 'candidate_only', 'mixed_unknown'));
```

- [x] **Step 4: Add the transcript-only coverage selector**

Render three radio choices under “录音转写”; when source kind is `recollection`, submit `mixed_unknown` and hide the recording-only selector.

- [x] **Step 5: Run focused tests and verify GREEN**

Run the same backend and frontend commands from Step 2.

### Task 2: Plan segment windows and deterministically reduce anchored questions

**Files:**
- Create: `backend/app/graphs/interview_retrospective_question_extraction.py`
- Modify: `backend/app/agents/interview_retrospective_contracts.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Create: `backend/tests/test_interview_retrospective_question_extraction.py`
- Modify: `backend/tests/test_interview_retrospective_agents.py`

**Interfaces:**
- Produces: `create_question_windows(segments, *, max_characters=12_000, overlap_segments=4) -> tuple[QuestionWindow, ...]`.
- Produces: `reduce_extracted_questions(window_outputs, *, segment_order) -> tuple[dict[str, object], ...]`.
- Separates: provider `QuestionExtractionModelOutput` semantic fields from program-owned `ordinal` and `anchor_segment_id`.
- Extends: `extract_questions(..., recording_coverage, allowed_segment_ids)` and validates every referenced segment.

- [x] **Step 1: Write failing planner and reducer tests**

```python
def test_overlap_with_same_anchor_merges_answer_segments():
    reduced = reduce_extracted_questions(
        [
            [{"anchorSegmentId": "s2", "answerSegmentIds": ["s3", "s4"]}],
            [{"anchorSegmentId": "s2", "answerSegmentIds": ["s4", "s5"]}],
        ],
        segment_order={"s2": 2, "s3": 3, "s4": 4, "s5": 5},
    )
    assert reduced[0]["answerSegmentIds"] == ["s3", "s4", "s5"]

def test_same_text_with_different_anchors_stays_two_questions(): ...
def test_candidate_only_question_anchors_to_first_answer_segment(): ...
def test_leading_continuation_attaches_to_previous_anchor(): ...
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_question_extraction.py tests/test_interview_retrospective_agents.py`

- [x] **Step 3: Implement segment-window planning and anchor reduction**

`QuestionWindow.work_key` is `question_extraction:{first_ordinal}:{last_ordinal}`. Windows include complete segment objects and four segment overlaps; output ordinals are local and the reducer assigns final global ordinals.

- [x] **Step 4: Enforce evidence contracts in the Agent boundary**

For `original`, the anchor must be the first `questionSegmentId`. For `inferred`, it must be the first `answerSegmentId` and `inferenceBasis` is mandatory. `continues_previous` may only appear on the first candidate in a window; its answer IDs are merged into the previous ordered anchor by the reducer.

- [x] **Step 4a: Remove unrelated context and non-semantic provider fields**

Question extraction sends `transcript_only` window input and never receives profile, resume Claim, job-document body or historical review context. The model returns semantic evidence only; the program assigns local ordinals and anchors before persistence.

- [x] **Step 4b: Bound structured-output repair**

Disable ToolStrategy's hidden schema retry. A validation error gets at most one compact repair request containing the invalid candidates and only their referenced evidence. A second validation error or out-of-window evidence stops the current window without replaying its full input.

- [x] **Step 5: Run focused tests and verify GREEN**

Run the same command from Step 2.

### Task 3: Persist and resume segmented question extraction

**Files:**
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/tests/test_interview_retrospective_api.py`

**Interfaces:**
- Produces: initial analysis work items `question_extraction:<first>:<last>` plus `question_reduce`.
- Produces: `fail_analysis_work_item`, `replace_question_extraction_item_with_windows`, and `MAX_QUESTION_EXTRACTION_CONCURRENCY = 2`.
- Consumes: Task 2 `QuestionWindow` and reducer functions.

- [x] **Step 1: Write failing state-machine tests**

```python
async def test_analysis_extracts_every_segment_beyond_sixty_thousand_characters(): ...
async def test_overlapping_question_windows_create_one_anchor_question(): ...
async def test_candidate_only_source_creates_pending_inferred_questions(): ...
async def test_question_window_timeout_splits_only_that_window(): ...
async def test_restart_reuses_completed_question_window_outputs(): ...
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_api.py -k 'sixty_thousand or overlapping_question or candidate_only or question_window_timeout or question_window_restart'`

- [x] **Step 3: Replace the single extraction item with deterministic window items**

At analysis creation, derive windows from confirmed, non-ignored segments and persist one work item per stable range. Persist `question_reduce` after the Map items and update `total_items` transactionally.

- [x] **Step 4: Execute extraction windows with concurrency two and explicit attempts**

Use the same `ModelInvocationPolicy(max_output_tokens=8192, request_timeout_seconds=120, max_retries=0)` boundary as Cleanup. Each window attempts at most twice; a timed-out multi-segment window is atomically replaced by two smaller overlapping segment windows.

- [x] **Step 5: Reduce only after every extraction item completes**

Load completed outputs in source order, reduce by anchor, call `replace_question_units`, complete `question_reduce`, and schedule the existing per-question analysis and finalizer work items. If any window is exhausted, preserve outputs and fail the run without creating partial formal questions.

- [x] **Step 6: Run focused tests and verify GREEN**

Run the same command from Step 2, then run `cd backend && uv run pytest -q tests/test_interview_retrospective_*.py`.

### Task 3c: Bound per-question analysis and isolate transient failures

**Files:**
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`

- [x] Add a per-question invocation policy with no hidden SDK retries.
- [x] Replace full profile/document transfer with bounded, question-relevant evidence.
- [x] Retry only the failed question, continue independent questions, and block finalizers until every question succeeds.
- [x] Resume the existing AnalysisRun from the UI so completed extraction and analysis work is reused.
- [x] Verify backend state recovery, frontend action wiring, Ruff, and diff integrity.

### Task 4: Expose extraction progress and evidence labels

**Files:**
- Modify: `frontend/src/features/interviewRetrospectives/AnalysisProgress.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/AnalysisProgress.test.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/QuestionTimeline.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/QuestionAnalysisPanel.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/RetrospectiveWorkspace.test.tsx`

**Interfaces:**
- Consumes: `AnalysisWorkItem.workKey` extraction prefixes and existing `InterviewQuestion.origin`.
- Displays: extraction-window progress independently from later per-question analysis progress.

- [x] **Step 1: Write failing progressive UI tests**

```typescript
expect(screen.getByText("已识别 2 / 5 个问题窗口")).toBeVisible();
expect(screen.getByText("根据回答推断")).toBeVisible();
```

- [x] **Step 2: Run focused tests and verify RED**

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/AnalysisProgress.test.tsx src/features/interviewRetrospectives/RetrospectiveWorkspace.test.tsx`

- [x] **Step 3: Derive extraction progress from report work items**

Pass report items into `AnalysisProgress`; count only `question_extraction:` keys during the extraction stage. Preserve existing overall progress after `question_reduce` schedules per-question work.

- [x] **Step 4: Label direct and inferred evidence without changing confirmation rules**

Render `原话问题` for `original` and `根据回答推断` for `inferred`; inferred questions remain pending until the existing confirm/edit/reject action resolves them.

- [x] **Step 5: Run focused tests and verify GREEN**

Run the same command from Step 2.

### Task 5: Documentation and verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-interview-retrospective-agent-design.md`
- Modify: `docs/verification/interview-retrospective.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [x] **Step 1: Record the implemented evidence and recovery contract**

Document recording coverage, segment-anchor ownership, same-text/different-occurrence behavior, no-summary evidence transfer, partial Map persistence, and the real-Provider boundary.

- [x] **Step 2: Run backend affected regression and static checks**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_*.py tests/test_agent_observability_service.py tests/test_agent_observability_routes.py tests/test_agent_observability_registry.py`

Run: `cd backend && uv run ruff check app tests/test_interview_retrospective_*.py`

- [x] **Step 3: Run frontend affected regression and production build**

Run: `cd frontend && pnpm exec vitest run src/features/interviewRetrospectives/RetrospectiveCreateFlow.test.tsx src/features/interviewRetrospectives/AnalysisProgress.test.tsx src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx src/features/interviewRetrospectives/RetrospectiveWorkspace.test.tsx`

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`

- [x] **Step 4: Run final diff and documentation checks**

Run: `git diff --check`

Run: `python3 scripts/check_stage_docs.py --verification docs/verification/interview-retrospective.md --learning docs/learning/interview-retrospective/ --plan docs/superpowers/plans/2026-08-02-interview-retrospective-segmented-question-extraction.md`

- [x] **Step 5: Complete one browser acceptance pass**

Use isolated data and no real Provider unless the user separately authorizes it. Verify the coverage selector, extraction progress, direct/inferred labels, refresh persistence, and 390px reachability before marking this step complete.

## Self-Review

- Spec coverage: Task 1 freezes source evidence mode; Task 2 owns planning and deterministic reduction; Task 3 owns persistence and recovery; Task 4 owns user-visible progress and evidence labels; Task 5 owns acceptance evidence.
- Placeholder scan: every production behavior has a concrete interface, test name, command, and expected observable result.
- Type consistency: `recordingCoverage`, `anchorSegmentId`, `boundaryRelation`, `question_extraction:<first>:<last>`, and `question_reduce` are identical across schema, Agent contract, persistence, and UI tasks.
