# 后台 Agent 可见性与模型批量设置实施计划

> **Implementation workflow:** Use `superpowers:executing-plans` to implement this cross-layer plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 让质量检查和简历画像整理成为可追踪的后台 Agent 运行，为运行中任务提供全局导航角标，并支持一次设置全部任务模型。

**Architecture:** 控制面把“能否由用户直接创建”和“是否默认出现在运行中心”拆成独立属性。质量检查通过共享 `AgentExecutionService` 创建 `quality.evaluate` 系统 Execution，再在后台执行现有评估逻辑；前端根据该 Execution 和模型 Operation 展示真实阶段。全局导航复用运行中心快照与 SSE 计算当前工作区活动数，设置页复用既有 replace-all API 完成批量绑定。

**Tech Stack:** FastAPI、SQLite、现有 Agent Runtime/Trace、React、TanStack Query、Zod、Vitest、pytest。

## Global Constraints

- 系统 Agent 必须保持 `user_creatable=False`，不得因为默认可见而开放直接创建入口。
- 质量检查不得伪造百分比，只展示可由运行与 Operation 事实推导的阶段。
- 导航角标只统计当前工作区默认可见的 `running` 任务；0 时隐藏。
- 模型批量设置必须继续通过现有 replace-all API 原子保存全部 `ModelRole`。
- 不修改或提交 `docs/my_idea.md`。

---

### Task 1: 默认可见的系统 Agent

**Files:**
- Modify: `backend/app/agents/definition_registry.py`
- Modify: `backend/app/observability/service.py`
- Test: `backend/tests/test_agent_observability_registry.py`
- Test: `backend/tests/test_agent_observability_service.py`

**Interfaces:**
- Produces: `AgentDefinition.run_center_default_visible: bool`
- Consumes: existing `system`, `run_center_visible`, `includeSystemAgents` filters.

- [x] **Step 1: Write failing registry and service tests**

```python
assert AGENT_DEFINITIONS["profile.ingest"].system is True
assert AGENT_DEFINITIONS["profile.ingest"].run_center_default_visible is True
assert service.list_executions().items[0].graph_id == "profile.ingest"
```

- [x] **Step 2: Run targeted tests and confirm failure**

Run: `uv run pytest -q tests/test_agent_observability_registry.py tests/test_agent_observability_service.py`

- [x] **Step 3: Add the independent default-visibility field and filtering rule**

```python
if registration.system and not include_system_agents:
    if not registration.run_center_default_visible:
        return False
```

- [x] **Step 4: Mark `profile.ingest`, `profile.assess`, and `quality.evaluate` default-visible while preserving `system=True`**

- [x] **Step 5: Re-run targeted backend tests**

### Task 2: Asynchronous quality-check Execution and real progress

**Files:**
- Modify: `backend/app/evaluation/service.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/api/routes_agent_evaluations.py`
- Modify: `backend/app/schemas/evaluation.py`
- Modify: `frontend/src/features/evaluation/evaluationApi.ts`
- Modify: `frontend/src/features/evaluation/evaluationTypes.ts`
- Modify: `frontend/src/features/evaluation/EvaluationLabPage.tsx`
- Modify: `frontend/src/features/evaluation/evaluation.css`
- Test: `backend/tests/test_agent_judge_service.py`
- Test: `backend/tests/test_agent_evaluation_routes.py`
- Test: `frontend/src/features/evaluation/EvaluationLabPage.test.tsx`

**Interfaces:**
- Produces: `AgentEvaluationService.start_manual_evaluation(...) -> ExecutionRecord`
- Produces: `POST /api/agent-evaluations/runs` response `{ judgeExecutionId, sourceExecutionId }` with HTTP 202.
- Consumes: `AgentExecutionService.prepare()` and `run_background()`.

- [x] **Step 1: Add failing API/service tests for immediate accepted response and visible `quality.evaluate` run**

```python
started = await service.start_manual_evaluation("source-run", idempotency_key="manual-123")
assert started.status == "running"
assert product_repository.get_session(started.session_id).kind == "quality.evaluate"
```

- [x] **Step 2: Run targeted backend tests and confirm failure**

- [x] **Step 3: Create a hidden, non-user-creatable quality session and a shared-runtime Execution**

```python
execution = await executions.prepare(
    session,
    input={"sourceExecutionId": source_execution_id},
    project_input_message=False,
    execution_id=evaluation_run_id,
)
executions.run_background(execution, handler)
```

- [x] **Step 4: Reuse the Execution ID as evaluation run and Trace run ID, and translate failed evaluation status into failed Execution status**

- [x] **Step 5: Change the route to HTTP 202 and return the Judge Execution ID**

- [x] **Step 6: Add failing frontend test for the three real stages and “在运行中心查看” link**

- [x] **Step 7: Poll the Judge Execution and model Operations until terminal state**

```ts
const stage = execution.status === "completed"
  ? "completed"
  : modelOperation?.status === "running"
    ? "judging"
    : modelOperation?.status === "completed"
      ? "saving"
      : "preparing";
```

- [x] **Step 8: Refresh the evaluation report only after the Judge Execution completes**

- [x] **Step 9: Run backend and frontend targeted tests**

### Task 3: Global active-Agent navigation badge

**Files:**
- Create: `frontend/src/features/observability/useActiveAgentCount.ts`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Modify: `frontend/src/app/navigation/PrimaryNavigation.tsx`
- Modify: `frontend/src/app/navigation/MobileNavigation.tsx`
- Modify: `frontend/src/app/global.css`
- Test: `frontend/src/app/navigation/PrimaryNavigation.test.tsx`

**Interfaces:**
- Produces: `useActiveAgentCount(workspaceId): number`
- Consumes: execution snapshot API and `execution.summary.changed` SSE.

- [x] **Step 1: Add failing tests for hidden zero badge and live non-zero badge**

```tsx
expect(screen.getByRole("link", { name: "Agent 运行中心，2 个任务正在运行" }))
  .toHaveAttribute("href", "/agents?status=running");
```

- [x] **Step 2: Implement one AppShell-owned snapshot/SSE hook so desktop and mobile share the same count**

- [x] **Step 3: Render a `99+`-capped badge and hide it at zero**

- [x] **Step 4: Run navigation and AppShell regression tests**

### Task 4: One-click model binding for all task roles

**Files:**
- Modify: `frontend/src/features/settings/ModelBindings.tsx`
- Modify: `frontend/src/app/global.css`
- Modify: `frontend/src/features/settings/ModelBindings.test.tsx`

**Interfaces:**
- Consumes: existing `replaceWorkspaceModelBindings(workspaceId, bindings)`.
- Produces: a bulk model selector and `全部使用并保存` action.

- [x] **Step 1: Add failing test that selects one model and sends all roles in one PUT**

```ts
expect(Object.values(request.bindings)).toEqual(
  Array(MODEL_ROLE_COUNT).fill("model-1"),
);
```

- [x] **Step 2: Add the bulk selector and a single atomic save action**

- [x] **Step 3: Preserve per-role overrides and existing dirty-navigation protection**

- [x] **Step 4: Run ModelBindings tests**

### Task 5: Integrated verification and documentation

**Files:**
- Modify: `docs/verification/interview-retrospective-agent.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: all four completed tasks.
- Produces: reproducible targeted verification evidence and manual acceptance checklist.

- [x] **Step 1: Run the combined backend targeted suite**

- [x] **Step 2: Run the combined frontend targeted suite and typecheck/build**

- [ ] **Step 3: Perform one browser happy path for quality progress, profile visibility, badge, and bulk model save**

Blocked on 2026-08-05 because the 5175 frontend was reachable but its backend was not running. The browser correctly showed “正在检查后端连接 / 尚未创建工作区”; no Provider call or model-binding write was fabricated.

- [x] **Step 4: Record evidence and remaining product boundary**
