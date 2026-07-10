# R1.3 Workspace 工具安全实施计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 落实默认拒绝的 Agent 工具、Workspace 相对路径 scope、软链接越界拒绝和脱敏工具审计事件。

**架构：** 所有 Agent 文件访问统一进入 `WorkspacePathPolicy`，所有 Agent 可调用操作统一进入 `ToolRegistry`。Runtime 注入不可变执行上下文；注册工具在调用领域函数前校验输入/输出 schema 和权限。

**技术栈：** Python pathlib/os、Pydantic 2、FastAPI service 依赖、SQLite 审计记录、LangGraph 工具封装、pytest。

## 全局约束

- Agent 工具只接受相对路径。
- 创建文件前解析并验证已存在父目录。
- 拒绝绝对路径、路径穿越、NUL byte、未授权 scope 和软链接越界。
- 工具权限来自 GraphDefinition，不能来自模型输入或导入文档。
- R1 不提供任意 HTTP 工具。
- 审计事件只包含元数据，不包含 API Key 或完整敏感文件正文。

---

## 文件结构

新建：

- `backend/app/security/workspace_paths.py` — 路径校验和 scope 根目录。
- `backend/app/tools/context.py` — 不可变 ToolExecutionContext。
- `backend/app/tools/registry.py` — ToolDefinition, registry, permission errors.
- `backend/app/tools/file_tools.py` — 已授权读取和创建草稿操作。
- `backend/app/tools/audit.py` — 脱敏工具审计 Repository/事件。
- `backend/tests/test_workspace_paths.py`
- `backend/tests/test_tool_registry.py`
- `backend/tests/test_file_tools.py`
- `backend/tests/test_tool_audit.py`

修改：

- `backend/app/db/migrations/runtime/002_tool_audit.sql` — 在 R1.2 后追加工具审计 schema。
- `backend/app/runtime/graph_registry.py` — typed tool/scope 声明。
- `backend/app/runtime/run_manager.py` — 注入 ToolExecutionContext 并发送工具事件。
- `backend/app/agents/tools.py` — 仅保留纯复习逻辑；文件操作迁移到注册工具。
- `backend/app/api/routes_knowledge.py` — 保持 API 行为并使用路径策略处理上传目标。

### 任务 1：WorkspacePathPolicy

**接口：**
- 产出 `resolve_for_read(scope, relative_path)` and `resolve_for_create(scope, relative_path)`.
- 依赖 registered Workspace root and a fixed scope-to-directory map.

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_workspace_paths.py`：

```python
def test_rejects_absolute_and_parent_paths(policy):
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("review.sources", "/etc/passwd")
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("review.sources", "../secret.txt")


def test_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    (workspace / "artifacts" / "review" / "sources").mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (workspace / "artifacts" / "review" / "sources" / "escape").symlink_to(outside, target_is_directory=True)
    policy = WorkspacePathPolicy(workspace)
    with pytest.raises(PathPolicyError):
        policy.resolve_for_read("review.sources", "escape/secret.txt")


def test_create_validates_existing_parent(policy):
    target = policy.resolve_for_create("review.drafts", "draft.md")
    assert target.name == "draft.md"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_workspace_paths.py -v`

预期：失败，因为 WorkspacePathPolicy 尚不存在。

- [ ] **步骤 3：实现最小功能**

Define a fixed map for R1:

```python
SCOPE_PATHS = {
    "review.sources": Path("artifacts/review/sources"),
    "review.drafts": Path("artifacts/review/drafts"),
    "knowledge.active": Path("knowledge-vault"),
}
```

拒绝 NUL、绝对路径、空路径、`.` 和 `..` 组件。解析授权根目录和现有父目录，断言包含关系，拒绝软链接组件，并在每次文件操作前立即重新校验。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_workspace_paths.py -v`

```bash
git add backend/app/security/workspace_paths.py backend/tests/test_workspace_paths.py
git commit -m "feat(security): enforce workspace path scopes"
```

### 任务 2：ToolExecutionContext 与 Registry

**接口：**
- 产出 immutable context and `ToolRegistry.invoke(name, context, raw_input)`.
- ToolDefinition includes schemas, risk, required scope, and audit policy.

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_tool_registry.py`：

```python
def test_unregistered_tool_is_denied(context):
    with pytest.raises(ToolNotAllowedError):
        ToolRegistry().invoke("shell", context, {})


def test_scope_is_checked_before_tool_runs(context, registered_tool):
    context = replace(context, allowed_scopes=frozenset())
    with pytest.raises(ToolScopeDeniedError):
        registered_tool.registry.invoke("read_source", context, {"path": "a.txt"})
    assert registered_tool.called is False


def test_model_input_cannot_replace_context(context, registered_tool):
    registered_tool.registry.invoke("read_source", context, {"path": "a.txt", "workspace_root": "/tmp/other"})
    assert registered_tool.received_context is context
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_registry.py -v`

预期：失败，因为工具模块尚不存在。

- [ ] **步骤 3：实现最小功能**

Use Pydantic input/output models. Reject unknown input fields, validate required scope before invocation, and return only output schema data. Registry registration is startup-only; duplicate tool names fail fast.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_registry.py -v`

```bash
git add backend/app/tools/context.py backend/app/tools/registry.py backend/app/runtime/graph_registry.py backend/tests/test_tool_registry.py
git commit -m "feat(security): add deny by default tool registry"
```

### 任务 3：授权文件工具

**接口：**
- 产出 `read_source`, `read_active_knowledge`, and `write_review_draft` registered tools.
- 文件工具只依赖 context 和 WorkspacePathPolicy。

- [ ] **步骤 1：编写失败测试**

Create `backend/tests/test_file_tools.py` and assert UTF-8 reads, bounded maximum bytes, draft writes only under `review.drafts`, active knowledge is read-only, and a symlink swapped immediately before I/O is rejected by the second validation.

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_file_tools.py -v`

预期：失败，因为文件工具尚不存在。

- [ ] **步骤 3：实现最小功能**

使用以下 schema：

```python
class ReadTextInput(BaseModel):
    path: str


class ReadTextOutput(BaseModel):
    path: str
    text: str
    sha256: str


class WriteDraftInput(BaseModel):
    path: str
    content: str
    expected_sha256: str | None = None
```

读取必须有明确 byte 上限，覆盖保护使用 expected hash。这些工具不能调用 Publication。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_file_tools.py -v`

```bash
git add backend/app/tools/file_tools.py backend/tests/test_file_tools.py
git commit -m "feat(security): add scoped agent file tools"
```

### 任务 4：工具审计与 Runtime 集成

**接口：**
- 产出 sanitized `ToolAuditRepository.record`.
- RunManager 在 Registry 授权后发出 `tool.started/completed/failed`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_tool_audit.py`，断言审计行包含 tool/session/run/status/latency/resource hash，同时递归删除 `apiKey`、`authorization`、`secret`、`accessToken`、`refreshToken` 和完整正文。保留 `tokenUsage`、`inputTokens`、`outputTokens` 等聚合字段。

新增 RunManager 集成测试：导入 prompt 请求 `shell` 工具时，Runtime 不执行任何调用，并发出 code 为 `tool_not_allowed` 的 `tool.failed`。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_audit.py tests/test_run_manager.py -v`

预期：失败，因为审计集成尚不存在。

- [ ] **步骤 3：实现最小功能**

Runtime 根据已注册的 Workspace/session/run/Graph 元数据构造 ToolExecutionContext，取 Graph scope 与 ToolDefinition scope 的交集，通过 Registry 调用，记录脱敏审计并发送脱敏事件。模型提供的值永远不能填充 context 字段。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_tool_audit.py tests/test_run_manager.py -v`

```bash
git add backend/app/tools/audit.py backend/app/runtime/run_manager.py backend/app/db/migrations/runtime/002_tool_audit.sql backend/tests/test_tool_audit.py backend/tests/test_run_manager.py
git commit -m "feat(security): audit authorized agent tools"
```

### 任务 5：迁移现有文件边界并验证

**接口：**
- Existing upload/rescan APIs keep their browser contract.
- 所有目标路径都必须经过 WorkspacePathPolicy。

- [ ] **步骤 1：编写失败的路由回归测试**

Extend `test_knowledge_routes.py` with filenames containing traversal segments, symlinked inbox paths, and valid Unicode filenames. Assert invalid paths return stable `workspace_path_denied`; valid upload remains successful.

- [ ] **步骤 2：运行测试确认缺少策略集成时失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_knowledge_routes.py -v`

预期：集成前至少软链接目标测试失败。

- [ ] **步骤 3：让所有现有文件操作经过路径策略**

使用 WorkspaceService + WorkspacePathPolicy 替换 route 内部路径拼接。只有仍有测试 import 时才保留 `ensure_inside_workspace` 弃用兼容层，且实现必须委派给新策略。

- [ ] **步骤 4：运行完整安全验证并提交**

运行：

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_workspace_paths.py tests/test_tool_registry.py tests/test_file_tools.py tests/test_tool_audit.py tests/test_knowledge_routes.py -v
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

Create ignored `docs/verification/r1_3_workspace_tool_security.md`, then:

```bash
git add backend/app/api/routes_knowledge.py backend/app/services/workspace.py backend/tests/test_knowledge_routes.py
git commit -m "refactor(security): enforce workspace policy on file routes"
```

R1.3 验收：未知工具和未授权 scope 在执行前失败；拒绝路径/软链接越界；授权复习读写保持在 scope 内；审计/事件 payload 不包含 secret 或完整敏感正文。
