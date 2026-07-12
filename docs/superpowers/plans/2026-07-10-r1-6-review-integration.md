# R1.6 单题复习 Runtime 集成计划


**目标：** 把现有单题复习流程迁移到真实 Provider 模型、持久化 Agent Runtime/SSE、scope 工具、HITL 和批准后 Vault 发布，同时不实现 R2 多题行为。

**架构：** 在 GraphRegistry 注册 graph ID `review.single`、版本 `1`。Runtime 解析 Workspace 的回答评估和报告总结模型绑定，注入受 scope 限制的复习工具集，把报告 Markdown 持久化为知识草稿，并在 PublicationService 写入 Vault 前停在 `knowledge.publish` action。

**技术栈：** LangGraph、LangChain model adapter、Pydantic 结构化输出、FastAPI Agent API、React/TypeScript session UI、SSE、Vitest、Playwright、pytest。

## 全局约束

- 只处理一个问题和一个回答；10/20 题轮次仍属于 R2。
- Graph 使用 Runtime 保存快照的模型用途绑定。
- 评估使用经过校验的结构化输出，报告使用带 provenance 的 Markdown。
- LLM 调用不能直接访问 API Key，也不能自行选择其他 Provider/模型。
- Graph 工具仅限复习 source/draft 和只读 active knowledge。
- 报告发布必须停在 HITL。
- 前端迁移后，旧 `/api/review/run` 和 `/api/review/reports/confirm` 不能继续作为绕过路径。
- 自动测试使用 Fake ChatModelGateway；真实 Provider 调用只用于人工验收。

---

## 文件结构

新建：

- `backend/app/providers/chat_gateway.py` — 按用途绑定的文本/结构化模型调用。
- `backend/app/runtime/model_resolver.py` — 把 run 绑定快照解析为模型和 secret。
- `backend/app/agents/review_contracts.py` — Graph input/state/evaluation/report schemas.
- `backend/app/agents/review_nodes.py` — 选题、评估、报告草稿和发布请求节点。
- `backend/app/agents/review_definition.py` — graph ID `review.single`、版本 `1` 的 GraphDefinition。
- `backend/tests/test_chat_gateway.py`
- `backend/tests/test_review_definition.py`
- `backend/tests/test_review_runtime_integration.py`
- `backend/tests/test_review_provider_errors.py`
- `frontend/src/features/review/SessionList.tsx`
- `frontend/src/features/review/SessionList.test.tsx`
- `frontend/src/features/review/ReviewConversation.tsx`
- `frontend/src/features/review/ReviewConversation.test.tsx`
- `frontend/src/features/review/reviewSessionApi.ts`
- `tests/e2e/r1-review-session.spec.ts`

修改：

- `backend/app/agents/review_state.py` — 用导入契约替换技术切片 state，或删除文件。
- `backend/app/agents/review_graph.py` — 委派给复习 definition，或删除旧 builder。
- `backend/app/agents/tools.py` — 只保留纯选题逻辑。
- `backend/app/api/dependencies.py` — 组合模型 resolver/gateway 并注册 Graph。
- `backend/app/api/routes_review.py` — 迁移后移除绕过 endpoint。
- `backend/app/main.py` — 启动时注册复习 definition。
- `backend/tests/test_review_graph.py` — 替换确定性关键词评估测试。
- `backend/tests/test_review_routes.py` — 断言绕过路由已移除并验证 Runtime 流程。
- `frontend/src/features/review/ReviewPage.tsx` — 持久化 session 组合。
- `frontend/src/features/review/ReviewPage.test.tsx`.
- `frontend/src/features/review/reviewApi.ts` — 删除直接 run/confirm 方法。
- `frontend/src/app/layout/AppShell.tsx` — 不再持有 report/session 真相状态。
- `frontend/src/app/App.test.tsx`.
- `frontend/src/features/settings/settingsApi.ts` — Workspace resource includes stable ID.
- `playwright.config.ts` 和 `tests/e2e/mvp-smoke.spec.ts` — 更新 shell 和 mocked 事件流。

### 任务 1：按用途绑定的 ChatModelGateway

**接口：**
- 产出 `ChatModelGateway.invoke_structured` and `stream_text`.
- 依赖 immutable `ResolvedModelBinding` from the run snapshot.

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_chat_gateway.py`：

```python
@pytest.mark.asyncio
async def test_structured_invocation_uses_snapshot_model(gateway, fake_adapter, binding):
    fake_adapter.structured_result = {"score": "partial", "missing_key_points": ["隔离级别"], "evidence": "用户只回答了事务"}
    result = await gateway.invoke_structured(binding=binding, schema=AnswerEvaluation, messages=[HumanMessage(content="answer")])
    assert result.score == "partial"
    assert fake_adapter.last_model_id == binding.model_id


@pytest.mark.asyncio
async def test_stream_emits_sanitized_deltas(gateway, fake_adapter, binding):
    fake_adapter.text_chunks = ["报", "告"]
    chunks = [chunk async for chunk in gateway.stream_text(binding=binding, messages=[HumanMessage(content="report")])]
    assert chunks == ["报", "告"]
```

Also verify missing secret, 401, model-not-found, rate-limit, timeout, and Pydantic validation failures map to stable Runtime error codes without exposing provider response bodies.

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_chat_gateway.py -v`

预期：失败，因为 gateway/resolver 尚不存在。

- [ ] **步骤 3：实现最小功能**

定义：

```python
@dataclass(frozen=True)
class ResolvedModelBinding:
    role: str
    provider_id: str
    provider_model_id: str
    api_format: str
    base_url: str
    model_id: str
    api_key: str
```

Resolver reads the run's binding snapshot, validates Provider/model still exist, and resolves the secret. Gateway selects adapter by format, performs structured/text invocation, and emits deltas through an injected Runtime event callback. Never serialize `ResolvedModelBinding.api_key`.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_chat_gateway.py -v`

```bash
git add backend/app/providers/chat_gateway.py backend/app/runtime/model_resolver.py backend/tests/test_chat_gateway.py
git commit -m "feat(review): invoke role bound chat models"
```

### 任务 2：复习 Graph 契约与节点

**接口：**
- 产出 Graph ID/version `review.single`/`1`。
- Input contains one ReviewQuestion and `user_answer`.
- State contains evaluation, report Markdown, draft ID, action ID, and decision.

- [ ] **步骤 1：编写失败测试**

创建使用 Fake ChatModelGateway、Fake DraftService 和 Fake PublicationService 的 `backend/tests/test_review_definition.py`，验证：

```python
result = await graph.ainvoke(
    {"question": question.model_dump(), "user_answer": "事务保证原子性", "workspace_id": "w1", "session_id": "s1", "run_id": "r1"},
    config={"configurable": {"thread_id": "s1"}},
)
assert result["evaluation"]["score"] == "partial"
assert result["report_draft_id"] == "draft-1"
assert publication_service.requested_draft_id == "draft-1"
```

The test Graph must interrupt at the publication action; resume with rejected decision completes without a Vault path, and approved decision completes with the handler result.

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_definition.py -v`

预期：失败，因为 contract/node/definition 尚不存在。

- [ ] **步骤 3：实现最小功能**

使用结构化评估：

```python
class AnswerEvaluation(BaseModel):
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str


class SingleReviewInput(BaseModel):
    question: ReviewQuestion
    user_answer: str = Field(min_length=1)
```

节点依次执行：校验输入、使用 `answer_evaluation` 评估回答、使用 `report_summarization` 流式生成报告、创建 `session_report` 草稿、请求发布 action、interrupt，再记录批准/拒绝决定。Prompt 要求证据与用户回答直接相关，并禁止在输出中生成无依据的隐藏推理。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_definition.py -v`

```bash
git add backend/app/agents/review_contracts.py backend/app/agents/review_nodes.py backend/app/agents/review_definition.py backend/app/agents/review_state.py backend/app/agents/review_graph.py backend/app/agents/tools.py backend/tests/test_review_definition.py backend/tests/test_review_graph.py
git commit -m "feat(review): define persistent single review graph"
```

### 任务 3：在 Runtime 注册复习 Graph

**接口：**
- 注册必需 role `answer_evaluation`、`report_summarization`。
- Registers allowed tools/scopes from R1 spec.

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_review_runtime_integration.py`：使用 fake gateway 构造真实 Repository/Runtime，断言 session 创建、run 事件、消息持久化、等待 action、重启、拒绝恢复和批准发布路径。

创建 `backend/tests/test_review_provider_errors.py`，断言绑定缺失、secret 缺失、鉴权和限流失败都会保留 session/input，并暴露稳定错误建议。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_runtime_integration.py tests/test_review_provider_errors.py -v`

预期：失败，因为复习 definition 尚未注册和组合。

- [ ] **步骤 3：组合依赖并注册 definition**

每个应用进程基于 app DB/SecretStore/GraphRegistry 构造一个应用 service container。GraphDefinition 声明：

```python
required_model_roles=frozenset({"answer_evaluation", "report_summarization"})
allowed_tools=frozenset({"read_source", "read_active_knowledge", "write_review_draft"})
allowed_scopes=frozenset({"review.sources", "review.drafts", "knowledge.active"})
```

Runtime 在创建 run 前校验全部必需绑定。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_runtime_integration.py tests/test_review_provider_errors.py -v`

```bash
git add backend/app/api/dependencies.py backend/app/main.py backend/tests/test_review_runtime_integration.py backend/tests/test_review_provider_errors.py
git commit -m "feat(review): register review graph with agent runtime"
```

### 任务 4：移除复习绕过 API

**接口：**
- 浏览器使用通用 Agent/HITL/Draft API。
- Legacy direct Graph invoke and direct Vault confirm endpoints are removed.

- [ ] **步骤 1：替换路由测试**

Update `backend/tests/test_review_routes.py` so `/api/review/run` and `/api/review/reports/confirm` return 404, while generic session/run/action endpoints complete the equivalent fake flow.

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_routes.py -v`

预期：失败，因为绕过路由仍返回 200。

- [ ] **步骤 3：移除绕过 handler**

Delete direct `build_review_graph().invoke`, `save_session_report`, and direct mastery write routes. Remove `routes_review` from `main.py` if it has no remaining resource endpoints. Keep pure mastery helpers only if covered and used by future R2 code; otherwise remove dead imports without unrelated refactors.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_review_routes.py tests/test_review_runtime_integration.py -v`

```bash
git add backend/app/api/routes_review.py backend/app/main.py backend/tests/test_review_routes.py backend/app/services/mastery.py backend/tests/test_mastery.py
git commit -m "refactor(review): remove direct runtime bypass routes"
```

### 任务 5：持久化复习 UI

**接口：**
- 产出 session list and one active ReviewConversation.
- ReviewPage no longer owns authoritative evaluation/report confirmation state.

- [ ] **步骤 1：编写失败测试**

创建 SessionList 和 ReviewConversation 测试，覆盖 session 创建、旧 session 恢复、启动 run、SSE delta、最终评估/报告、刷新详情恢复、interrupted 恢复、pending ActionCenter、拒绝、批准和发布路径。

更新 ReviewPage 测试，断言页面组合这些组件，并要求 Workspace 稳定 ID 和问题草稿。

- [ ] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- SessionList.test.tsx ReviewConversation.test.tsx ReviewPage.test.tsx`

预期：失败，因为持久化复习组件尚不存在。

- [ ] **步骤 3：实现最小功能**

使用通用 Agent API：

```ts
await createSession({ workspaceId, graphId: "review.single", graphVersion: 1, title: question.title });
await startRun(sessionId, { question, userAnswer: answer });
```

SessionList 按 Workspace/Graph 加载。ReviewConversation 合并已持久化 session detail 与实时 SSE，在收到 `hitl.required` 时渲染 ActionCenter，并在 completed/resolved 事件后重新加载详情。

- [ ] **步骤 4：移除 AppShell 中的会话真相状态**

Remove `latestReportMarkdown` and `reportConfirmed` as authoritative values. Keep only current Workspace and selected/generated question until R2 persists question selection. Update flow status from current session resource rather than local callback flags.

- [ ] **步骤 5：运行测试确认通过并提交**

运行：

```bash
pnpm --dir frontend test -- SessionList.test.tsx ReviewConversation.test.tsx ReviewPage.test.tsx App.test.tsx
pnpm --dir frontend build
```

```bash
git add frontend/src/features/review/SessionList.tsx frontend/src/features/review/SessionList.test.tsx frontend/src/features/review/ReviewConversation.tsx frontend/src/features/review/ReviewConversation.test.tsx frontend/src/features/review/reviewSessionApi.ts frontend/src/features/review/ReviewPage.tsx frontend/src/features/review/ReviewPage.test.tsx frontend/src/features/review/reviewApi.ts frontend/src/app/layout/AppShell.tsx frontend/src/app/App.test.tsx frontend/src/features/settings/settingsApi.ts
git commit -m "feat(review): persist single review sessions in the browser"
```

### 任务 6：E2E、真实 Provider 验证与 R1 收口

**接口：**
- Automated E2E uses mocked REST/SSE; no production fake-provider switch.
- Manual verification uses actual configured Providers.

- [ ] **步骤 1：编写浏览器 E2E 测试**

Create `tests/e2e/r1-review-session.spec.ts`. Use Playwright `page.route` for REST resources and fulfill the SSE endpoint with a finite `text/event-stream` body containing persisted event IDs for run start, message completion, draft created, HITL required, and run completion. Assert the UI restores session detail after reload and approving an action shows one published path.

更新 `mvp-smoke.spec.ts` 的标签和状态预期，但不能弱化初始前置条件覆盖。

- [ ] **步骤 2：运行聚焦 E2E**

运行：`pnpm --dir frontend e2e -- --grep "R1 review session"`

预期：允许绑定 localhost 时通过。在受限沙箱中记录精确 EPERM 输出，并在最终验收前于沙箱外运行。

- [ ] **步骤 3：运行完整自动验证**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
cd ..
pnpm --dir frontend e2e
git diff --check
```

预期：所有可运行测试套件通过，不需要真实网络或 API Key。

- [ ] **步骤 4：执行真实 Provider 协议验证**

使用用户本地提供的 secret，分别测试一个 OpenAI-compatible 模型和一个 Anthropic-compatible 模型。只记录 Provider/模型 ID、时间戳、状态、延迟和脱敏错误；不能记录包含凭证的 URL 或 API Key。

随后运行一次真实单题复习，覆盖评估、流式报告、刷新、后端重启/恢复、HITL 编辑/批准、重复批准、Vault 路径、Obsidian 外部编辑冲突和 Workspace 外访问拒绝。

- [ ] **步骤 5：编写最终本地验证指南**

Create ignored `docs/verification/r1_shared_agent_foundation.md` with exact browser steps, code map, generated files, automated outputs, real protocol status, and remaining R2 boundaries.

- [ ] **步骤 6：提交受跟踪的验证测试**

```bash
git add tests/e2e/r1-review-session.spec.ts tests/e2e/mvp-smoke.spec.ts playwright.config.ts
git commit -m "test(review): verify R1 persistent review workflow"
```

R1.6 验收：现有单题用户流程使用真实 Provider adapter 和共享 Runtime；支持刷新/重启恢复；停在持久化 HITL；只发布一份已批准 Markdown；保留外部编辑；拒绝 Workspace 越界；多题行为留给 R2。
