# R1.2 Agent Runtime 与 SSE 实施计划

> **历史实现记录，禁止作为后续模板：** 本文保留 R1/Pre-R2 当时的设计、实施和验收事实。
> 其中涉及的自研 `AgentRuntime`、`RunManager`、Gateway、Registry/Executor、middleware
> pipeline 或旧 session/run API 已由
> `docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md` 取代。
> R2-R8 必须以产品总路线、框架收敛设计和各阶段新 spec 为准；本文中的领域安全、
> HITL、发布和恢复不变量仍可作为历史证据，但代码路径和协议名称可能已不存在。


**目标：** 持久化 Agent session、run、message、checkpoint 和可重放事件，通过 REST 暴露异步命令，通过 SSE 暴露运行进度。

**架构：** 产品记录和 LangGraph checkpoint 保存在 Workspace 内部 Runtime 数据库，但两者 API 分离。Graph Registry 创建固定版本的编译 Graph；进程内异步 RunManager 按 session 串行执行 run，并在发布事件前先持久化。

**技术栈：** FastAPI、Pydantic 2、SQLite WAL、aiosqlite、LangGraph SQLite checkpointer、asyncio、React/TypeScript EventSource、pytest-asyncio、Vitest。

## 全局约束

- `session_id` 同时作为 LangGraph `thread_id`，每次调用使用独立 `run_id`。
- 产品消息和 run 状态不从 checkpoint 内部读取。
- 每个 session 只允许一个 active run；并发启动返回 `409 session_busy`。
- 每个 SSE 事件发送前先持久化，并支持按 event ID 重放。
- R1 使用进程内异步 runner，不引入 Celery/Redis。
- 重启后 running run 变为 interrupted，waiting-for-approval 保持不变。
- session 固定 graph ID/version，不能静默用其他版本恢复。
- 本切片使用确定性 Fake Graph；真实复习/Provider 集成在 R1.6 完成。

---

## 文件结构

新建：

- `backend/app/db/runtime_database.py` — Workspace runtime connection/migrations.
- `backend/app/db/migrations/runtime/001_runtime.sql` — session、message、run 和 event 表。
- `backend/app/runtime/models.py` — 不可变 record 和状态 literal。
- `backend/app/runtime/repository.py` — session/run/message/event 持久化。
- `backend/app/runtime/graph_registry.py` — 带版本 Graph 注册。
- `backend/app/runtime/checkpoints.py` — LangGraph SQLite saver lifecycle.
- `backend/app/runtime/event_stream.py` — 先持久化后发送的事件 broker。
- `backend/app/runtime/run_manager.py` — session 锁、task 生命周期和重启恢复。
- `backend/app/runtime/service.py` — AgentRuntime application service.
- `backend/app/schemas/agent.py` — REST/SSE resource schemas.
- `backend/app/api/routes_agent.py` — session/run/event endpoint。
- `backend/tests/test_runtime_database.py`
- `backend/tests/test_graph_registry.py`
- `backend/tests/test_runtime_repository.py`
- `backend/tests/test_event_stream.py`
- `backend/tests/test_run_manager.py`
- `backend/tests/test_agent_routes.py`
- `frontend/src/features/agent/agentTypes.ts`
- `frontend/src/features/agent/agentApi.ts`
- `frontend/src/features/agent/agentApi.test.ts`
- `frontend/src/features/agent/useAgentEvents.ts`
- `frontend/src/features/agent/useAgentEvents.test.tsx`
- `frontend/src/features/settings/RuntimeDiagnostics.tsx`
- `frontend/src/features/settings/RuntimeDiagnostics.test.tsx`

修改：

- `backend/pyproject.toml` — 添加 `aiosqlite` 和 `langgraph-checkpoint-sqlite`。
- `backend/uv.lock` — 更新依赖锁。
- `backend/app/api/dependencies.py` — `get_agent_runtime`.
- `backend/app/main.py` — 注册 Agent router 和启动恢复。
- `frontend/src/shared/api/client.ts` — 在不改变错误语义的前提下支持 `202 Accepted` 资源。
- `frontend/src/features/settings/SettingsPage.tsx` — Workspace 就绪后组合 Runtime 自检面板。
- `frontend/src/app/global.css` — Runtime 状态和事件时间线响应式样式。

### 任务 1：Runtime 数据库与记录模型

**接口：**
- 产出 `connect_runtime_database(workspace_root: Path) -> sqlite3.Connection`.
- 产出 `SessionRecord`, `RunRecord`, `MessageRecord`, and `EventRecord`.

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_runtime_database.py`：

```python
from app.db.runtime_database import connect_runtime_database


def test_runtime_database_lives_outside_vault(tmp_path):
    connection = connect_runtime_database(tmp_path)
    assert (tmp_path / ".cyber-interview-agent" / "runtime.sqlite").exists()
    assert not (tmp_path / "knowledge-vault" / ".cyber-interview-agent" / "runtime.sqlite").exists()
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_runtime_schema_contains_product_tables(tmp_path):
    connection = connect_runtime_database(tmp_path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agent_sessions", "agent_messages", "agent_runs", "agent_events"} <= tables
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_runtime_database.py -v`

预期：失败，因为模块尚不存在。

- [x] **步骤 3：实现最小功能**

Schema 必须强制 session/run 外键、每个 session 唯一事件序列和状态 CHECK 约束。Run 表包含 `resume_count` 和 `last_resumed_at`；恢复动作沿用原 run ID。`connect_runtime_database` 创建 `.cyber-interview-agent`，启用外键、WAL 和 busy timeout，再按顺序应用 Runtime 迁移。

严格使用 spec 中的状态。Session 状态不包含 `failed`；某次 run 失败后 session 回到 active。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_runtime_database.py -v`

```bash
git add backend/app/db/runtime_database.py backend/app/db/migrations/runtime/001_runtime.sql backend/app/runtime/models.py backend/tests/test_runtime_database.py
git commit -m "feat(runtime): add workspace runtime database"
```

### 任务 2：Graph Registry

**接口：**
- 产出 `GraphDefinition` and `GraphRegistry.register/get`.
- definition 包含 `graph_id`、`graph_version`、factory、模型用途、工具和 scope。

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_graph_registry.py`：

```python
def test_registry_resolves_exact_graph_version():
    registry = GraphRegistry()
    definition = GraphDefinition(graph_id="test.echo", graph_version=1, factory=lambda checkpointer: object(), required_model_roles=frozenset(), allowed_tools=frozenset(), allowed_scopes=frozenset())
    registry.register(definition)
    assert registry.get("test.echo", 1) is definition


def test_registry_does_not_fall_forward_to_new_version():
    registry = GraphRegistry()
    registry.register(GraphDefinition(graph_id="test.echo", graph_version=2, factory=lambda checkpointer: object(), required_model_roles=frozenset(), allowed_tools=frozenset(), allowed_scopes=frozenset()))
    with pytest.raises(GraphVersionNotFoundError):
        registry.get("test.echo", 1)
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_graph_registry.py -v`

预期：失败，因为 GraphRegistry 尚不存在。

- [x] **步骤 3：实现最小功能**

使用以 `(graph_id, graph_version)` 为 key 的字典。重复注册抛出 `DuplicateGraphDefinitionError`。Factory 接收 checkpointer 并返回已编译 Graph；Registry 不访问 Workspace 或 Provider service。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_graph_registry.py -v`

```bash
git add backend/app/runtime/graph_registry.py backend/tests/test_graph_registry.py
git commit -m "feat(runtime): register versioned agent graphs"
```

### 任务 3：Session 与 Run Repository

**接口：**
- 产出 CRUD/state-transition methods used by AgentRuntime.
- Repository methods use explicit expected states for transitions.

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_runtime_repository.py`，测试：

```python
session = repository.create_session(workspace_id="w1", graph_id="test.echo", graph_version=1, title="Echo")
run = repository.create_run(session.id, model_bindings={})
repository.transition_run(run.id, expected="queued", target="running")
repository.transition_run(run.id, expected="running", target="failed", error_code="boom")
assert repository.get_session(session.id).status == "active"
```

同时断言同一 session 的第二个 queued/running run 抛出 `SessionBusyError`，消息保持顺序，event ID 单调递增。

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_runtime_repository.py -v`

预期：失败，因为 RuntimeRepository 尚不存在。

- [x] **步骤 3：实现最小功能**

Use `BEGIN IMMEDIATE` for run creation/transition. Store model binding snapshots as canonical JSON. Reject stale transitions with `InvalidRunTransitionError`; never overwrite a state without an expected source status.

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_runtime_repository.py -v`

```bash
git add backend/app/runtime/repository.py backend/tests/test_runtime_repository.py
git commit -m "feat(runtime): persist sessions runs and events"
```

### 任务 4：先持久化后发送的事件流

**接口：**
- 产出 `EventStream.publish(session_id, run_id, type, payload)` and `subscribe(session_id, after_id)`.
- Event payloads pass through a type registry and secret scrubber.

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_event_stream.py`：

```python
@pytest.mark.asyncio
async def test_publish_persists_before_subscriber_receives(runtime_repository):
    stream = EventStream(runtime_repository)
    subscription = stream.subscribe("s1", after_id=None)
    published = await stream.publish("s1", "r1", "run.started", {"apiKey": "sk-secret"})
    received = await anext(subscription)
    assert received.id == published.id
    assert runtime_repository.get_event(published.id) is not None
    assert "sk-secret" not in received.payload_json


@pytest.mark.asyncio
async def test_subscribe_replays_after_event_id(runtime_repository):
    first = runtime_repository.append_event("s1", "r1", "message.delta", {"text": "a"})
    second = runtime_repository.append_event("s1", "r1", "message.delta", {"text": "b"})
    received = await anext(EventStream(runtime_repository).subscribe("s1", after_id=first.id))
    assert received.id == second.id
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_event_stream.py -v`

预期：失败，因为 EventStream 尚不存在。

- [x] **步骤 3：实现最小功能**

先持久化并提交事件，再通知内存 subscriber。订阅时先重放数据库事件，再流式发送新事件。SSE 编码如下：

```text
id: <event-id>
event: <event-type>
data: <camelCase JSON envelope>

```

持久化前递归移除 key 为 `api_key`、`apiKey`、`authorization`、`secret`、`access_token`、`accessToken`、`refresh_token`、`refreshToken` 的字段。保留 `tokenUsage`、`inputTokens`、`outputTokens` 等非 secret 指标。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_event_stream.py -v`

```bash
git add backend/app/runtime/event_stream.py backend/tests/test_event_stream.py
git commit -m "feat(runtime): persist and replay agent events"
```

### 任务 5：Checkpointer 与 RunManager

**接口：**
- 产出 `RuntimeCheckpointer.open(workspace_root)`.
- 产出 `RunManager.start`, `resume`, `cancel`, and `recover_interrupted_runs`.

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_run_manager.py`：一个确定性 StateGraph 写入消息，另一个 Graph 通过注入测试节点暂停。验证完成 run 持久化 checkpoint，重启恢复把 running 标记为 interrupted，waiting-for-approval 保持不变，恢复使用 config `{"configurable": {"thread_id": session_id}}`，并沿用原 run ID。

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_run_manager.py -v`

预期：失败，因为 checkpointer 和 RunManager 尚不存在。

- [x] **步骤 3：实现最小功能**

先在 `backend/pyproject.toml` 添加 `aiosqlite` 和 `langgraph-checkpoint-sqlite`。用 `RuntimeCheckpointer` 封装 `AsyncSqliteSaver`，配置 WAL 并使用 Workspace Runtime 数据库路径。RunManager 为每个 session 持有 `asyncio.Lock`，并按 run 维护进程内 task map。它发送 start/completion/failure/interrupted 事件，并把最终 Agent 消息与 checkpoint 分开保存。

进程启动时调用 `recover_interrupted_runs()`，只把 `running` 转换为 `interrupted`，不能自动恢复外部模型调用。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv lock && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_run_manager.py -v`

```bash
git add backend/app/runtime/checkpoints.py backend/app/runtime/run_manager.py backend/tests/test_run_manager.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(runtime): checkpoint and recover agent runs"
```

### 任务 6：AgentRuntime 与 REST/SSE 路由

**接口：**
- 产出 API resources from the R1 spec.
- Start/resume endpoints return `202` with a Run resource.

- [x] **步骤 1：编写失败测试**

创建 `backend/tests/test_agent_routes.py` 并覆盖 `get_agent_runtime`。断言 session 创建/列表/详情、启动返回 202、并发 run 返回 `409 session_busy`、取消幂等，以及 SSE 遵循 `Last-Event-ID`。

使用以下响应断言：

```python
response = client.post("/api/agent/sessions", json={"workspaceId": "w1", "graphId": "test.echo", "graphVersion": 1, "title": "Echo"})
assert response.status_code == 201
session_id = response.json()["id"]
run = client.post(f"/api/agent/sessions/{session_id}/runs", json={"input": {"text": "hello"}})
assert run.status_code == 202
```

- [x] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_agent_routes.py -v`

预期：失败，因为 schema/route 尚不存在。

- [x] **步骤 3：实现最小功能**

AgentRuntime 通过 WorkspaceService 解析 Workspace，打开 Runtime Repository，校验精确 Graph 版本，保存模型绑定快照，再委派 RunManager。Session detail 返回消息、最近 run 和 pending action 摘要，但不返回 checkpoint blob。

在 `main.py` 注册 `routes_agent` 和启动恢复逻辑。

- [x] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_agent_routes.py tests/test_run_manager.py -v`

```bash
git add backend/app/runtime/service.py backend/app/schemas/agent.py backend/app/api/routes_agent.py backend/app/api/dependencies.py backend/app/main.py backend/tests/test_agent_routes.py
git commit -m "feat(runtime): expose persistent agent sessions and SSE"
```

### 任务 7：前端 Agent Client 与切片验证

**接口：**
- 产出 typed session/run methods and `useAgentEvents(sessionId)`.
- 不迁移复习业务 Graph；为设置页 Runtime 自检提供 typed client。

- [x] **步骤 1：编写失败测试**

Create API tests for create/list/detail/start/resume/cancel. Create hook tests with a fake EventSource asserting reconnect uses the last event ID through the URL `?after=<id>`, duplicate event IDs are ignored, and `run.failed` updates connection state without losing prior messages.

- [x] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- agentApi.test.ts useAgentEvents.test.tsx`

预期：失败，因为 Agent 前端模块尚不存在。

- [x] **步骤 3：实现最小功能**

使用可辨识联合类型：

```ts
export type AgentEvent =
  | { id: number; type: "message.delta"; sessionId: string; runId: string; payload: { text: string } }
  | { id: number; type: "message.completed"; sessionId: string; runId: string; payload: { messageId: string; content: string } }
  | { id: number; type: "run.failed"; sessionId: string; runId: string; payload: { code: string; message: string } }
  | { id: number; type: string; sessionId: string; runId: string; payload: Record<string, unknown> };
```

The hook owns connection/reconnect state only; final product messages come from session detail after reconnect.

- [x] **步骤 4：验证完整切片并提交**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

Create ignored `docs/verification/r1_2_agent_runtime_sse.md`, then:

```bash
git add frontend/src/features/agent frontend/src/shared/api/client.ts
git commit -m "feat(runtime): add browser agent session client"
```

### 任务 8：设置页 Runtime 自检闭环

**接口：**
- 产出 `RuntimeDiagnostics({ workspaceId })`。
- 使用固定 `test.echo` version 1 创建/恢复“Agent Runtime 自检”session。
- 展示最近 run、SSE 连接状态和经过整理的事件时间线。

- [x] **步骤 1：编写失败测试**

创建 `RuntimeDiagnostics.test.tsx`，覆盖：首次加载恢复最近自检 session；没有 session 时显示可运行状态；点击“运行自检”后创建 session、启动 run；收到 `run.started`、`message.completed`、`run.completed` 后更新状态；`run.failed` 显示恢复建议；重复事件不重复渲染。

更新 `SettingsPage.test.tsx`，断言 Workspace 注册恢复后组合 RuntimeDiagnostics；无 Workspace 时不渲染自检按钮。

- [x] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- RuntimeDiagnostics.test.tsx SettingsPage.test.tsx`

预期：失败，因为 RuntimeDiagnostics 尚不存在。

- [x] **步骤 3：实现最小功能**

RuntimeDiagnostics 使用 React Query 加载 `listAgentSessions(workspaceId)` 和 session detail。运行自检时复用最近的 `test.echo` session，否则创建新 session，再用固定非敏感输入启动 run。`useAgentEvents` 只提供连接和增量事件；run 终态后重新获取 session detail。

面板只显示产品状态和整理后的事件，不展示 checkpoint、原始 payload 或开发调试 JSON。使用 `aria-live="polite"` 告知连接和 run 变化；375px 下事件项和操作按钮换行。

- [x] **步骤 4：验证前端和浏览器闭环并提交**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

使用 Playwright 在 1440、1024、768、375px 验证设置页自检、刷新恢复和无水平溢出。创建忽略文件 `docs/verification/r1_2_agent_runtime_sse.md`，然后：

```bash
git add frontend/src/features/settings/RuntimeDiagnostics.tsx frontend/src/features/settings/RuntimeDiagnostics.test.tsx frontend/src/features/settings/SettingsPage.tsx frontend/src/features/settings/SettingsPage.test.tsx frontend/src/app/global.css
git commit -m "feat(runtime): add browser runtime diagnostics"
```

R1.2 验收：确定性 Graph session 可跨进程重启保存；running 变为 interrupted；断线后事件可重放；设置页可完成一次真实 Runtime 自检，浏览器刷新后使用 session detail 和持久化事件恢复状态。
