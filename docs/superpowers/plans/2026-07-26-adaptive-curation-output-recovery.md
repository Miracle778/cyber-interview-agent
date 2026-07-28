# Adaptive Curation Output Recovery Implementation Plan

> **For Codex:** Execute this plan inline with targeted tests. Preserve the current curation batch and its completed work items.

**Goal:** Make question curation survive reasoning-heavy or truncated model responses without relying on configured model-name heuristics or restarting completed work.

**Architecture:** Discovery uses bounded section groups and treats output truncation as a recoverable scheduling signal. A failed parent work item is retried as smaller in-memory partitions and its seed outputs are aggregated back into the same persisted work-item boundary, so existing completed work remains valid. Provider tests record the actual returned model identity and an internal capability profile; the resolver uses that profile conservatively, while bounded work and adaptive splitting remain the correctness boundary.

**Tech Stack:** Python 3.12, FastAPI, LangChain/LangGraph, Pydantic, SQLite, React/TypeScript.

---

### Task 1: Bound discovery work before it reaches the model

**Files:**
- Modify: `backend/app/review/curation_planner.py`
- Modify: `backend/app/agents/question_curation_contracts.py`
- Test: `backend/tests/test_curation_planner.py`

- [x] Add a failing test proving dense short sections are split at the section-count limit as well as the character limit.
- [x] Update `_pack_model_sections` to enforce both limits.
- [x] Add a persisted aggregate seed-output contract large enough for a parent work item that required several bounded model calls.
- [x] Run the planner test file only.

### Task 2: Detect truncated structured output and split adaptively

**Files:**
- Modify: `backend/app/agents/question_curation_agent.py`
- Modify: `backend/app/graphs/question_curation.py`
- Modify: `backend/app/review/curation_seed_reconciliation.py`
- Test: `backend/tests/test_question_curation_agent.py`
- Test: `backend/tests/test_question_curation_progressive_graph.py`

- [x] Add a typed `ModelOutputTruncatedError` when the final AI message reports `max_tokens` without a structured response.
- [x] Partition oversized legacy work items into bounded child inputs before invoking the model.
- [x] Recursively halve only the failed child on truncation; do not replay successful parent work items.
- [x] Aggregate child seed outputs under the original work-item ID and teach reconciliation to read the aggregate contract.
- [x] Surface an explicit retryable error if even a single-section child cannot return a final structured answer.
- [x] Run only the Agent and progressive-graph tests.

### Task 3: Probe and persist model capabilities internally

**Files:**
- Add: `backend/app/db/migrations/app/006_model_capability_profiles.sql`
- Modify: `backend/app/providers/base.py`
- Modify: `backend/app/providers/openai_compatible.py`
- Modify: `backend/app/providers/anthropic_compatible.py`
- Modify: `backend/app/repositories/provider_repository.py`
- Modify: `backend/app/services/provider_service.py`
- Modify: `backend/app/agents/agent_model_resolver.py`
- Test: `backend/tests/test_provider_service.py`
- Test: `backend/tests/test_agent_model_resolver.py`

- [x] Add internal fields for observed model ID, capability profile JSON, and probe time; expose no new user-editable form fields.
- [x] Capture the actual model identity and conservative reasoning/structured-output observations during model testing.
- [x] Persist partial/unknown probe results without turning a successful connectivity test into a failure.
- [x] Resolve reasoning controls from observed capability data first, configured aliases second, and conservative fallback last.
- [x] Verify an Anthropic-compatible alias returning a GLM identity receives the supported “reasoning disabled” control for standard curation.
- [x] Run only migration/provider/resolver tests.

### Task 4: Report persisted recovery progress truthfully

**Files:**
- Modify: `backend/app/review/application.py`
- Modify: relevant curation resource DTO/router if required
- Modify: relevant curation progress React component if required
- Test: targeted backend curation resource test
- Test: targeted frontend curation progress test

- [x] Derive completed, failed, running, and remaining counts from persisted work items even after an execution fails.
- [x] Keep user-facing language plain: “已完成 / 可继续处理 / 等待处理”, not scheduler internals.
- [x] Ensure a failed execution no longer collapses persisted progress to `0 / total`.
- [x] Run only the affected backend and frontend test files plus TypeScript checking if frontend code changes.

### Task 5: Verify against the current failed session

**Files:**
- Update: `progress.md`
- Update: `docs/verification/r2-complete-review-agent.md` if this slice already records curation recovery evidence

- [x] Back up the current development SQLite databases before applying migrations.
- [x] Restart only the backend needed for migration/code reload.
- [ ] Resume the existing failed curation session once and confirm completed work items are skipped.
- [ ] Confirm progress advances from the persisted baseline and the old dense failed items complete through bounded child calls.
- [x] Check the 5174 page for correct progress/error language and no new console error.
- [x] Run `git diff --check` and the minimal affected test set; do not run full regression.

Task 5 note: the backend restart and migration completed. The existing session
advanced through all `80 / 80` discovery items and persisted 95 of 166
enrichment candidates. The second real attempt exposed a distinct malformed
tool-payload case: LangChain's `StructuredOutputValidationError` escaped the
Seed-level invalid-response boundary. That wrapper is now handled by the
existing per-Seed retry/skip policy, and failed resources report enrichment
progress (`95 / 166`) rather than reverting to discovery progress. Re-running
the remaining enrichment work would send user material to the configured
external model proxy and is not triggered automatically.
