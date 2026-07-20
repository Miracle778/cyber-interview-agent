# R3 Personal Profile Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first R3 acceptance milestone (R3.1-R3.4): securely ingest resume versions, derive evidence-backed profile claims, let the user assess and revise them through a constrained Agent workflow, and publish or revoke only explicitly selected confirmed claims.

**Architecture:** Add an isolated `app/profile` domain package and explicit `profile.ingest`, `profile.assess`, and `profile.manage` graphs while reusing the existing workspace Runtime, Session/Execution/Event stream, middleware, HITL, and knowledge draft/publication infrastructure. Domain facts live in normalized Runtime SQLite tables and private content-addressed artifacts; LangGraph checkpoints contain orchestration state only. Every mutation is performed by deterministic application services after validation or user confirmation—LLM Agents receive structured context and, only for `profile_chat`, a bounded read-only Tool allowlist.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite/aiosqlite, LangGraph/LangChain, pypdf, python-docx, React 19, TypeScript, React Router, Vitest, Testing Library, CSS semantic tokens.

## Global Constraints

- This plan implements only R3.1-R3.4. R3.5 external identity sources, OCR, general search, and automatic long-term memory remain outside the milestone.
- Keep `AgentState` as the default Agent state schema. Material, Evidence, Claim, Proposal, Plan, and publication state must not be copied into checkpoints.
- Do not implement general Time Travel or user-visible branches. Retry creates a new Execution against the same immutable input version or confirmed snapshot.
- `profile_extraction` and `profile_assessment` have no Tools. `profile_chat` receives only the read-only Tools selected for the current intent. `profile_action_planner` defaults to no Tools.
- LLM output is always a proposal. Only repositories and application services can accept claims, apply action-plan items, create knowledge drafts, publish, revoke, archive, restore, or delete.
- Every domain write uses an `Idempotency-Key`, an expected aggregate/plan version, and an immutable input or selection snapshot. Batch receipts distinguish `completed`, `conflict`, `failed_retryable`, `failed_terminal`, and `not_started`.
- Uploaded source bytes and extracted text remain under private workspace artifacts and are never written to the active knowledge Vault. Logs, Events, Tool audits, and frontend payloads must not contain raw resume text.
- Use one hidden `profile.ingest` system Session per material version, with `session_id == material_version_id`; generic session lists and generic session detail routes must not expose it.
- Preserve the existing frontend visual language: light, professional, data-dense, evidence-centered; reuse current semantic tokens and the 4/8 spacing system. Do not add a second theme or raw one-off colors.
- Every Task ends with a focused reviewer gate. Do not start the next Task while its focused tests or type checks are failing.
- Maintain `docs/verification/r3-personal-profile-agent.md` incrementally during implementation. Generate the R3 learning pack only after behavior stabilizes.

---

## File and Interface Map

### Backend domain and persistence

- Create `backend/app/db/migrations/runtime/016_r3_personal_profile.sql` for profile tables, system-session visibility, Tool audit correlation/digests, knowledge publication revocation state, and the `profile` document type constraint.
- Create `backend/app/profile/models.py` for immutable domain records and command/result types.
- Create `backend/app/profile/errors.py` for stable domain/API error codes.
- Create `backend/app/profile/repository.py` for Material, Version, Evidence, Claim, Proposal, Assessment, Action Plan, and publication-selection persistence.
- Create `backend/app/profile/storage.py` for private content-addressed source/text storage and verified deletion.
- Create `backend/app/profile/parsers.py` for PDF, DOCX, Markdown, and text extraction.
- Create `backend/app/profile/service.py` for upload/version lifecycle, proposal decisions, deletion impact preview, assessment requests, plan execution, and query-context assembly.

### Agent Runtime

- Create `backend/app/agents/profile_contracts.py` for structured extraction, assessment, chat, and action-plan outputs.
- Create `backend/app/agents/profile_agents.py` for four explicit Agent specs.
- Create `backend/app/agents/prompts/profile_prompts.py` for role-specific system prompts and deterministic input rendering.
- Create `backend/app/tools/profile_tools.py` for the eight bounded read-only Tools.
- Create `backend/app/graphs/profile_ingest.py`, `backend/app/graphs/profile_assess.py`, and `backend/app/graphs/profile_manage.py`.
- Extend `backend/app/application/graph_factory.py`, `backend/app/application/session_service.py`, `backend/app/application/execution_service.py`, and `backend/app/application/workspace_runtime.py`; do not introduce a parallel graph registry or execution engine.

### API

- Create `backend/app/schemas/profile.py` and `backend/app/api/routes_profile.py`.
- Extend `backend/app/main.py` with the profile router and stable error mapping.
- Extend existing generic Agent APIs only where system-session visibility or new safe Event/Message kinds require it.

### Knowledge publication

- Extend `backend/app/knowledge/document_types.py`, `backend/app/knowledge/workspace_layout.py`, `backend/app/knowledge/drafts.py`, `backend/app/knowledge/publication.py`, and `backend/app/services/search_index.py`.
- The new active document type is `profile`; its Vault target is `50_profile/<profile_document_id>.md`.
- Revocation is a recoverable state transition: verify the published hash, remove the active file, remove its search rows, and retain publication/provenance history in Runtime SQLite.

### Frontend

- Create `frontend/src/features/profile/profileTypes.ts`, `profileApi.ts`, `ProfilePage.tsx`, and focused view/component files under `frontend/src/features/profile/`.
- Extend `frontend/src/shared/api/client.ts` with a FormData upload helper.
- Extend `frontend/src/app/navigation/navigationItems.ts`, `frontend/src/app/layout/AppShell.tsx`, and `frontend/src/app/global.css`.
- Reuse the existing SSE hook and Agent workspace patterns; extend their event unions rather than creating a second streaming client.

### Frontend implementation matrix

| Screen | Primary regions | Shared primitives | Narrow-screen rule |
|---|---|---|---|
| Overview | primary resume, completeness, claim health, suggestions, publication coverage, recent sessions | Profile Shell, metric card, status badge, evidence link | one-column priority order; actions stay adjacent to their card |
| Material versions | upload/stages, version list, primary marker, comparison | stage row, version card/table, diff panel, drawer | table becomes labeled cards; diff stacks before/after |
| Evidence detail | immutable version context, locator, sanitized excerpt, linked claims | evidence card, locator chip, claim link, drawer | drawer becomes full-screen sheet |
| Claim review | filters/queue, current-vs-proposed diff, evidence/rationale, decisions | claim card, proposal badge, diff panel, receipt | filters collapse; detail follows selected queue card |
| Agent workspace | sibling sessions, focus, timeline/cards, composer/stop | session rail, Tool stage, assessment/action-plan card, composer | session rail becomes selector; composer remains sticky |
| Publication scope | confirmed claim selection, sensitive exclusions, preview, status/revoke | selection row, preview, status timeline, confirm dialog | groups become cards; preview follows selection |

Every screen must implement `loading`, `empty`, `error`, `conflict`, `partial_success`, `interrupted`, and `permission_denied` where the state is reachable. Shared primitives are implemented before screen-private layout rules; long text and real data are used in slice review.

---

## Task 1: Establish the R3 Runtime Schema and Shared Registries

**Files:**

- Create: `backend/app/db/migrations/runtime/016_r3_personal_profile.sql`
- Modify: `backend/app/schemas/settings.py`
- Modify: `backend/app/services/workspace_service.py`
- Modify: `backend/app/knowledge/document_types.py`
- Modify: `backend/app/knowledge/workspace_layout.py`
- Modify: `backend/app/security/workspace_paths.py`
- Modify: `backend/app/services/vault.py`
- Modify: `backend/pyproject.toml`
- Modify: `frontend/src/features/settings/providerTypes.ts`
- Modify: `frontend/src/features/settings/ModelBindings.tsx`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_provider_routes.py`
- Test: `backend/tests/test_frontmatter.py`
- Test: `backend/tests/test_workspace_paths.py`
- Test: `frontend/src/features/settings/ModelBindings.test.tsx`

- [x] Write migration tests that expect schema version 16, user/system Session visibility, correlated Tool audits, typed profile card Messages, the R3 tables/indexes, `profile` knowledge drafts, and revocable publication state. Confirm they fail because migration 016 does not exist.
- [x] Define the normalized R3 tables with foreign keys and constrained states:

  ```sql
  profile_materials(id, workspace_id, type, title, primary_role, current_version_id, lifecycle_status, version, created_at, updated_at)
  profile_material_versions(id, material_id, version_number, source_type, file_name, mime_type, content_sha256, storage_ref, text_ref, processing_status, derived_from_version_id, created_by, created_at)
  profile_evidence(id, material_version_id, section, start_offset, end_offset, sanitized_text, content_sha256, sensitivity, tombstoned_at, created_at)
  profile_claims(id, workspace_id, claim_type, current_confirmed_version_id, version, created_at, updated_at)
  profile_claim_versions(id, claim_id, version, value_json, status, support_status, evidence_ids_json, source, expected_previous_version, created_at, confirmed_at)
  profile_claim_proposals(id, workspace_id, proposal_type, target_claim_id, base_claim_version_id, proposed_value_json, reason, evidence_ids_json, status, created_by_execution_id, decided_at, created_at)
  profile_claim_conflicts(id, workspace_id, claim_id, proposal_id, conflicting_claim_version_id, created_at)
  profile_assessments(id, workspace_id, base_profile_version, result_json, created_by_execution_id, created_at)
  profile_action_plans(id, workspace_id, session_id, execution_id, request_summary, base_profile_version, selection_snapshot_json, status, version, expires_at, created_at, confirmed_at, completed_at)
  profile_action_plan_items(id, plan_id, item_id, ordinal, operation, target_json, expected_version, before_json, after_json, evidence_ids_json, status, receipt_id, error_code)
  profile_publication_selections(id, workspace_id, profile_version, excluded_sensitive_fields_json, status, version, created_at, updated_at)
  profile_publication_selection_items(selection_id, claim_version_id)
  profile_publications(id, workspace_id, draft_id, publication_run_id, profile_version, state, published_hash, revoked_at, created_at, updated_at)
  ```

- [x] Add `visibility TEXT NOT NULL DEFAULT 'user' CHECK (visibility IN ('user','system'))` to `agent_sessions`; add `tool_call_id`, `agent_role`, `input_digest`, and `result_digest` plus audit state `denied` to `tool_audits`; add Message kinds `claim_card`, `proposal_card`, `assessment_card`, `action_plan_card`, and `receipt`; rebuild only tables whose existing CHECK constraint must accept the new values, preserving all rows and indexes inside one transaction.
- [x] Add `profile_extraction` and `profile_assessment` to the backend `ModelRole`/`MODEL_ROLES` contract and change validation text from “four” to “six”; preserve existing bindings during migration but require all six on the next explicit settings save.
- [x] Add the two model roles and Chinese labels to frontend settings, update empty/complete binding state, and revise tests/error copy to six roles.
- [x] Register document type `profile -> 50_profile`, add the Vault directory, allow `initialize_knowledge_artifacts(..., domain="profile")`, and add private scope `profile.materials -> artifacts/profile/materials`.
- [x] Add `python-docx>=1.1.0` to backend dependencies and update the lock file using the repository's existing package workflow.
- [x] Run `cd backend && uv run pytest -q tests/test_runtime_migrations.py tests/test_provider_routes.py tests/test_frontmatter.py tests/test_workspace_paths.py`. Expected: all focused schema, role, registry, and path-policy tests pass.
- [x] Run `cd frontend && npm test -- --run src/features/settings/ModelBindings.test.tsx`. Expected: all six roles load and save as one complete payload.
- [x] Reviewer gate: inspect migration rollback safety, table rebuild copy columns, foreign-key checks, and confirm no raw material path can resolve into `knowledge-vault`.

## Task 2: Define Profile Domain Contracts and Repository Invariants

**Files:**

- Create: `backend/app/profile/__init__.py`
- Create: `backend/app/profile/models.py`
- Create: `backend/app/profile/errors.py`
- Create: `backend/app/profile/repository.py`
- Test: `backend/tests/test_profile_repository.py`

- [x] Write repository tests for material version monotonicity, one active material per `primary_role`, immutable Evidence/tombstones, accepted Claim version monotonicity, independent decision/support states, proposal idempotency, optimistic claim-version conflicts, assessment snapshots, ordered plan items, versioned publication selection, archive/restore, and workspace isolation. Confirm imports or tests fail before implementation.
- [x] Define Literal-backed status types and frozen dataclasses/Pydantic value objects. Use JSON only for typed values/locators/receipts; never store raw LLM envelopes as the source of truth.
- [x] Implement `ProfileRepository` methods with explicit transactions, including:

  ```python
  create_material(command) -> ProfileMaterialRecord
  add_material_version(command) -> ProfileMaterialVersionRecord
  mark_version_parsed(version_id, *, text_path, content_sha256) -> ProfileMaterialVersionRecord
  replace_version_evidence(version_id, evidence) -> tuple[EvidenceRecord, ...]
  create_claim_proposals(version_id, proposals) -> tuple[ClaimProposalRecord, ...]
  decide_proposal(proposal_id, *, decision, expected_status) -> ClaimDecisionResult
  batch_decide_proposals(commands) -> BatchClaimDecisionResult
  save_assessment(command) -> ProfileAssessmentRecord
  create_action_plan(command) -> ProfileActionPlanRecord
  apply_action_plan_item(item_id, *, expected_claim_version) -> ActionPlanItemRecord
  create_publication_selection(command) -> PublicationSelectionRecord
  profile_snapshot(workspace_id) -> ConfirmedProfileSnapshot
  ```

- [x] Make acceptance atomic: validate every referenced Evidence belongs to an immutable material version, append a ClaimVersion, update `current_confirmed_version_id`, and mark the proposal accepted in the same transaction. Support edited acceptance by recording the edited ClaimVersion and retaining its source Proposal relation.
- [x] Model Claim decision and evidence support independently: confirmed Claims may be `supported`, `conflicted`, or `unsupported`; a conflicting new proposal records a conflict edge and never overwrites the confirmed version.
- [x] Compute a deterministic `profile_version` from the ordered `(claim_id, current_version)` pairs; return it with every confirmed snapshot and reject stale Action Plans against it.
- [x] Return stable domain errors such as `profile_material_not_found`, `profile_evidence_mismatch`, `profile_proposal_already_decided`, `profile_claim_version_conflict`, and `profile_snapshot_changed`.
- [x] Run `cd backend && uv run pytest -q tests/test_profile_repository.py`. Expected: all repository invariant and concurrency tests pass.
- [x] Reviewer gate: use `PRAGMA foreign_key_check`; verify no repository update bypasses expected state/version predicates and no query omits `workspace_id` where cross-workspace IDs could be supplied.

## Task 3: Implement Private Content-Addressed Storage and Parsers

**Files:**

- Create: `backend/app/profile/storage.py`
- Create: `backend/app/profile/parsers.py`
- Test: `backend/tests/test_profile_storage.py`
- Test: `backend/tests/test_profile_parsers.py`

- [ ] Write failing tests for maximum upload size, allowed media types/extensions, duplicate bytes, filename traversal, symlinks, short writes, hash verification, PDF page locators, DOCX paragraph locators, Markdown line locators, empty/corrupt/encrypted documents, and redacted error messages.
- [ ] Implement a 10 MiB streaming upload limit and accept only PDF, DOCX, Markdown, and UTF-8 plain text. Detect type from validated extension plus parser success; never trust the browser's media type alone.
- [ ] Store bytes as `artifacts/profile/materials/blobs/<sha256-prefix>/<sha256>.<ext>` and extracted normalized UTF-8 text as `artifacts/profile/materials/text/<version_id>.txt` using fsync + atomic replace and `WorkspacePathPolicy`.
- [ ] Return parser segments as `ExtractedSegment(text, locator)` where locator is `{page}` for PDF, `{paragraph}` for DOCX, and `{lineStart,lineEnd}` for Markdown/text; normalize line endings without rewriting source bytes.
- [ ] Ensure duplicate content reuses the blob but creates a new immutable MaterialVersion record; deleting one version must not remove a blob still referenced by another version.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_storage.py tests/test_profile_parsers.py`. Expected: all storage, parser, corruption, and path-security tests pass.
- [ ] Reviewer gate: inspect failure paths for partial files and raw-content leakage; confirm exception strings/log records contain IDs and error codes only.

## Task 4: Add Material Lifecycle Services and Hidden Ingest Sessions

**Files:**

- Create: `backend/app/profile/service.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Test: `backend/tests/test_profile_material_service.py`
- Test: `backend/tests/test_agent_routes_v2.py`

- [ ] Write failing service tests for first upload, new version upload, duplicate content, retry after parse failure, archive/restore, primary selection, hidden Session creation, generic session-list filtering, generic detail denial, and restart recovery.
- [ ] Extend `SessionRecord`, `ProductRepository.create_session`, and `AgentSessionService.create` with `visibility`; make list queries default to `visibility='user'` and add an internal `include_system=True` path used only by Runtime services.
- [ ] Add `ProfileService.upload_material` and `add_material_version`: persist source bytes, create the immutable version, create a hidden `profile.ingest` system Session whose ID equals the version ID, and start an Execution with IDs/locators only and `project_input_message=False`.
- [ ] Make retry create a new Execution on the same hidden Session and immutable version. Refuse retry while one Execution is active; never create an upload/chat Message.
- [ ] Make archive/restore reversible and primary selection explicit. An archived material remains addressable by existing Evidence and Claims but is excluded from default lists and new assessment context.
- [ ] Add `profile: ProfileService` to `WorkspaceRuntime`, construct it from the shared connection/repository/execution service, and close no new standalone database handles.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_material_service.py tests/test_agent_routes_v2.py`. Expected: lifecycle tests pass and existing user sessions remain unchanged.
- [ ] Reviewer gate: query Runtime SQLite directly to verify one system Session per version, no user-visible Message, and no system Session returned by generic Agent endpoints.

## Task 5: Extend Tool Audit and Product Events for Safe Tool Visibility

**Files:**

- Modify: `backend/app/middleware/tool_policy_middleware.py`
- Modify: `backend/app/tools/audit.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `frontend/src/features/review/reviewTypes.ts`
- Test: `backend/tests/test_tool_policy_middleware.py`
- Test: `backend/tests/test_agent_routes_v2.py`

- [ ] Write failing tests for `agent.tool.started`, `agent.tool.completed`, and `agent.tool.failed`; assert payloads contain only `executionId`, `toolCallId`, `toolName`, purpose, status, result count, and error code, never raw arguments/results. Denials use `agent.tool.failed` with `tool_not_allowed` while the audit state is `denied`.
- [ ] Extend `ToolPolicyMiddleware` to audit denied calls, compute canonical SHA-256 input/result digests, persist `tool_call_id` and `agent_role`, and publish lifecycle Events through an injected safe projection callback.
- [ ] Add the three Event types to `ProductEventStream._allowed` and frontend event unions. Keep `ToolMessage` internal; do not project it into `agent_messages`.
- [ ] Preserve current middleware callers by making the Event projection dependency explicit in `build_default_middleware`; update every construction site and test fixture.
- [ ] Run `cd backend && uv run pytest -q tests/test_tool_policy_middleware.py tests/test_agent_routes_v2.py tests/test_approval_execution.py`. Expected: safe lifecycle Events and all prior Tool-policy behavior pass.
- [ ] Reviewer gate: inspect serialized Events and audits using sensitive sample arguments; confirm neither source text nor Tool result bodies are present.

## Task 6: Build Read-Only Profile Tools and Context Budgets

**Files:**

- Create: `backend/app/tools/profile_tools.py`
- Modify: `backend/app/tools/context.py`
- Modify: `backend/app/agents/context.py`
- Modify: `backend/app/middleware/middleware_stack.py`
- Test: `backend/tests/test_profile_tools.py`
- Test: `backend/tests/test_profile_tool_budget.py`

- [ ] Write failing tests for scope denial, workspace isolation, item/text limits, deterministic ordering, absent/archived records, repeated normalized arguments, six-call budget exhaustion, and two-identical-call no-progress handling.
- [ ] Implement exactly these read-only Tools:

  ```text
  list_personal_materials
  search_personal_materials
  read_personal_evidence
  get_profile_claims
  get_profile_claim_evidence
  compare_material_versions
  search_active_knowledge
  get_profile_publication_status
  ```

- [ ] Give every Tool a strict Pydantic input schema and bounded result schema. Return identifiers, locators, selected structured values, and short excerpts; cap lists at 50 and excerpts at the spec's context budget.
- [ ] Add `PROFILE_CHAT_BUDGET` with maximum six Tool calls per Execution and two calls for the same normalized `(tool_name,args)` fingerprint. On exhaustion, require answer/clarification/safe failure rather than another call.
- [ ] Keep write verbs out of tool names and functions. Add a structural test that the profile Tool module imports no repositories' mutation commands and exposes no `create/update/delete/publish/accept/apply` Tool.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_tools.py tests/test_profile_tool_budget.py`. Expected: bounded read-only behavior and loop termination tests pass.
- [ ] Reviewer gate: compare the exported Tool names with the R3 ADR/spec allowlist and confirm every result can be shown in audit-safe UI without exposing an entire source document.

## Task 7: Implement Structured Profile Agents and the Ingest Graph

**Files:**

- Create: `backend/app/agents/profile_contracts.py`
- Create: `backend/app/agents/profile_agents.py`
- Create: `backend/app/agents/prompts/profile_prompts.py`
- Create: `backend/app/graphs/profile_ingest.py`
- Create: `backend/app/graphs/profile_assess.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/infrastructure/checkpoints.py`
- Test: `backend/tests/test_profile_agents.py`
- Test: `backend/tests/test_profile_ingest_graph.py`
- Test: `backend/tests/test_checkpoint_serialization.py`

- [ ] Write failing Agent-spec tests asserting roles, structured outputs, prompts, no Tools for extraction/assessment, default `AgentState`, and explicit execution names/thread IDs.
- [ ] Define `ProfileExtractionOutput` as evidence-grounded candidate claims. Every candidate must include category, typed value, exact Evidence references, confidence, and rationale; reject any unknown Evidence ID before persistence.
- [ ] Implement `ProfileAgents.create` with roles `profile_extraction`, `profile_assessment`, `profile_chat`, and `profile_action_planner`; bind planner to `profile_assessment` for R3 and chat to `agent_chat`.
- [ ] Build `profile.ingest` as an explicit StateGraph:

  ```text
  START -> parse -> redact_for_model -> extract_evidence_candidates
        -> profile_extraction -> validate_and_persist_proposals -> END
  ```

- [ ] Publish deterministic Events `profile.ingest.parsing`, `profile.ingest.extracting`, and `profile.claims.proposed`; on failure persist parse/extraction status and a stable error code. Event payloads contain counts and IDs, not raw text.
- [ ] Use outer thread ID `<material_version_id>` and Agent thread ID `<material_version_id>:profile_extraction`; add only the new structured contracts required by safe checkpoint serialization.
- [ ] Extend `ProductionGraphFactory` explicitly for `profile.ingest`; inject repository/service callbacks through the existing factory and execution service instead of opening another connection in graph nodes.
- [ ] Build `profile.assess` as a separate explicit Graph that locks a Material/Claim snapshot, invokes `profile_assessment`, validates Evidence references, idempotently saves Assessment/Proposal records, and projects a typed card only after the transaction succeeds.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_agents.py tests/test_profile_ingest_graph.py tests/test_checkpoint_serialization.py`. Expected: extraction proposals persist, invalid evidence is rejected, failure is retryable, and Agent specs have no write Tools.
- [ ] Reviewer gate: inspect graph state/checkpoints to confirm they contain orchestration IDs and structured output only—not source bytes, normalized full text, or domain truth copies.

## Task 8: Expose R3.1 Material and Evidence APIs

**Files:**

- Create: `backend/app/schemas/profile.py`
- Create: `backend/app/api/routes_profile.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_profile_material_api.py`

- [ ] Write failing API tests for the exact R3 material/version endpoints, `202 Accepted` upload payload, multipart validation, background Execution resource, version detail, Evidence pagination, archive/restore/primary actions, retry, idempotency/version headers, workspace isolation, and stable error envelopes.
- [ ] Implement:

  ```text
  POST /api/workspaces/{workspaceId}/profile/materials
  GET  /api/workspaces/{workspaceId}/profile/materials
  POST /api/profile/materials/{materialId}/versions
  GET  /api/profile/materials/{materialId}/versions
  GET  /api/profile/material-versions/{versionId}
  POST /api/profile/material-versions/{versionId}/retry
  POST /api/profile/materials/{materialId}/archive
  POST /api/profile/materials/{materialId}/restore
  POST /api/profile/materials/{materialId}/primary
  ```

- [ ] Return camelCase resources with parse/extraction stages, safe filenames/metadata, Evidence locators/excerpts, proposal counts, hidden ingest Execution status, and retry capability. Never return `source_path`, `text_path`, full normalized text, or system Session IDs as navigable Agent sessions.
- [ ] Map parser/storage/domain failures to 400/404/409/413/422 with `code`, user-facing Chinese `message`, and retryability; unexpected failures remain redacted 500 responses.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_material_api.py`. Expected: all material/version/Evidence API contract tests pass.
- [ ] Reviewer gate: snapshot representative JSON and confirm it matches the frontend type map and privacy constraints.

## Task 9: Build the Material Version and Evidence Frontend

**Files:**

- Create: `frontend/src/features/profile/profileTypes.ts`
- Create: `frontend/src/features/profile/profileApi.ts`
- Create: `frontend/src/features/profile/ProfilePage.tsx`
- Create: `frontend/src/features/profile/ProfileOverview.tsx`
- Create: `frontend/src/features/profile/ResumeVersions.tsx`
- Create: `frontend/src/features/profile/EvidenceDetail.tsx`
- Create: `frontend/src/features/profile/ProfileStatusBadge.tsx`
- Modify: `frontend/src/shared/api/client.ts`
- Modify: `frontend/src/app/navigation/navigationItems.ts`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfilePage.test.tsx`
- Test: `frontend/src/features/profile/ResumeVersions.test.tsx`
- Test: `frontend/src/features/profile/EvidenceDetail.test.tsx`
- Test: `frontend/src/shared/api/client.test.ts`

- [ ] Write failing component tests for empty/loading/error states, drag/drop and picker upload, size/type validation, deterministic ingest stages, retry, version selection, archive/restore/primary actions, Evidence locator display, keyboard navigation, and 390 px layout behavior.
- [ ] Add `apiUpload<T>(path, formData)` without setting a JSON `Content-Type`; preserve the existing error-envelope behavior and abort support.
- [ ] Add `/profile` as a top-level workspace route and `UserRound` navigation item. Keep `/review` as the default route for R3 unless a later product decision changes onboarding.
- [ ] Implement the overview, versions table, and Evidence detail according to the committed reference images. Use current `--color-*`, spacing, radius, typography, focus, and motion tokens only.
- [ ] Show stage text `上传 -> 文本提取 -> 脱敏 -> Claim 提取 -> 等待审核`, with failed-stage reason and retry action. Do not present upload as a chat conversation.
- [ ] Keep desktop information density while collapsing tables into labeled cards below 768 px; keep primary actions reachable and touch targets at least 44 px.
- [ ] Run `cd frontend && npm test -- --run src/shared/api/client.test.ts src/features/profile/ProfilePage.test.tsx src/features/profile/ResumeVersions.test.tsx src/features/profile/EvidenceDetail.test.tsx`. Expected: all focused UI/API tests pass.
- [ ] Run `cd frontend && npm run typecheck`. Expected: zero TypeScript errors.
- [ ] Reviewer gate: compare 390/768/1024/1440 screenshots with the three committed material/evidence references; record deltas in the R3 verification document.

## Task 10: Implement Claim Proposal Review and Deletion Impact Analysis

**Files:**

- Modify: `backend/app/profile/repository.py`
- Modify: `backend/app/profile/service.py`
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Test: `backend/tests/test_profile_claim_service.py`
- Test: `backend/tests/test_profile_claim_api.py`

- [ ] Write failing tests for claim/proposal list/detail/version history, accept/edit-and-accept/reject idempotency, partial batch receipts, evidence traceability, conflicting proposals, stale decisions, delete-preview dependency counts, unsupported retention, and selection-protected permanent deletion.
- [ ] Implement Claim read APIs and proposal decision APIs:

  ```text
  GET  /api/workspaces/{workspaceId}/profile/claims
  GET  /api/profile/claims/{claimId}
  GET  /api/profile/claims/{claimId}/versions
  POST /api/profile/claim-proposals/{proposalId}/accept
  POST /api/profile/claim-proposals/{proposalId}/reject
  POST /api/profile/claim-proposals/batch-decide
  ```

- [ ] Add deletion APIs from the spec. `deletion-preview` returns `deletionPlanId`, material version, expiry, affected Evidence/Claims, Claims that would become unsupported, publication selections, and active knowledge publication. `permanent-delete` requires the unexpired plan, exact per-Claim choices, Active Knowledge revocation choice, idempotency key, and expected material version.
- [ ] For permanent deletion, let the user choose per affected confirmed Claim: delete it, retain it as `unsupported`, or cancel the deletion. Require explicit Active Knowledge revocation or cancel. Revoke dependent publication first, tombstone Evidence without recoverable sensitive text, delete unreferenced private artifacts last, and return item-level receipts. If a stage fails, preserve sufficient state for safe retry and do not claim completion.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_claim_service.py tests/test_profile_claim_api.py`. Expected: claim review and deletion-safety tests pass.
- [ ] Reviewer gate: simulate concurrent acceptance and deletion; verify stale operations return 409 and no accepted Claim references missing Evidence.

## Task 11: Build the Claim Review Frontend

**Files:**

- Create: `frontend/src/features/profile/ClaimReview.tsx`
- Create: `frontend/src/features/profile/ClaimDiff.tsx`
- Create: `frontend/src/features/profile/DeletionImpactDialog.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ClaimReview.test.tsx`
- Test: `frontend/src/features/profile/DeletionImpactDialog.test.tsx`

- [ ] Write failing tests for filters, conflict badges, side-by-side diff, Evidence navigation, single and batch decisions, partial selection, stale 409 refresh, deletion preview, typed confirmation, focus trap/return, and non-color-only status cues.
- [ ] Implement the Claim review workspace from the committed reference: category/status filters, proposal queue, current-vs-proposed diff, Evidence citations, rationale, and explicit accept/reject controls.
- [ ] Keep batch decisions visible as a pending selection until the API succeeds; on conflict refresh the affected Claim and preserve unaffected selections.
- [ ] Implement a destructive-action dialog that displays dependency counts and receipts, requires typed confirmation, and clearly distinguishes archive from permanent deletion.
- [ ] Run `cd frontend && npm test -- --run src/features/profile/ClaimReview.test.tsx src/features/profile/DeletionImpactDialog.test.tsx`. Expected: all focused interaction/accessibility tests pass.
- [ ] Reviewer gate: keyboard-only complete the accept/reject and delete-preview flows; compare the Claim screen with `claim-review-reference.png`.

## Task 12: Implement Assessment, Constrained Planning, and Action Receipts

**Files:**

- Modify: `backend/app/profile/models.py`
- Modify: `backend/app/profile/repository.py`
- Modify: `backend/app/profile/service.py`
- Test: `backend/tests/test_profile_assessment.py`
- Test: `backend/tests/test_profile_action_plans.py`

- [ ] Write failing tests for assessment on confirmed snapshots only, evidence citation validation, deterministic assessment persistence, simple single-change commands, multi-item plan creation, confirm/cancel/retry, stale base profile version, per-item optimistic locking, partial failure, and idempotent receipts.
- [ ] Implement assessment persistence with strengths, gaps, risks, evidence-backed recommendations, and proposal candidates. Assessment text never becomes a confirmed Claim automatically.
- [ ] Define the constrained Plan-and-Execute operations accepted by deterministic services:

  ```text
  propose_claim_create
  propose_claim_update
  propose_claim_reject
  propose_material_derived_version
  set_publication_selection
  request_reassessment
  ```

- [ ] Validate an Agent-produced plan into immutable ordered items with before/after diff and expected Claim versions. Unsupported verbs or missing Evidence invalidate the whole plan before confirmation.
- [ ] Implement resume polishing as `propose_material_derived_version`: create an immutable `source_type='derived_draft'` version linked by `derived_from_version_id`; it remains a draft until explicit confirmation makes it the material's current version.
- [ ] Apply confirmed items sequentially through `ProfileService`; persist `completed`, `failed`, or `skipped` per item plus a receipt. Retry only failed/unapplied items after revalidation; never silently replay completed mutations.
- [ ] Publish safe Events `profile.action_plan.created` and `profile.action_plan.item_completed` with IDs, operation, ordinal, and status only.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_assessment.py tests/test_profile_action_plans.py`. Expected: assessment and constrained plan state-machine tests pass.
- [ ] Reviewer gate: inspect every operation dispatch and confirm there is no generic method/tool invocation, arbitrary Python/code execution, free-form path, or publish mutation.

## Task 13: Build `profile.manage` and the Bounded Chat Tool Loop

**Files:**

- Create: `backend/app/graphs/profile_manage.py`
- Modify: `backend/app/agents/profile_contracts.py`
- Modify: `backend/app/agents/profile_agents.py`
- Modify: `backend/app/agents/prompts/profile_prompts.py`
- Modify: `backend/app/application/graph_factory.py`
- Modify: `backend/app/application/execution_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Test: `backend/tests/test_profile_manage_graph.py`
- Test: `backend/tests/test_profile_chat_tool_loop.py`

- [ ] Write failing graph tests for intent classification, simple Q&A, assessment, single proposal change, multi-item plan, clarification, cancellation, restart recovery, thread IDs, Tool allowlists, Tool budgets, and invalid Agent output.
- [ ] Build `profile.manage` with deterministic routing around explicit Agent nodes and the standalone assessment subgraph:

  ```text
  assemble confirmed snapshot and focus
    -> classify intent
       -> profile_chat (read-only Tool loop)
       -> profile.assess -> profile_assessment (structured, no Tools)
       -> direct single proposal validation
       -> profile_action_planner (structured plan, no Tools by default)
    -> persist proposal/assessment/plan
    -> project safe response/receipt
  ```

- [ ] Use thread IDs `<session_id>` for the outer graph, `<session_id>:profile_chat`, `<session_id>:profile_assessment`, and `<execution_id>:profile_action_planner`. Planner state does not survive across Executions except as the persisted domain Action Plan.
- [ ] Assemble current Material/Claim/Proposal focus from `profile_agent_context`, not from old chat messages. Use existing context compaction for conversation history; Tool results and domain snapshots are rehydratable context and must not be summarized into domain truth.
- [ ] Allocate Tools by classified intent and intersect them with `AgentContext.allowed_tools/allowed_scopes`. Denied or exhausted calls produce safe assistant guidance and a terminal Execution state.
- [ ] Project assistant text, assessment cards, action-plan cards, diffs, receipts, and safe Tool stages using typed Message/Event kinds; never project raw structured prompts or ToolMessage content.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_manage_graph.py tests/test_profile_chat_tool_loop.py tests/test_agent_context_assembly.py`. Expected: all routing, budget, context, and recovery tests pass.
- [ ] Reviewer gate: inspect model inputs for one long session and prove current profile facts come from fresh domain projection while conversational history follows existing compaction thresholds.

## Task 14: Expose Profile Manage, Assessment, and Action Plan APIs

**Files:**

- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Test: `backend/tests/test_profile_manage_api.py`
- Test: `backend/tests/test_profile_action_plan_api.py`

- [ ] Write failing API tests for creating/listing profile sessions, starting/cancelling Executions, SSE replay/reconnect, assessment resources, plan detail, confirm/cancel/retry, stale conflicts, and restart recovery.
- [ ] Reuse generic Agent Session/Execution/Event endpoints for user-visible `profile.manage` sessions, but add profile-specific creation validation and resource aggregation so callers cannot create `profile.ingest` sessions.
- [ ] Implement Action Plan endpoints:

  ```text
  GET  /api/profile/action-plans/{planId}
  POST /api/profile/action-plans/{planId}/confirm
  POST /api/profile/action-plans/{planId}/cancel
  POST /api/profile/action-plans/{planId}/retry
  ```

- [ ] Return typed card payloads with base/current profile versions, item diffs, Evidence links, per-item status, receipts, and retryability. Use 409 for stale snapshot/version conflicts.
- [ ] Ensure SSE `Last-Event-ID` replay includes profile Tool/action events in order and cancellation reaches a terminal Event without orphaning an active Execution.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_manage_api.py tests/test_profile_action_plan_api.py tests/test_agent_routes_v2.py`. Expected: profile manage API, SSE, cancel, and recovery tests pass.
- [ ] Reviewer gate: restart the application between plan creation and confirmation, then confirm/retry through the API and verify identical persisted receipts.

## Task 15: Build the Profile Agent Workspace Frontend

**Files:**

- Create: `frontend/src/features/profile/ProfileAgentWorkspace.tsx`
- Create: `frontend/src/features/profile/ProfileConversation.tsx`
- Create: `frontend/src/features/profile/ProfileActionPlanCard.tsx`
- Create: `frontend/src/features/profile/ProfileAssessmentCard.tsx`
- Create: `frontend/src/features/profile/ProfileToolStage.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/features/agent/useAgentEvents.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfileAgentWorkspace.test.tsx`
- Test: `frontend/src/features/profile/ProfileActionPlanCard.test.tsx`
- Test: `frontend/src/features/profile/ProfileToolStage.test.tsx`

- [ ] Write failing tests for session list/create, context focus, streaming reply, reconnect/replay, safe Tool stages, assessment card, Action Plan diff, confirm/cancel/retry, stale conflict refresh, stop control, reduced motion, and mobile composer behavior.
- [ ] Implement the committed Agent workspace reference with a compact session rail, current profile focus, conversation timeline, evidence-linked cards, and persistent composer/stop control.
- [ ] Render Tool activity from safe lifecycle Events as stages (`正在读取已确认画像`, `已比较两个版本`) and expose IDs/status/duration only in detail. Never display raw Tool JSON.
- [ ] Render Action Plans as user-confirmable ordered diffs with base-version warning, item status, receipt, and retry controls. Do not imply that an unconfirmed plan has changed the profile.
- [ ] Reuse the existing SSE reconnect cursor and cancellation behavior; extend rather than fork `useAgentEvents`.
- [ ] Run `cd frontend && npm test -- --run src/features/profile/ProfileAgentWorkspace.test.tsx src/features/profile/ProfileActionPlanCard.test.tsx src/features/profile/ProfileToolStage.test.tsx`. Expected: focused Agent workspace tests pass.
- [ ] Run `cd frontend && npm run typecheck`. Expected: zero TypeScript errors.
- [ ] Reviewer gate: compare desktop/mobile screenshots with `profile-agent-reference.png`; verify keyboard focus after stream completion, cancel, dialog close, and retry.

## Task 16: Complete Selective Knowledge Publication and Revocation

**Files:**

- Modify: `backend/app/knowledge/drafts.py`
- Modify: `backend/app/knowledge/publication.py`
- Modify: `backend/app/services/search_index.py`
- Modify: `backend/app/profile/service.py`
- Modify: `backend/app/schemas/profile.py`
- Modify: `backend/app/api/routes_profile.py`
- Test: `backend/tests/test_profile_publication.py`
- Test: `backend/tests/test_search_index.py`
- Test: `backend/tests/test_publication_service.py`

- [ ] Write failing tests for default-unselected Claims, confirmed-only selection, deterministic profile Markdown/frontmatter, publication approval reuse, active-file hash conflict, index failure/repair, revocation, revoke retry, rescan exclusion, and R4-R6 confirmed-context queries.
- [ ] Build one `profile` knowledge draft from an immutable, versioned PublicationSelection containing explicitly selected, currently confirmed Claim versions and excluded sensitive fields. Include stable Claim IDs/versions and Evidence provenance in frontmatter, but include only the user-approved public summary in the Markdown body.
- [ ] Reuse the existing HITL `knowledge.publish` approval flow; profile code may create/update a draft and request publication but cannot call file/index mutation from an Agent node or Tool.
- [ ] Add `delete_document(conn, document_id)` to remove both manifest and FTS rows transactionally. Implement `PublicationService.revoke` with expected published hash, recoverable states, atomic active-file removal, index cleanup, Event projection, and retained Runtime history.
- [ ] Implement publication selection/status/revoke APIs under the profile router and a confirmed-profile context API for R4-R6. The context response includes only accepted Claims and requested categories; it excludes raw source text, rejected/pending proposals, and unselected publication state.
- [ ] Ensure material deletion coordinates revocation before evidence destruction and that Vault rescan cannot resurrect a revoked document.
- [ ] Run `cd backend && uv run pytest -q tests/test_profile_publication.py tests/test_search_index.py tests/test_publication_service.py`. Expected: publish, repair, revoke, and downstream context tests pass.
- [ ] Reviewer gate: inspect the active Markdown, index rows, Runtime history, and post-revoke filesystem; confirm the private source/evidence content was never copied into the Vault.

## Task 17: Build Publication Scope UI and Cross-Layer Acceptance

**Files:**

- Create: `frontend/src/features/profile/PublicationScope.tsx`
- Modify: `frontend/src/features/profile/ProfilePage.tsx`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/PublicationScope.test.tsx`
- Test: `frontend/src/features/profile/ProfileFlow.test.tsx`
- Create/Update: `docs/verification/r3-personal-profile-agent.md`

- [ ] Write failing frontend tests for confirmed-only selection, preview, approval handoff, published status, external-change conflict, revoke confirmation, retry, empty state, and non-selected Claim exclusion.
- [ ] Implement the publication scope screen from the committed reference: category grouping, Claim/version/Evidence summary, explicit checkboxes, publication preview, status timeline, and revoke action.
- [ ] Add a cross-layer frontend flow test covering upload -> ingest status -> Evidence -> proposal acceptance -> assessment/chat -> Action Plan confirmation -> selective publication -> revoke.
- [ ] Run the complete frontend suite once after cross-layer integration: `cd frontend && npm test -- --run`. Expected: all tests pass.
- [ ] Run frontend production verification: `cd frontend && npm run typecheck && npm run build`. Expected: zero type errors and successful production build.
- [ ] Run the complete backend suite once after cross-layer integration: `cd backend && uv run pytest -q`. Expected: all tests pass.
- [ ] Start the local app and complete one minimal browser happy path before documentation: upload one Markdown resume, accept one Claim, ask one profile question, select/publish one Claim, and revoke it. Record Event IDs, receipts, screenshots, and observed limitations in `docs/verification/r3-personal-profile-agent.md`.
- [ ] Reviewer gate: compare all six implemented screens at 390/768/1024/1440 against the committed references; verify WCAG contrast, visible focus, semantic headings/landmarks, error announcements, reduced motion, and 44 px touch targets.

## Task 18: Final Documentation, Ownership Pack, and Stage Gate

**Files:**

- Update: `task_plan.md`
- Update: `findings.md`
- Update: `progress.md`
- Update: `docs/verification/r3-personal-profile-agent.md`
- Create: `docs/learning/r3-personal-profile-agent/README.md`
- Create: `docs/learning/r3-personal-profile-agent/01-product-map.md`
- Create: `docs/learning/r3-personal-profile-agent/02-code-reading-guide.md`
- Create: `docs/learning/r3-personal-profile-agent/03-core-flows.md`
- Create: `docs/learning/r3-personal-profile-agent/04-risk-boundaries.md`
- Create: `docs/learning/r3-personal-profile-agent/05-practice.md`
- Create: `docs/learning/r3-personal-profile-agent/06-acceptance-checklist.md`

- [ ] Reshape `docs/verification/r3-personal-profile-agent.md` into the final user guide: prerequisites, six screen flows, expected states, retry/recovery, publication/revocation, known R3.5 boundary, and complete browser acceptance checklist.
- [ ] Generate the seven-file local learning pack with the formal risk profile for a cross-layer Agent/state/security stage; compare depth and structure with the previous same-profile stage.
- [ ] Run one complete browser acceptance pass from a clean workspace covering all 14 scenarios in the R3 spec: DOCX ingest; new-version compare/primary; accept/edit/reject; conflict preservation; assessment; cross-version chat/Tool stage; selected plan execution; stop/refresh; partial retry; sensitive-excluded HITL publication; revoke/search removal; archive/restore/delete preview; Session deletion decoupling; desktop/390 px layout. Re-run only affected scenarios if fixes are needed.
- [ ] Run fresh real-Provider acceptance for structured extraction, assessment, bounded Tool chat, and structured Action Plan; capture provider/model IDs, timestamps, result status, and redacted evidence without storing prompts, resume text, or Provider responses.
- [ ] Run the final backend regression: `cd backend && uv run pytest -q`. Expected: all tests pass.
- [ ] Run the final frontend verification: `cd frontend && npm test -- --run && npm run typecheck && npm run build`. Expected: all tests and build pass.
- [ ] Run `python3 scripts/check_stage_docs.py --verification docs/verification/r3-personal-profile-agent.md --learning docs/learning/r3-personal-profile-agent/ --plan docs/superpowers/plans/2026-07-20-r3-personal-profile-agent.md`. Expected: documentation gate passes with no unchecked browser acceptance or inconsistent evidence.
- [ ] Update root planning files with product status, maturity boundary, ownership status, next task, and non-blocking exercise. Confirm `docs/my_idea.md` is unchanged and only formal documents under `docs/superpowers/` are candidates for commit.
- [ ] Reviewer gate: compare every acceptance criterion in `docs/superpowers/specs/2026-07-20-r3-personal-profile-agent-design.md` with code/tests/evidence and record any intentionally deferred item under R3.5 rather than silently omitting it.

---

## Milestone Checkpoints

- **R3.1 complete after Tasks 1-9:** private material/version/Evidence ingestion works, hidden system Sessions are not user-visible, safe Tool Events exist, and material/evidence UI is usable.
- **R3.2 complete after Tasks 10-11:** evidence-backed Claim proposals can be reviewed, accepted/rejected, traced, batch-decided, and safely invalidated/deleted.
- **R3.3 complete after Tasks 12-15:** assessment, bounded read-only chat, constrained planning, receipts, cancellation, retry, and profile Agent UI work across restart.
- **R3.4 complete after Tasks 16-18:** selected confirmed Claims publish through HITL, revoke safely, feed R4-R6 confirmed context, and pass full product/documentation acceptance.

## Explicit Non-Goals for This Plan

- Browser profile import, GitHub/LinkedIn connectors, OCR, image resumes, arbitrary URL ingestion, and general web search.
- Automatic acceptance of extracted facts, automatic publication, autonomous background task pursuit, arbitrary write Tools, or a free ReAct mutation loop.
- General checkpoint browsing, forked sessions, replay-based domain rollback, or user-visible Time Travel.
- Cross-device sync, multi-user permissions, remote object storage, or organization-wide profile sharing.
