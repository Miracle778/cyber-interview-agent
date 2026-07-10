# R1 共享 Agent 底座实施总计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 交付 R1 spec 中定义的共享 Provider、Agent Runtime、沙箱、HITL、知识发布和单题复习集成底座。

**架构：** 按六个可独立审阅的纵向切片执行。每个切片都包含 schema、后端服务、API、前端入口、测试和人工验证；后续切片只依赖前序切片已经提交的公共接口。

**技术栈：** React 19、TypeScript、Vite、FastAPI、Pydantic 2、SQLite、LangGraph、LangChain OpenAI/Anthropic adapter、系统密钥链、Vitest、Playwright、pytest。

## 全局约束

- 遵循 `docs/superpowers/specs/2026-07-10-r1-shared-agent-foundation-design.md`。
- 后端文件访问始终限制在已注册 Workspace 内。
- API Key 不能进入 Vault、浏览器持久化、日志、SSE payload 或 API 响应。
- Provider 元数据全局保存，模型用途绑定按 Workspace 保存。
- 产品消息和 run 状态与 LangGraph checkpoint 内部数据分离。
- REST 承载命令，SSE 承载已持久化的 Runtime 事件。
- Agent 工具默认拒绝，并从 Graph 专属 allowlist 注入。
- Agent 输出在持久化 HITL action 批准前始终是领域草稿。
- 自动测试使用 Fake Provider 和 Fake SecretStore，不依赖网络或真实 API Key。
- 不得暂存 `docs/my_idea.md`、`docs/product_roadmap.md`、`task_plan.md`、`findings.md` 和 `progress.md`。
- 每个实现任务结束后，Codex 必须审阅 diff 并运行该任务验证，再开始下一任务。

---

## 计划包

按以下顺序执行计划：

1. `docs/superpowers/plans/2026-07-10-r1-1-provider-settings.md`
2. `docs/superpowers/plans/2026-07-10-r1-2-agent-runtime-sse.md`
3. `docs/superpowers/plans/2026-07-10-r1-3-workspace-tool-security.md`
4. `docs/superpowers/plans/2026-07-10-r1-4-persistent-hitl.md`
5. `docs/superpowers/plans/2026-07-10-r1-5-knowledge-publication.md`
6. `docs/superpowers/plans/2026-07-10-r1-6-review-integration.md`

## 跨切片契约

### 应用级数据库

R1.1 产出：

```python
def connect_app_database(data_dir: Path | None = None) -> sqlite3.Connection: ...
def get_provider_service() -> ProviderService: ...
def get_workspace_service() -> WorkspaceService: ...
```

### Workspace Runtime 数据库

R1.2 产出：

```python
def connect_runtime_database(workspace_root: Path) -> sqlite3.Connection: ...
class AgentRuntime:
    async def create_session(self, command: CreateSessionCommand) -> SessionRecord: ...
    async def start_run(self, command: StartRunCommand) -> RunRecord: ...
    async def resume_run(self, run_id: str, resume_value: object | None = None) -> RunRecord: ...
```

### 安全上下文

R1.3 产出：

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    graph_id: str
    allowed_scopes: frozenset[str]
```

### HITL

R1.4 produces:

```python
class HitlService:
    def create_action(self, request: CreatePendingAction) -> PendingAction: ...
    async def approve(self, action_id: str, command: ResolveActionCommand) -> PendingAction: ...
    async def reject(self, action_id: str, command: ResolveActionCommand) -> PendingAction: ...
```

### 知识发布

R1.5 产出：

```python
class PublicationService:
    def request_publication(self, draft_id: str) -> PendingAction: ...
    def publish_approved_draft(self, action: PendingAction) -> PublicationResult: ...
```

### 复习集成

R1.6 注册 Graph ID `review.single`、版本 `1`，要求模型用途 `answer_evaluation` 和 `report_summarization`，允许 scope `review.sources`、`review.drafts` 和只读 `knowledge.active`。

## 验收门槛

每份子计划结束时：

- 运行该计划列出的聚焦前后端测试。
- 运行 `git diff --check`。
- 确认 snapshot、日志、fixture 和 API 响应中没有 secret 值。
- 检查 `git status --short`，只暂存子计划明确列出的文件。
- 开始下一切片前先创建当前子计划的提交。

R1.6 结束时运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
cd ..
pnpm --dir frontend e2e
git diff --check
```

预期：前端测试与构建、后端测试全部通过；在允许绑定 localhost 的环境中 E2E 通过。如果当前沙箱不能绑定端口，记录精确错误，并在沙箱外完成人工浏览器流程后才能声明“场景可用”。

## 完成产物

每个切片在本地忽略目录 `docs/verification/` 下创建验证文档，最后创建 `docs/verification/r1_shared_agent_foundation.md`，内容包括：

- 已实现文件及职责；
- 自动验证输出；
- 两种协议的真实 Provider 人工验证状态；
- 浏览器逐步验证；
- 恢复、HITL、重复发布、冲突和沙箱检查；
- 仍属于 R2 的边界。
