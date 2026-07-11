# R1.4 持久化 HITL 实施计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 持久化人工确认请求、暂停 LangGraph run，使用乐观并发和幂等支持接受/编辑/拒绝，并在重启后恢复同一个 run。

**架构：** pending action 和 resolution receipt 保存在 Runtime SQLite。Graph 节点调用 LangGraph interrupt 前先创建确定性 action；HitlService 校验版本和幂等键，再通过 AgentRuntime 使用 typed decision payload 恢复精确 run。

**技术栈：** FastAPI、Pydantic 2、SQLite、LangGraph interrupt/Command、React、TypeScript、Vitest、pytest-asyncio。

**设计复核：** 执行前先遵循 `docs/superpowers/specs/2026-07-11-r1-4-persistent-hitl-design-review.md`。该文档补充 R1.3 后的 Workspace Runtime 依赖方向、interrupt 返回语义和设置页真实诊断闭环。

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
- `backend/app/hitl/repository.py` — 基于独立 aiosqlite 连接的事务持久化、乐观状态转换和投递状态。
- `backend/app/hitl/handlers.py` — action handler Registry。
- `backend/app/hitl/service.py` — 创建、接受/编辑/拒绝和 Runtime 恢复。
- `backend/app/runtime/approval_diagnostic_graph.py` — 确定性 HITL 人工验证 Graph。
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
- `backend/app/runtime/graph_build_context.py` — 注入窄化的 action 创建接口。
- `backend/app/runtime/default_graphs.py` — 注册 `test.approval`。
- `backend/app/runtime/service.py` — `resume_run` with typed resume value.
- `backend/app/runtime/event_stream.py` — `hitl.required/resolved` events.
- `backend/app/schemas/agent.py` — session detail pending action 摘要。
- `backend/app/main.py` — HITL router.
- `frontend/src/features/agent/agentTypes.ts` — HITL event payloads.
- `frontend/src/features/agent/useAgentEvents.ts` — 暴露 pending action ID。
- `frontend/src/features/settings/SettingsPage.tsx` — 挂载 ActionCenter。
- `backend/tests/test_tool_audit.py` — migration 版本断言更新。

### 任务 1：HITL 迁移与 Repository

**接口：**
- 产出异步 `PendingActionRepository.create/get/list_pending/resolve`，每次操作使用独立 aiosqlite 连接。
- 使用 action `version` 和确定性创建 `idempotency_key`。
- resolution receipt 保存 `delivery_status`、attempt count 和可重试 decision payload。

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_hitl_repository.py`：

```python
async def test_create_is_idempotent(repository, action_request):
    first = await repository.create(action_request)
    second = await repository.create(action_request)
    assert second.id == first.id


async def test_resolution_requires_current_version(repository, action_request):
    action = await repository.create(action_request)
    with pytest.raises(ActionVersionConflictError):
        await repository.resolve(action.id, expected_version=action.version + 1, status="approved", resolution_key="resolve-1", payload={})


async def test_duplicate_resolution_returns_receipt(repository, action_request):
    action = await repository.create(action_request)
    first = await repository.resolve(action.id, expected_version=action.version, status="approved", resolution_key="resolve-1", payload={"decision": "approved"})
    second = await repository.resolve(action.id, expected_version=action.version, status="approved", resolution_key="resolve-1", payload={"decision": "approved"})
    assert second == first
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_repository.py -v`

预期：失败，因为 HITL 模块和迁移尚不存在。

- [x] **步骤 3：实现最小功能**

迁移创建 `pending_actions` 和 `pending_action_resolutions`。强制唯一创建幂等键、唯一 `(action_id, resolution_key)`、session/run 外键和不可变终态。receipt 保存 decision JSON、delivery status/attempt/delivered time/稳定错误码。payload/preview/editable fields 保存为标准 JSON，对外暴露不可变 record。更新 migration 版本回归。Repository 不复用 Runtime 同步 connection。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_repository.py -v`

```bash
git add backend/app/db/migrations/runtime/003_hitl.sql backend/app/hitl/models.py backend/app/hitl/repository.py backend/tests/test_hitl_repository.py backend/tests/test_tool_audit.py
git commit -m "feat(hitl): persist approval actions"
```

### 任务 2：HitlService 与 Handler Registry

**接口：**
- 产出 `ActionHandlerRegistry.register(action_type, handler)`.
- 产出 `HitlService.create_action/approve/reject`.
- Handler 在 Repository 状态转换后接收 resolved action，且必须幂等。

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_hitl_service.py`：

```python
@pytest.mark.asyncio
async def test_edited_approval_saves_payload_and_resumes(service, runtime, request):
    action = await service.create_action(request)
    resolved = await service.approve(action.id, ResolveActionCommand(version=action.version, idempotency_key="approve-1", edited_payload={"content": "edited"}))
    assert resolved.status == "edited_and_approved"
    runtime.resume_run.assert_awaited_once_with(action.run_id, {"actionId": action.id, "decision": "approved", "payload": {"content": "edited"}})


@pytest.mark.asyncio
async def test_reject_resumes_with_reason(service, runtime, request):
    action = await service.create_action(request)
    await service.reject(action.id, ResolveActionCommand(version=action.version, idempotency_key="reject-1", reason="不发布"))
    runtime.resume_run.assert_awaited_once_with(action.run_id, {"actionId": action.id, "decision": "rejected", "reason": "不发布"})
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_service.py -v`

预期：失败，因为 service/handler Registry 尚不存在。

- [x] **步骤 3：实现最小功能**

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

每个 Workspace Runtime 创建自己的 Repository 与 Service，Action API 通过 `AgentRuntime` 定位，不创建悬空的应用级全局 service。action 创建先持久化；`RunManager` 是 `hitl.required` 的唯一发布者，识别 interrupt 并进入 waiting 后才发送事件。终态转换后发送 `hitl.resolved`，resolution receipt 提交后才能恢复 run。相同幂等键在“已提交但尚未成功启动恢复”的情况下必须安全重试恢复；启动时 reconciliation 处理未 delivered receipt。

- [x] **步骤 4：运行测试确认通过并提交**

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

创建包含以下 StateGraph 节点的 `backend/tests/test_hitl_restart.py`，并新增生产确定性 `test.approval` Graph：

```python
async def approval_node(state):
    action = await context.request_action(
        action_type="test.approval",
        payload={"value": state["value"]},
        preview={"summary": state["value"]},
        idempotency_key="test.approval",
        editable_fields=("value",),
    )
    decision = interrupt({"actionId": action.id})
    return {"decision": decision}
```

断言 run 进入 waiting，重启后 action/checkpoint 保留，批准恢复同一个 run，重放不会创建第二个 action。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_restart.py -v`

预期：失败，因为 RunManager 尚未映射 interrupt。

- [ ] **步骤 3：实现最小功能**

识别 `ainvoke()` 结果中的 `__interrupt__`，把 run/session 转换为 waiting-for-approval，并持久化 `hitl.required`。使用原 thread/session、原 `run_id` 和原 checkpoint，通过 `Command(resume=decision_payload)` 恢复；增加该 run 的 resume attempt 计数，不创建第二个 run。取消 waiting run 时同时取消 pending action。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_restart.py -v`

```bash
git add backend/app/runtime/run_manager.py backend/app/runtime/service.py backend/app/runtime/graph_build_context.py backend/app/runtime/approval_diagnostic_graph.py backend/app/runtime/default_graphs.py backend/tests/test_hitl_restart.py
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

返回 camelCase 资源。列表支持 Workspace、status 和可选 session 过滤；session detail 返回 pending action 摘要。不能返回 checkpoint 数据、secret payload 字段或内部 handler 异常。在 `main.py` 注册 router，并补齐 typed 409 exception handlers。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_hitl_routes.py -v`

```bash
git add backend/app/schemas/hitl.py backend/app/schemas/agent.py backend/app/api/routes_hitl.py backend/app/main.py backend/tests/test_hitl_routes.py
git commit -m "feat(hitl): expose persistent action decisions"
```

### 任务 5：前端 ActionCenter

**接口：**
- 产出 typed HITL API and ActionCenter list/detail/resolve UI.
- ActionCenter 接受 Workspace ID 和可选 session ID 过滤。
- 设置页必须能启动一次真实 `test.approval` run，不能只展示静态 action 列表。

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

优先渲染结构化预览；只有 action schema 标记字段可编辑时才显示编辑控件。每次按钮动作只生成一次幂等键，重试时不能重新生成。把 ActionCenter 接入设置页，提供“运行确认测试”入口并支持刷新恢复 pending action。

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
git add frontend/src/features/agent/hitlTypes.ts frontend/src/features/agent/hitlApi.ts frontend/src/features/agent/ActionCenter.tsx frontend/src/features/agent/ActionCenter.test.tsx frontend/src/features/agent/agentTypes.ts frontend/src/features/agent/useAgentEvents.ts frontend/src/features/settings/SettingsPage.tsx frontend/src/features/settings/SettingsPage.test.tsx
git commit -m "feat(hitl): review and resolve pending actions"
```

- [ ] **步骤 5：整理阶段文档并运行质量门禁**

按照正式模板把增量 verification 整理为最终用户验证指南，并生成 `docs/learning/r1-4-hitl/` 七件套。对照 R1.3 同类型文档检查内容深度，然后运行：

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r1_4_persistent_hitl.md \
  --learning docs/learning/r1-4-hitl/
```

将门禁结果写入 `progress.md` 和最终交付汇报。门禁失败时不得把 R1.4 标记为“可人工验证”；用户尚未完成 learning 练习不阻塞阶段关闭或后续产品开发。

R1.4 验收：Graph 停在一个持久化 action；重启后仍存在；支持编辑后批准或拒绝；只恢复一次；重复或浏览器并发决定不会执行两次。
