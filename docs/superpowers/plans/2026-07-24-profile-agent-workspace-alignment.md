# Profile Agent Workspace Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Profile Agent with the established R2 conversation workspace while extracting reusable Agent session, message, composer, context-panel, and lifecycle contracts.

**Architecture:** Keep R2 business components unchanged as the golden reference. Add generic session title/lifecycle APIs to the existing Runtime, introduce focused shared frontend primitives, and rebuild only `ProfileAgentWorkspace` as a session-list/selected-session state machine. Profile-specific scope and proposal content enter through slots; durable Session/Execution state remains authoritative over SSE.

**Tech Stack:** React 18, TypeScript, TanStack Query, React Markdown, FastAPI, Pydantic, SQLite Runtime repository, LangChain Agent middleware.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-24-agent-conversation-workspace-guidelines.md`.
- Do not change R2 question-curation business behavior in this slice.
- Do not add a second page-specific viewport calculation.
- Do not add a second provider call solely to block the first answer on title generation.
- One Session allows at most one active Execution; different Sessions remain independent.
- Use targeted tests and one measured browser pass; do not repeat full regression unless a shared Runtime failure appears.
- Do not commit until the user explicitly requests a local commit.

---

### Task 1: Shared Session Title and Archive Contract

**Files:**
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/application/session_service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/api/routes_agent.py`
- Modify: `backend/app/api/routes_profile.py`
- Modify: `frontend/src/features/agent/agentTypes.ts`
- Modify: `frontend/src/features/agent/agentApi.ts`
- Modify: `frontend/src/features/profile/profileApi.ts`
- Test: `backend/tests/test_agent_session_api.py`
- Test: `backend/tests/test_profile_agent_api.py`

**Interfaces:**
- Produces `PATCH /api/agent/sessions/{sessionId}` with `UpdateSessionTitleCommand(workspaceId, title)`.
- Produces `GET /api/workspaces/{workspaceId}/profile/sessions?deletedOnly=true`.
- Produces frontend `renameAgentSession`, `restoreAgentSession`, and archived Profile session queries.

- [ ] Add API tests proving blank/overlong titles fail, successful rename sets a user-owned title, archived Profile sessions are isolated by Workspace and kind, running sessions cannot archive, and restore returns the session.
- [x] Add `ProductRepository.update_session_title(session_id, title)` and deleted-only list support without changing the default active list query.
- [x] Add `AgentSessionService.rename`, publish `session.renamed`, and validate Workspace ownership in `AgentApplication`.
- [x] Stop forcing `"简历助手对话"` in `create_profile_session`; let `SessionTitleMiddleware` own placeholder-to-generated compare-and-set.
- [x] Add frontend API functions and `deletedAt` typing.
- [x] Run:

```bash
backend/.venv/bin/pytest -q \
  backend/tests/test_agent_session_api.py \
  backend/tests/test_profile_agent_api.py
```

Expected: targeted session and Profile Agent API tests pass.

### Task 2: Shared Agent Conversation Primitives

**Files:**
- Create: `frontend/src/shared/agent/AgentWorkspaceShell.tsx`
- Create: `frontend/src/shared/agent/AgentMessage.tsx`
- Create: `frontend/src/shared/agent/AgentComposer.tsx`
- Create: `frontend/src/shared/agent/AgentProcessCard.tsx`
- Create: `frontend/src/shared/agent/agentPresentation.ts`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/shared/agent/AgentWorkspaceShell.test.tsx`
- Test: `frontend/src/shared/agent/AgentComposer.test.tsx`
- Test: `frontend/src/shared/agent/AgentMessage.test.tsx`

**Interfaces:**
- Produces `AgentWorkspaceShell({ header, conversation, aside, asideOpen, onAsideOpenChange })`.
- Produces `AgentMessage` with Markdown, copy action, Beijing timestamp, pending state, and domain-card children.
- Produces `AgentComposer` with prompt fill, model/reasoning selectors, `44–128px` textarea, send and stop actions.
- Produces `AgentProcessCard` that collapses terminal stages and hides internal Tool names.

- [ ] Write component tests for labelled regions, fixed composer semantics, prompt-fill-without-submit, Markdown rendering, copy, process-card terminal collapse, and accessible aside controls.
- [x] Implement primitives using the existing R2 class/token behavior; do not import Profile or Review domain types.
- [x] Add CSS only under `.agent-workspace-*` and `.agent-conversation-*`; preserve current `.curation-*` behavior.
- [x] Run:

```bash
cd frontend
npm test -- --run \
  src/shared/agent/AgentWorkspaceShell.test.tsx \
  src/shared/agent/AgentComposer.test.tsx \
  src/shared/agent/AgentMessage.test.tsx
npx tsc --noEmit
```

Expected: shared component tests and TypeScript pass.

### Task 3: Profile Conversation Record Landing

**Files:**
- Create: `frontend/src/features/profile/ProfileSessionList.tsx`
- Create: `frontend/src/features/profile/ProfileSessionRecycleBin.tsx`
- Create: `frontend/src/features/profile/ProfileSessionTitle.tsx`
- Modify: `frontend/src/features/profile/ProfileAgentWorkspace.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfileAgentWorkspace.test.tsx`

**Interfaces:**
- Consumes Task 1 session lifecycle APIs.
- Produces list and selected-session states while keeping filter/search/scroll state in the mounted workspace.
- `ProfileSessionTitle` performs inline rename and returns focus to the rename trigger.

- [x] Replace the permanent left session column with a landing page containing new conversation, search, “全部 / 正在运行 / 需要处理”, archive, and recycle-bin actions.
- [x] Show the selected session as a separate workspace with “返回对话记录”, title, rename, latest execution status, and aside trigger.
- [x] Disable archive for a running session and direct the user back to that session.
- [x] Restore archived sessions and reserve permanent deletion for the recycle bin with explicit Profile-data boundary copy.
- [ ] Test landing/open/back, deterministic filters, rename, archive/restore, running guard, and empty search copy.
- [x] Run:

```bash
cd frontend
npm test -- --run src/features/profile/ProfileAgentWorkspace.test.tsx
```

Expected: Profile session navigation and lifecycle tests pass.

### Task 4: Profile Conversation and Context Rail

**Files:**
- Modify: `frontend/src/features/profile/ProfileAgentWorkspace.tsx`
- Rewrite: `frontend/src/features/profile/ProfileConversation.tsx`
- Modify: `frontend/src/features/profile/ProfileContextScope.tsx`
- Create: `frontend/src/features/profile/ProfileAgentContextPanel.tsx`
- Modify: `frontend/src/features/profile/ProfileToolStage.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/features/profile/ProfileAgentWorkspace.test.tsx`
- Test: `frontend/src/features/profile/ProfileConversation.test.tsx`

**Interfaces:**
- Consumes Task 2 shared primitives.
- Uses `listProviders()` and `startAgentExecution(sessionId, input, configuration)`.
- Sends `focus.categories` with each Execution and initializes model/reasoning from the latest Execution snapshot.
- Produces Profile slots for proposal, assessment, Action Plan, scope, privacy boundary and pending count.

- [x] Render persisted and streaming responses with shared Markdown messages; structured planning streams remain hidden behind a user-facing process card.
- [x] Move scope selection into the right rail and keep only a compact summary in the conversation header.
- [x] Build the rail in confirmed order: reference scope, privacy boundary, pending products, execution status, collapsed technical details.
- [x] Use the shared composer with model/reasoning selection, prompt fill without auto-submit, send, stop, and clear unavailable-model error.
- [x] Group Tool events by Execution into one user-facing process card; do not display raw Tool/Event identifiers.
- [x] Implement bottom-aware streaming: follow only near the bottom and show “有新回复，回到底部” after the user scrolls away.
- [ ] Test Markdown, model configuration payload, durable-terminal-over-SSE, context scope payload, non-submitting prompts, process grouping, stop binding, proposal navigation and failed recovery copy.
- [x] Run:

```bash
cd frontend
npm test -- --run \
  src/features/profile/ProfileAgentWorkspace.test.tsx \
  src/features/profile/ProfileConversation.test.tsx
npx tsc --noEmit
```

Expected: Profile Agent component tests and TypeScript pass.

### Task 5: Responsive Workbench and Acceptance Evidence

**Files:**
- Modify: `frontend/src/app/global.css`
- Modify: `docs/verification/r3-personal-profile-agent.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes Tasks 1–4.
- Produces measured browser evidence and the handoff checklist.

- [ ] Verify session landing and selected conversation at `390 / 768 / 1024 / 1200 / 1440`.
- [ ] Measure document height, message scroll owner, aside scroll owner and composer visibility; no Agent workspace may extend below the available Profile tab area.
- [ ] Verify long Markdown, empty conversation, running, stopped, failed, proposal card, aside collapse/drawer, rename, archive and restore without sending a real model request.
- [ ] Run:

```bash
backend/.venv/bin/python -m compileall -q backend/app
cd frontend && npx tsc --noEmit
git diff --check
```

Expected: all commands exit zero.

- [ ] Record the maturity boundary: Profile aligns to the shared contract; R2 remains the golden implementation and is not structurally migrated in this slice.
- [ ] Do not commit until the user requests a local commit.

## Self-Review

- Spec coverage: product structure, responsive rail, messages, scroll, title/rename, archive/restore, concurrency, state ownership, model/scope snapshots, recovery and acceptance all map to Tasks 1–5.
- Placeholder scan: no deferred interface or undefined behavior remains in this delivery plan.
- Type consistency: Task 1 API names are consumed by Task 3; Task 2 primitives are domain-neutral and consumed by Task 4.
- Execution choice: inline execution in the existing user-selected worktree; repository rules prohibit unnecessary subagents.
