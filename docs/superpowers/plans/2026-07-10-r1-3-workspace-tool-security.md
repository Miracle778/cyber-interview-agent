# R1.3 Workspace 工具安全实施计划


**目标：** 建立默认拒绝的 Agent 工具执行边界、Workspace 相对路径 scope、软链接越界拒绝、脱敏工具审计，以及可在设置页运行的工具安全自检。

**架构：** 所有文件访问统一进入 `WorkspacePathPolicy`，所有 Agent 工具调用统一进入 `ToolRegistry` 与 `BoundToolInvoker`。Runtime 根据持久化 session/run 与 GraphDefinition 构造不可变上下文，再通过 `GraphBuildContext` 向 Graph 注入绑定当前 run 的工具入口。设置页复用 Agent session/run/SSE 协议运行确定性 `test.tool-security` Graph。

**技术栈：** Python pathlib/os、Pydantic 2、FastAPI、SQLite、LangGraph、pytest、React 19、TypeScript、TanStack Query、Vitest。

## 全局约束

- Agent 工具只接受非空相对路径；拒绝绝对路径、`.`、`..`、NUL 和软链接组件。
- 创建文件前验证已存在父目录，真正 I/O 前执行第二次路径校验。
- 工具权限只来自 GraphDefinition 和 Runtime 构造的上下文，不能来自模型输入、Graph state、导入文档或 API payload。
- 未注册工具、未授权 tool、未授权 scope、输入或输出 schema 失败时不得调用 handler。
- R1 不提供任意 shell、任意 HTTP、动态安装或知识发布工具。
- 审计和事件不得包含 API key、请求头、完整正文、异常堆栈或 Workspace 绝对路径。
- `diagnostics.security` 只允许内部 `test.tool-security` Graph 使用。
- 不实现 R1.4 HITL、R1.5 发布、R1.6 真实复习 Graph 或 R2 多题行为。
- 每个 Task 后增量更新本地 `docs/verification/r1_3_workspace_tool_security.md`，不得暂存该文件。

---

## 文件结构

新建：

- `backend/app/security/__init__.py`
- `backend/app/security/workspace_paths.py` — scope 映射、路径校验和稳定错误。
- `backend/app/tools/__init__.py`
- `backend/app/tools/context.py` — 不可变 ToolExecutionContext。
- `backend/app/tools/registry.py` — ToolDefinition、ToolRegistry 和权限/schema 错误。
- `backend/app/tools/file_tools.py` — 授权文本读取、草稿写入和诊断读取。
- `backend/app/tools/audit.py` — 脱敏审计 Repository。
- `backend/app/tools/executor.py` — BoundToolInvoker 和工具事件生命周期。
- `backend/app/tools/defaults.py` — 默认工具注册。
- `backend/app/runtime/graph_build_context.py` — GraphBuildContext 和 invoker protocol。
- `backend/app/runtime/security_diagnostic_graph.py` — `test.tool-security` Graph。
- `backend/app/db/migrations/runtime/002_tool_audit.sql`
- `backend/tests/test_workspace_paths.py`
- `backend/tests/test_tool_registry.py`
- `backend/tests/test_file_tools.py`
- `backend/tests/test_tool_audit.py`
- `backend/tests/test_tool_executor.py`
- `backend/tests/test_security_diagnostic.py`
- `frontend/src/features/settings/SecurityDiagnostics.tsx`
- `frontend/src/features/settings/SecurityDiagnostics.test.tsx`

修改：

- `backend/app/runtime/graph_registry.py` — factory 改用 GraphBuildContext。
- `backend/app/runtime/default_graphs.py` — 适配新 factory 并注册诊断 Graph。
- `backend/app/runtime/run_manager.py` — 构造执行上下文和 GraphBuildContext。
- `backend/app/runtime/service.py` — 为每个 Workspace 注入 ToolRegistry 与审计组件。
- `backend/app/api/routes_knowledge.py` — 现有上传/rescan 使用路径策略。
- `backend/app/services/workspace.py` — 旧兼容函数委派新策略。
- `backend/app/main.py` — 注册稳定安全错误映射。
- `backend/tests/test_run_manager.py`
- `backend/tests/test_knowledge_routes.py`
- `frontend/src/features/agent/agentTypes.ts`
- `frontend/src/features/settings/SettingsPage.tsx`
- `frontend/src/features/settings/SettingsPage.test.tsx`
- `frontend/src/app/global.css`

### 任务 1：WorkspacePathPolicy

**文件：**

- 新建：`backend/app/security/__init__.py`
- 新建：`backend/app/security/workspace_paths.py`
- 测试：`backend/tests/test_workspace_paths.py`

**接口：**

- 产出 `WorkspacePathPolicy(workspace_root: Path)`。
- 产出 `resolve_for_read(scope: str, relative_path: str) -> Path`。
- 产出 `resolve_for_create(scope: str, relative_path: str) -> Path`。
- 产出稳定 `PathPolicyError(code="workspace_path_denied")`。

- [x] **步骤 1：编写失败测试**

覆盖固定 scope、绝对路径、父目录、`.`、NUL、空路径、未知 scope、目标软链接、父目录软链接、读不存在文件、创建时父目录不存在和合法 Unicode 文件名：

```python
def test_rejects_absolute_parent_and_nul(policy):
    for value in ("/etc/passwd", "../secret.txt", "a/../secret.txt", "a\x00b"):
        with pytest.raises(PathPolicyError) as caught:
            policy.resolve_for_read("review.sources", value)
        assert caught.value.code == "workspace_path_denied"


def test_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    scope = workspace / "artifacts" / "review" / "sources"
    scope.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (scope / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathPolicyError):
        WorkspacePathPolicy(workspace).resolve_for_read(
            "review.sources", "escape/secret.txt"
        )
```

- [x] **步骤 2：运行测试确认 RED**

运行：

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_workspace_paths.py -q
```

预期：collection 失败，`app.security.workspace_paths` 尚不存在。

- [x] **步骤 3：实现最小策略**

固定映射：

```python
SCOPE_PATHS = {
    "review.sources": Path("artifacts/review/sources"),
    "review.drafts": Path("artifacts/review/drafts"),
    "knowledge.active": Path("knowledge-vault"),
    "diagnostics.security": Path(".cyber-interview-agent/diagnostics"),
}
```

先做词法组件校验，再逐组件使用 `lstat()` 拒绝软链接，最后使用 `resolve(strict=True)` 或已存在父目录的 real path 验证包含关系。错误消息只返回 scope 和相对路径。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

运行同一测试，预期全部通过；把覆盖行为和真实测试数字写入本地 verification，然后提交：

```bash
git add backend/app/security/__init__.py backend/app/security/workspace_paths.py backend/tests/test_workspace_paths.py
git commit -m "feat(security): enforce workspace path scopes"
```

### 任务 2：ToolExecutionContext、Registry 与 GraphBuildContext

**文件：**

- 新建：`backend/app/tools/__init__.py`
- 新建：`backend/app/tools/context.py`
- 新建：`backend/app/tools/registry.py`
- 新建：`backend/app/runtime/graph_build_context.py`
- 修改：`backend/app/runtime/graph_registry.py`
- 修改：`backend/app/runtime/default_graphs.py`
- 测试：`backend/tests/test_tool_registry.py`
- 修改测试：`backend/tests/test_graph_registry.py`
- 修改测试：`backend/tests/test_run_manager.py`

**接口：**

```python
@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    graph_id: str
    graph_version: int
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class GraphBuildContext:
    checkpointer: object
    invoke_tool: ToolInvokerProtocol
```

- [x] **步骤 1：编写失败测试**

覆盖未知工具、Graph tool allowlist、required scope、未知输入字段、输入/输出 schema、重复注册和模型不能覆盖 context：

```python
def test_scope_is_checked_before_handler(context, registry, called):
    denied = replace(context, allowed_scopes=frozenset())
    with pytest.raises(ToolScopeDeniedError):
        registry.invoke("read_source", denied, {"path": "a.txt"})
    assert called.value is False


def test_context_fields_are_rejected_as_model_input(context, registry):
    with pytest.raises(ToolInputInvalidError):
        registry.invoke(
            "read_source",
            context,
            {"path": "a.txt", "workspace_root": "/tmp/other"},
        )
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_registry.py tests/test_graph_registry.py tests/test_run_manager.py -q
```

预期：新工具和 GraphBuildContext 类型不存在，或旧 factory 签名断言失败。

- [x] **步骤 3：实现 Registry 并迁移 factory 契约**

`ToolDefinition` 使用 `ConfigDict(extra="forbid")` 的 Pydantic input/output model。调用顺序必须是 exists → allowed tool → required scope → input → handler → output。`GraphDefinition.factory` 改为 `Callable[[GraphBuildContext], Any]`，现有 Echo Graph 和测试 Graph 使用 `context.checkpointer`。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

运行聚焦测试和 `git diff --check`，记录 factory 迁移及测试结果，然后提交：

```bash
git add backend/app/tools backend/app/runtime/graph_build_context.py backend/app/runtime/graph_registry.py backend/app/runtime/default_graphs.py backend/tests/test_tool_registry.py backend/tests/test_graph_registry.py backend/tests/test_run_manager.py
git commit -m "feat(security): add deny by default tool registry"
```

### 任务 3：授权文件工具

**文件：**

- 新建：`backend/app/tools/file_tools.py`
- 新建：`backend/app/tools/defaults.py`
- 测试：`backend/tests/test_file_tools.py`

**接口：**

```python
class ReadTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class ReadTextOutput(BaseModel):
    path: str
    text: str
    sha256: str
    byte_count: int


class WriteDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str
    expected_sha256: str | None = None
```

- [x] **步骤 1：编写失败测试**

覆盖 UTF-8 读取、最大 `256 KiB`、正式知识只读、草稿首次写入、覆盖 hash 匹配/冲突、I/O 前二次校验和诊断 probe 不进入业务目录：

```python
def test_write_requires_matching_hash_for_existing_draft(tool_context, tools):
    tools.invoke("write_review_draft", tool_context, {
        "path": "draft.md", "content": "first"
    })
    with pytest.raises(DraftVersionChangedError):
        tools.invoke("write_review_draft", tool_context, {
            "path": "draft.md",
            "content": "second",
            "expected_sha256": "stale",
        })
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_file_tools.py -q
```

预期：`app.tools.file_tools` 和默认注册尚不存在。

- [x] **步骤 3：实现文件工具**

读取先检查 `stat().st_size` 再读取 bytes，严格 UTF-8 解码，返回 SHA-256 和 byte count。写草稿使用临时文件加 `os.replace`，已有文件必须校验 expected hash。handler 在 I/O 前重新调用 WorkspacePathPolicy。`diagnostic_read` 在 `diagnostics.security` 创建固定非敏感 probe 后通过同一读取 helper 返回。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

```bash
git add backend/app/tools/file_tools.py backend/app/tools/defaults.py backend/tests/test_file_tools.py
git commit -m "feat(security): add scoped agent file tools"
```

### 任务 4：工具审计、BoundToolInvoker 与 Runtime 集成

**文件：**

- 新建：`backend/app/db/migrations/runtime/002_tool_audit.sql`
- 新建：`backend/app/tools/audit.py`
- 新建：`backend/app/tools/executor.py`
- 修改：`backend/app/runtime/run_manager.py`
- 修改：`backend/app/runtime/service.py`
- 修改：`backend/app/main.py`
- 测试：`backend/tests/test_tool_audit.py`
- 测试：`backend/tests/test_tool_executor.py`
- 修改测试：`backend/tests/test_run_manager.py`

**接口：**

```python
class BoundToolInvoker:
    async def invoke_tool(
        self, name: str, raw_input: dict[str, object]
    ) -> dict[str, object]: ...
```

审计表保存 `tool_name/session_id/run_id/status/error_code/latency_ms/resource_scope/resource_path/resource_sha256/created_at`，不保存正文和原始异常。

- [x] **步骤 1：编写失败测试**

覆盖 migration、先审计再事件、started/completed/failed、递归 secret 脱敏、正文移除、绝对路径移除、聚合 tokenUsage 保留，以及 RunManager 注入的 context 不能被 Graph state 替换：

```python
@pytest.mark.asyncio
async def test_unknown_tool_is_audited_and_emits_safe_failure(invoker, repository):
    with pytest.raises(ToolNotAllowedError):
        await invoker.invoke_tool("shell", {"authorization": "Bearer secret"})
    audit = repository.list_tool_audits(run_id="r1")[-1]
    event = repository.list_events("s1")[-1]
    assert audit.error_code == "tool_not_allowed"
    assert event.type == "tool.failed"
    assert "secret" not in str(event.payload)
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_audit.py tests/test_tool_executor.py tests/test_run_manager.py -q
```

预期：migration、AuditRepository 和 BoundToolInvoker 尚不存在。

- [x] **步骤 3：实现审计和 Runtime 注入**

AgentRuntime 每个 Workspace context 共享 ToolRegistry，但审计 Repository 使用该 Workspace runtime connection。RunManager 在每次 execute/resume 时根据持久化 session/run、Workspace root 和 GraphDefinition 构造 ToolExecutionContext，再构造 GraphBuildContext。Invoker 捕获稳定 ToolError，持久化安全元数据并发布安全事件；未知异常只暴露 `tool_execution_failed`。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

```bash
git add backend/app/db/migrations/runtime/002_tool_audit.sql backend/app/tools/audit.py backend/app/tools/executor.py backend/app/runtime/run_manager.py backend/app/runtime/service.py backend/app/main.py backend/tests/test_tool_audit.py backend/tests/test_tool_executor.py backend/tests/test_run_manager.py
git commit -m "feat(security): audit authorized agent tools"
```

### 任务 5：迁移现有文件边界

**文件：**

- 修改：`backend/app/api/routes_knowledge.py`
- 修改：`backend/app/services/workspace.py`
- 修改：`backend/app/main.py`
- 修改测试：`backend/tests/test_knowledge_routes.py`
- 修改测试：`backend/tests/test_workspace.py`

**接口：**

- 现有 upload/rescan 浏览器契约保持不变。
- 路径拒绝统一映射 `400 workspace_path_denied`。
- 旧 `ensure_inside_workspace` 若仍被引用，只能委派 WorkspacePathPolicy。

- [x] **步骤 1：编写失败路由测试**

覆盖上传文件名穿越、软链接 inbox、Workspace 缺失、合法 Unicode 文件名和正常 rescan：

```python
def test_upload_rejects_symlinked_inbox(client, workspace, outside):
    inbox = workspace / "knowledge-vault" / "00-inbox"
    inbox.rmdir()
    inbox.symlink_to(outside, target_is_directory=True)
    response = client.post(
        "/api/knowledge/sources",
        data={"workspacePath": str(workspace)},
        files={"file": ("notes.md", b"safe", "text/markdown")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "workspace_path_denied"
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_knowledge_routes.py tests/test_workspace.py -q
```

预期：至少软链接和稳定错误码测试失败。

- [x] **步骤 3：迁移路径边界**

Route 先使用 WorkspaceService/既有兼容接口解析注册 Workspace，再使用 WorkspacePathPolicy 生成目标。上传文件名只作为单个相对文件名处理；rescan 所有路径进入同一策略。保留现有响应 schema，不在此任务重做摄取业务。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

```bash
git add backend/app/api/routes_knowledge.py backend/app/services/workspace.py backend/app/main.py backend/tests/test_knowledge_routes.py backend/tests/test_workspace.py
git commit -m "refactor(security): enforce workspace policy on file routes"
```

### 任务 6：确定性工具安全诊断 Graph

**文件：**

- 新建：`backend/app/runtime/security_diagnostic_graph.py`
- 修改：`backend/app/runtime/default_graphs.py`
- 测试：`backend/tests/test_security_diagnostic.py`
- 修改测试：`backend/tests/test_agent_routes.py`

**接口：**

```text
graph_id: test.tool-security
graph_version: 1
allowed_tools: diagnostic_read, read_active_knowledge
allowed_scopes: diagnostics.security
```

- [x] **步骤 1：编写失败集成测试**

通过真实 AgentRuntime 创建 session/run 并订阅事件，断言：授权读取 completed、`shell` 为 tool_not_allowed、`read_active_knowledge` 为 tool_scope_denied、`../escape` 为 workspace_path_denied，最终 run completed，事件和审计无 probe 正文/绝对路径/secret。

```python
assert [event.type for event in events].count("tool.completed") == 1
assert {event.payload.get("code") for event in events if event.type == "tool.failed"} == {
    "tool_not_allowed", "tool_scope_denied", "workspace_path_denied"
}
assert repository.get_run(run_id).status == "completed"
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_security_diagnostic.py tests/test_agent_routes.py -q
```

预期：`test.tool-security` 未注册或不能获得绑定工具入口。

- [x] **步骤 3：实现诊断 Graph**

Graph 顺序执行四项检查并捕获预期 ToolError。每项预期拒绝必须匹配精确 code，否则抛出诊断失败；所有边界按预期工作时返回非敏感 assistant summary。诊断不读取用户文件，不写 review sources/drafts/Vault。

- [x] **步骤 4：验证 GREEN，更新 verification 并提交**

```bash
git add backend/app/runtime/security_diagnostic_graph.py backend/app/runtime/default_graphs.py backend/tests/test_security_diagnostic.py backend/tests/test_agent_routes.py
git commit -m "feat(security): add deterministic tool security diagnostic"
```

### 任务 7：设置页工具安全自检与阶段验收

**文件：**

- 新建：`frontend/src/features/settings/SecurityDiagnostics.tsx`
- 新建：`frontend/src/features/settings/SecurityDiagnostics.test.tsx`
- 修改：`frontend/src/features/agent/agentTypes.ts`
- 修改：`frontend/src/features/settings/SettingsPage.tsx`
- 修改：`frontend/src/features/settings/SettingsPage.test.tsx`
- 修改：`frontend/src/app/global.css`
- 本地新建/更新：`docs/verification/r1_3_workspace_tool_security.md`
- 本地新建：`docs/learning/r1-3-tool-security/`
- 修改：`task_plan.md`
- 修改：`findings.md`
- 修改：`progress.md`

**接口：**

- 产出 `SecurityDiagnostics({ workspaceId })`。
- 创建/恢复 `test.tool-security` version 1 session。
- 使用现有 `agentApi` 与 `useAgentEvents`，不新增第二套运行 API。

- [x] **步骤 1：编写失败前端测试**

覆盖无 session、恢复最近诊断、点击运行、四项检查、历史 run 隔离、失败建议、重复事件去重和无 Workspace 时不渲染：

```tsx
expect(await screen.findByText("工具安全策略已就绪")).toBeInTheDocument();
fireEvent.click(screen.getByRole("button", { name: "运行安全自检" }));
expect(await screen.findByText("授权读取通过")).toBeInTheDocument();
expect(screen.getByText("未注册工具已拒绝")).toBeInTheDocument();
expect(screen.getByText("未授权 Scope 已拒绝")).toBeInTheDocument();
expect(screen.getByText("路径越界已拒绝")).toBeInTheDocument();
```

- [x] **步骤 2：运行测试确认 RED**

```bash
cd frontend
pnpm test -- SecurityDiagnostics.test.tsx SettingsPage.test.tsx
```

预期：SecurityDiagnostics 尚不存在。

- [x] **步骤 3：实现独立诊断卡片**

卡片与 Agent Runtime 并列，不嵌套。只展示整理后的检查名、状态、错误 code 和相对资源；不渲染原始 payload。终态事件后 refetch session detail，当前 run 事件决定状态，375px 下按钮与检查行换行。

- [x] **步骤 4：运行全量自动验证**

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest -q
cd ../frontend
pnpm test
pnpm build
cd ..
git diff --check
```

预期：后端、前端、类型检查、production build 和 diff check 全部通过。

- [x] **步骤 5：浏览器、审阅、文档与提交**

在 1440x1000、1024x768、768x1024、375x812 验证：创建/恢复安全 session、四项检查、重复运行、刷新重放、无水平溢出和无控制台错误。独立代码审阅必须无未解决 Critical/Important。

增量完成并最终刷新：

```text
docs/verification/r1_3_workspace_tool_security.md
docs/learning/r1-3-tool-security/
```

更新产品状态和理解债务后提交正式文件：

```bash
git add frontend/src/features/settings/SecurityDiagnostics.tsx frontend/src/features/settings/SecurityDiagnostics.test.tsx frontend/src/features/agent/agentTypes.ts frontend/src/features/settings/SettingsPage.tsx frontend/src/features/settings/SettingsPage.test.tsx frontend/src/app/global.css task_plan.md findings.md progress.md
git commit -m "feat(security): add browser tool security diagnostics"
```

## R1.3 最终验收

- 未注册工具和未授权 scope 在 handler 前失败；
- 绝对路径、父目录、NUL 和软链接越界被拒绝；
- 授权复习读写保持在固定 scope 内；
- 工具审计与事件先持久化并且不包含 secret、完整正文或绝对路径；
- 设置页可运行、重复运行并刷新恢复工具安全自检；
- verification 与 learning 材料已在产品目录生成，合并后必须显式同步到主仓库并验证存在；
- 产品成熟度更新为“R1.3 工具安全切片可人工验证”，所有权状态单独记录；
- 下一产品任务为 R1.4 持久化 HITL，R1.3 非阻塞所有权练习不阻塞继续开发。
