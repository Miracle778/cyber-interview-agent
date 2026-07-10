# R1.4 持久化 HITL 实施计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 持久化人工确认请求、暂停 LangGraph run，使用乐观并发和幂等支持接受/编辑/拒绝，并在重启后恢复同一个 run。

**架构：** pending action 和 resolution receipt 保存在 Runtime SQLite。Graph 节点调用 LangGraph interrupt 前先创建确定性 action；HitlService 校验版本和幂等键，再通过 AgentRuntime 使用 typed decision payload 恢复精确 run。

**技术栈：** FastAPI、Pydantic 2、SQLite、LangGraph interrupt/Command、React、TypeScript、Vitest、pytest-asyncio。

## 全局约束

- Graph 节点重放时，action 创建保持幂等。
- Action 在后端重启后仍存在，并持续关联 session/run/checkpoint。
- 接受、编辑后接受、拒绝和取消都是明确终态。
- 处理 action 必须提供 action version 和 idempotency key。
- 重复处理返回原结果；冲突处理返回 409。
- Action payload、事件和审计数据必须脱敏。
- 知识发布到 R1.5 才实现；本切片使用确定性确认测试 Graph。

---

## 文件结构

新建：

- `backend/app/db/migrations/runtime/003_hitl.sql` — pending action 和 resolution receipt。
- `backend/app/hitl/models.py` — action/decision record 和状态。
- `backend/app/hitl/repository.py` — 事务持久化和乐观状态转换。
- `backend/app/hitl/handlers.py` — action handler Registry。
- `backend/app/hitl/service.py` — 创建、接受/编辑/拒绝和 Runtime 恢复。
- `backend/app/schemas/hitl.py` — API schemas.
- `backend/app/api/routes_hitl.py` — action 列表/详情/接受/拒绝。
- `backend/tests/test_hitl_repository.py`
- `backend/tests/test_hitl_service.py`
- `backend/tests/test_hitl_routes.py`
- `backend/tests/test_hitl_restart.py`
- `frontend/src/features/agent/hitlTypes.ts`
- `frontend/src/features/agent/hitlApi.ts`
- `frontend/src/features/agent/ActionCenter.tsx`
- `frontend/src/features/agent/ActionCenter.test.tsx`

修改：

- `backend/app/runtime/run_manager.py` — waiting/resume 支持。
- `backend/app/runtime/service.py` — `resume_run` with typed resume value.
- `backend/app/runtime/event_stream.py` — `hitl.required/resolved` events.
- `backend/app/api/dependencies.py` — `get_hitl_service`.
- `backend/app/main.py` — HITL router.
- `frontend/src/features/agent/agentTypes.ts` — HITL event payloads.
- `frontend/src/features/agent/useAgentEvents.ts` — 暴露 pending action ID。

### 任务 1：HITL 迁移与 Repository

**接口：**
- 产出 `PendingActionRepository.create/get/list_pending/resolve`.
- 使用 action `version` 和确定性创建 `idempotency_key`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_hitl_repository.py`：

```python
def test_create_is_idempotent(repository, action_request):
    first = repository.create(action_request)
    second = repository.create(action_request)
    assert second.id == first.id


def test_resolution_requires_current_version(repository, action_request):
    action = repository.create(action_request)
    with pytest.raises(ActionVersionConflictError):
        repository.resolve(action.id, expected_version=action.version + 1, status="approved", resolution_key="resolve-1", payload={})


def test_duplicate_resolution_returns_receipt(repository, action_request):
    action = repository.create(action_request)
    first = repository.resolve(action.id, expected_version=action.version, status="approved", resolution_key="resolve-1", payload={"decision": "approved"})
    second = repository.resolve(action.id, expected_version=action.version, status="approved", resolution_key="resolve-1", payload={"decision": "approved"})
    assert second == first
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_repository.py -v`

预期：失败，因为 HITL 模块和迁移尚不存在。

- [ ] **步骤 3：实现最小功能**

迁移创建 `pending_actions` 和 `pending_action_resolutions`。强制唯一创建幂等键、唯一 `(action_id, resolution_key)`、session/run 外键和不可变终态。payload/preview 保存为标准 JSON，对外暴露不可变 record。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_repository.py -v`

```bash
git add backend/app/db/migrations/runtime/003_hitl.sql backend/app/hitl/models.py backend/app/hitl/repository.py backend/tests/test_hitl_repository.py
git commit -m "feat(hitl): persist approval actions"
```

### 任务 2：HitlService 与 Handler Registry

**接口：**
- 产出 `ActionHandlerRegistry.register(action_type, handler)`.
- 产出 `HitlService.create_action/approve/reject`.
- Handler 在 Repository 状态转换后接收 resolved action，且必须幂等。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_hitl_service.py`：

```python
@pytest.mark.asyncio
async def test_edited_approval_saves_payload_and_resumes(service, runtime, request):
    action = service.create_action(request)
    resolved = await service.approve(action.id, ResolveActionCommand(version=action.version, idempotency_key="approve-1", edited_payload={"content": "edited"}))
    assert resolved.status == "edited_and_approved"
    runtime.resume_run.assert_awaited_once_with(action.run_id, {"actionId": action.id, "decision": "approved", "payload": {"content": "edited"}})


@pytest.mark.asyncio
async def test_reject_resumes_with_reason(service, runtime, request):
    action = service.create_action(request)
    await service.reject(action.id, ResolveActionCommand(version=action.version, idempotency_key="reject-1", reason="不发布"))
    runtime.resume_run.assert_awaited_once_with(action.run_id, {"actionId": action.id, "decision": "rejected", "reason": "不发布"})
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_service.py -v`

预期：失败，因为 service/handler Registry 尚不存在。

- [ ] **步骤 3：实现最小功能**

使用以下命令模型：

```python
class CreatePendingAction(BaseModel):
    workspace_id: str
    session_id: str
    run_id: str
    action_type: str
    payload: dict[str, object]
    preview: dict[str, object]
    idempotency_key: str


class ResolveActionCommand(BaseModel):
    version: int
    idempotency_key: str
    edited_payload: dict[str, object] | None = None
    reason: str | None = None
```

创建后发送已持久化的 `hitl.required`，终态转换后发送 `hitl.resolved`。resolution receipt 提交后才能恢复 run。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_service.py -v`

```bash
git add backend/app/hitl/handlers.py backend/app/hitl/service.py backend/app/runtime/service.py backend/app/runtime/event_stream.py backend/tests/test_hitl_service.py
git commit -m "feat(hitl): resolve and resume approval actions"
```

### 任务 3：LangGraph Interrupt 集成

**接口：**
- 产出一个先创建确定性 action、再调用 `interrupt` 的测试 Graph。
- RunManager 把 Graph interrupt 状态映射为 waiting-for-approval。

- [ ] **步骤 1：编写失败测试**

创建包含以下 StateGraph 节点的 `backend/tests/test_hitl_restart.py`：

```python
def approval_node(state, *, hitl_service):
    action = hitl_service.create_action(CreatePendingAction(
        workspace_id=state["workspace_id"],
        session_id=state["session_id"],
        run_id=state["run_id"],
        action_type="test.approval",
        payload={"value": state["value"]},
        preview={"summary": state["value"]},
        idempotency_key=f'{state["run_id"]}:test.approval',
    ))
    decision = interrupt({"actionId": action.id})
    return {"decision": decision}
```

断言 run 进入 waiting，重启后 action/checkpoint 保留，批准恢复同一个 run，重放不会创建第二个 action。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_restart.py -v`

预期：失败，因为 RunManager 尚未映射 interrupt。

- [ ] **步骤 3：实现最小功能**

捕获 LangGraph interrupt 输出，把 run/session 转换为 waiting-for-approval，并持久化 `hitl.required`。使用原 thread/session、原 `run_id` 和原 checkpoint，通过 `Command(resume=decision_payload)` 恢复；增加该 run 的 resume attempt 计数，不创建第二个 run。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_restart.py -v`

```bash
git add backend/app/runtime/run_manager.py backend/app/runtime/service.py backend/tests/test_hitl_restart.py
git commit -m "feat(hitl): pause and resume langgraph runs"
```

### 任务 4：HITL REST API

**接口：**
- 产出 list/detail/approve/reject endpoints exactly from the spec.
- 使用 typed 409 code：`action_version_conflict` 和 `action_already_resolved`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_hitl_routes.py`，验证 Workspace/status 过滤、脱敏详情、编辑后批准、带原因拒绝、重复幂等批准和冲突的第二次决定。

```python
response = client.post(f"/api/agent/actions/{action_id}/approve", json={"version": 1, "idempotencyKey": "approve-1", "editedPayload": {"content": "edited"}})
assert response.status_code == 200
assert response.json()["status"] == "edited_and_approved"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_routes.py -v`

预期：失败，因为 schema/route 尚不存在。

- [ ] **步骤 3：实现最小功能**

返回 camelCase 资源。不能返回 checkpoint 数据、secret payload 字段或内部 handler 异常。在 `main.py` 注册 router。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_routes.py -v`

```bash
git add backend/app/schemas/hitl.py backend/app/api/routes_hitl.py backend/app/api/dependencies.py backend/app/main.py backend/tests/test_hitl_routes.py
git commit -m "feat(hitl): expose persistent action decisions"
```

### 任务 5：前端 ActionCenter

**接口：**
- 产出 typed HITL API and ActionCenter list/detail/resolve UI.
- ActionCenter 接受 Workspace ID 和可选 session ID 过滤。

- [ ] **步骤 1：编写失败测试**

Create `ActionCenter.test.tsx` covering list, preview, edited approval, reject reason, stale version 409, duplicate resolve result, and restoration after rerender. Assert buttons disable during a resolution request.

- [ ] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- ActionCenter.test.tsx`

预期：失败，因为 HITL 前端文件尚不存在。

- [ ] **步骤 3：实现最小功能**

使用精确 status union 和请求类型：

```ts
export type PendingActionStatus = "pending" | "approved" | "edited_and_approved" | "rejected" | "cancelled";

export interface ResolveActionRequest {
  version: number;
  idempotencyKey: string;
  editedPayload?: Record<string, unknown>;
  reason?: string;
}
```

优先渲染结构化预览；只有 action schema 标记字段可编辑时才显示编辑控件。每次按钮动作只生成一次幂等键，重试时不能重新生成。

- [ ] **步骤 4：验证完整切片并提交**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

Create ignored `docs/verification/r1_4_persistent_hitl.md`, then:

```bash
git add frontend/src/features/agent/hitlTypes.ts frontend/src/features/agent/hitlApi.ts frontend/src/features/agent/ActionCenter.tsx frontend/src/features/agent/ActionCenter.test.tsx frontend/src/features/agent/agentTypes.ts frontend/src/features/agent/useAgentEvents.ts
git commit -m "feat(hitl): review and resolve pending actions"
```

R1.4 验收：Graph 停在一个持久化 action；重启后仍存在；支持编辑后批准或拒绝；只恢复一次；重复或浏览器并发决定不会执行两次。
