# R1.5 知识草稿与发布实施计划


**目标：** 把上传资料和领域草稿保留在 Vault 外，通过真实 `knowledge.publish` Graph 与持久化 HITL 审核，再将批准版本幂等发布为 Obsidian-compatible Markdown，并保证 active index 可恢复。

**架构：** `KnowledgeDraftService` 管理 Workspace artifacts 文件和 Runtime SQLite metadata；`PublicationService` 用 action id 驱动 journal、标准渲染、原子写入和 active index。发布请求启动确定性 Graph，批准 handler 执行发布后恢复原 run，前端在知识页复用 ActionCenter。

**技术栈：** FastAPI、Pydantic 2、SQLite/aiosqlite、LangGraph interrupt、python-frontmatter、React、TypeScript、TanStack Query、Vitest、pytest。

**设计复核：** `docs/superpowers/specs/2026-07-12-r1-5-knowledge-publication-design-review.md`

---

## 全局约束

- 普通开发分支直接实现，不创建 worktree、不委派外部 Agent。
- 上传 source 与 draft 在批准前始终位于 `artifacts/`。
- 知识 API 使用稳定 `workspaceId`，不再接受任意 `workspacePath`。
- migration `004_publication.sql` 在 Task 1 一次定义完整 schema，后续任务不回改。
- 草稿编辑使用 version 与 content hash 乐观并发。
- 发布路径由 document type 与稳定 document id 决定。
- Markdown 写入成功即为发布事实；索引失败进入 `index_stale`。
- 外部修改不静默覆盖；重复 action 不重复写文件或索引。
- 只有 `ingested + confirmed_by_user` 文档进入 active scope。
- 每个 Task 后增量更新本地 `docs/verification/r1_5_knowledge_publication.md`。

## 文件结构

新建：

- `backend/app/db/migrations/runtime/004_publication.sql`
- `backend/app/knowledge/workspace_layout.py`
- `backend/app/knowledge/drafts.py`
- `backend/app/knowledge/document_types.py`
- `backend/app/knowledge/frontmatter.py`
- `backend/app/knowledge/atomic_writer.py`
- `backend/app/knowledge/publication.py`
- `backend/app/runtime/knowledge_publication_graph.py`
- `backend/app/schemas/drafts.py`
- `backend/app/api/routes_drafts.py`
- `backend/tests/test_knowledge_drafts.py`
- `backend/tests/test_frontmatter.py`
- `backend/tests/test_atomic_writer.py`
- `backend/tests/test_publication_service.py`
- `backend/tests/test_knowledge_publication_graph.py`
- `backend/tests/test_draft_routes.py`
- `frontend/src/features/knowledge/draftTypes.ts`
- `frontend/src/features/knowledge/draftApi.ts`
- `frontend/src/features/knowledge/DraftReview.tsx`
- `frontend/src/features/knowledge/DraftReview.test.tsx`

修改：

- `backend/app/security/workspace_paths.py`
- `backend/app/api/routes_knowledge.py`
- `backend/app/api/dependencies.py`
- `backend/app/hitl/handlers.py`
- `backend/app/runtime/default_graphs.py`
- `backend/app/runtime/service.py`
- `backend/app/services/search_index.py`
- `backend/app/main.py`
- `backend/app/api/routes_settings.py`
- `backend/app/schemas/settings.py`
- `backend/tests/test_knowledge_routes.py`
- `backend/tests/test_runtime_database.py`
- `backend/tests/test_tool_audit.py`
- `backend/tests/test_hitl_repository.py`
- `frontend/src/features/agent/ActionCenter.tsx`
- `frontend/src/features/agent/ActionCenter.test.tsx`
- `frontend/src/features/knowledge/KnowledgePage.tsx`
- `frontend/src/features/knowledge/KnowledgePage.test.tsx`
- `frontend/src/features/knowledge/knowledgeApi.ts`
- `frontend/src/features/settings/settingsApi.ts`
- `frontend/src/app/layout/AppShell.tsx`

## Task 1：Migration 与 KnowledgeDraftService

**产出：** 完整 publication schema；异步 `create/get/list/update`；draft 正文只写 `artifacts/<domain>/drafts/`。

- [x] **步骤 1：编写失败测试**

在 `backend/tests/test_knowledge_drafts.py` 覆盖：

```python
@pytest.mark.asyncio
async def test_create_draft_writes_outside_vault(service, workspace):
    draft = await service.create(CreateDraftCommand(
        workspace_id="w1", domain="review", document_type="question",
        title="缓存穿透", markdown="# 缓存穿透", source_refs=("source-1",),
        relation_refs=(),
    ))
    assert draft.content_path == f"artifacts/review/drafts/{draft.id}.md"
    assert (workspace / draft.content_path).read_text() == "# 缓存穿透"
    assert not list((workspace / "knowledge-vault").rglob("*.md"))


@pytest.mark.asyncio
async def test_update_rejects_stale_version(service, draft):
    await service.update(draft.id, expected_version=1, markdown="# edited")
    with pytest.raises(DraftVersionChangedError):
        await service.update(draft.id, expected_version=1, markdown="# stale")
```

更新 runtime migration 测试，断言版本为 `[1, 2, 3, 4]`，且 `knowledge_drafts`、`publication_runs` 和必要唯一索引存在。

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_drafts.py tests/test_runtime_database.py -v
```

预期：因 migration 和 `app.knowledge.drafts` 不存在失败。

- [x] **步骤 3：实现最小功能**

`004_publication.sql` 一次定义 draft 与 publication run 全部字段。`initialize_knowledge_artifacts` 逐级创建 artifacts/domain/sources/drafts，并拒绝任一已存在软链接或非目录。`KnowledgeDraftService` 使用独立 aiosqlite 事务保存 metadata，使用 `WorkspacePathPolicy` 和同目录临时文件保存 UTF-8 正文。更新在第二次 hash 检查后 `os.replace`，成功后 version `+1`。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_drafts.py tests/test_runtime_database.py tests/test_tool_audit.py -v
git add backend/app/db/migrations/runtime/004_publication.sql backend/app/knowledge/workspace_layout.py backend/app/knowledge/drafts.py backend/tests/test_knowledge_drafts.py backend/tests/test_runtime_database.py backend/tests/test_tool_audit.py backend/tests/test_hitl_repository.py
git commit -m "feat(knowledge): persist drafts outside vault"
```

## Task 2：上传链路迁移与 Workspace ID

**产出：** source 写入 `artifacts/review/sources/`，上传响应为持久化 draft；知识 API 不再接受 raw path。

- [x] **步骤 1：编写失败测试**

在 `backend/tests/test_knowledge_routes.py` 替换旧 inbox 断言：

```python
def test_upload_creates_source_and_persistent_draft_outside_vault(client, workspace):
    response = client.post(
        "/api/knowledge/sources",
        data={"workspaceId": "w1"},
        files={"file": ("缓存.md", b"# cache", "text/markdown")},
    )
    assert response.status_code == 201
    draft = response.json()
    assert draft["workspaceId"] == "w1"
    assert (workspace / draft["contentPath"]).is_file()
    assert list((workspace / "artifacts/review/sources").iterdir())
    assert not list((workspace / "knowledge-vault").rglob("*.md"))
```

继续覆盖 Unicode 文件名、路径形文件名、source/draft 软链接和未知 workspace id。

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_routes.py -v
```

预期：旧接口仍要求 `workspacePath`，且写入 Vault inbox。

- [x] **步骤 3：实现最小功能**

`routes_knowledge` 通过 `WorkspaceService` 解析 `workspaceId`，使用 `review.sources` scope 保存 source，再调用当前确定性 question draft 生成器和 `KnowledgeDraftService`。后端 legacy Workspace resource 与前端 `WorkspaceConfig` 补稳定 id，AppShell 恢复和 Settings 初始化都保留该 id；上传/rescan 只传 id。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_routes.py tests/test_workspace_paths.py -v
git add backend/app/api/routes_knowledge.py backend/app/api/routes_settings.py backend/app/api/dependencies.py backend/app/schemas/drafts.py backend/app/schemas/settings.py backend/tests/test_knowledge_routes.py frontend/src/features/settings/settingsApi.ts frontend/src/features/settings/SettingsPage.tsx frontend/src/features/knowledge/knowledgeApi.ts frontend/src/app/layout/AppShell.tsx
git commit -m "refactor(knowledge): keep uploads outside vault"
```

## Task 3：Document Registry、Frontmatter 与原子 Writer

**产出：** 五种 canonical directory、严格 frontmatter、确定性路径和外部修改保护。

- [x] **步骤 1：编写失败测试**

`backend/tests/test_frontmatter.py`：

```python
def test_rendered_document_is_active_and_traceable(document):
    parsed = frontmatter.loads(render_published_document(document))
    assert parsed["status"] == "ingested"
    assert parsed["ingestion"]["confirmed_by_user"] is True
    assert parsed["provenance"]["session_id"] == "s1"


@pytest.mark.parametrize("key", ["api_key", "authorization", "system_prompt", "checkpoint"])
def test_forbidden_metadata_is_rejected(key, document):
    with pytest.raises(PublishedDocumentValidationError):
        render_published_document(document.model_copy(update={"extra_metadata": {key: "x"}}))
```

`backend/tests/test_atomic_writer.py` 覆盖 fsync、replace、expected hash 冲突、临时文件清理和文件内容保持。

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_frontmatter.py tests/test_atomic_writer.py -v
```

- [x] **步骤 3：实现最小功能**

Registry 映射 `source/question/session_report/mastery_report/concept` 到现有 Vault 目录。Pydantic frontmatter models `extra="forbid"`。`atomic_write_text` 在同目录创建 temp、flush/fsync、重验 existing hash 后 replace，并在 finally 清理 temp。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_frontmatter.py tests/test_atomic_writer.py tests/test_markdown.py -v
git add backend/app/knowledge/document_types.py backend/app/knowledge/frontmatter.py backend/app/knowledge/atomic_writer.py backend/app/schemas/knowledge.py backend/app/services/markdown.py backend/tests/test_frontmatter.py backend/tests/test_atomic_writer.py backend/tests/test_markdown.py
git commit -m "feat(knowledge): render canonical vault documents"
```

## Task 4：Publication Journal、Service 与 Active Index

**产出：** action-id 幂等发布状态机；只索引 active frontmatter；rescan 修复 index stale。

- [x] **步骤 1：编写失败测试**

`backend/tests/test_publication_service.py` 覆盖：

```python
published = await service.publish_approved_action(action)
assert published.status == "completed"
assert published.relative_path == "10_question_bank/question-1.md"
again = await service.publish_approved_action(action)
assert again == published
assert len(list((vault / "10_question_bank").glob("*.md"))) == 1
```

另测 stale draft、外部文件 hash 冲突、文件成功后 index 异常进入 `index_stale`。扩展 `test_search_index.py`：未确认文档不进入 FTS，rescan 修复 stale publication。

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_publication_service.py tests/test_search_index.py -v
```

- [x] **步骤 3：实现最小功能**

`PublicationRepository` 对 journal 状态使用 expected-state 更新。Service 校验 action draft/version/hash，渲染并写入稳定路径，随后 upsert manifest/FTS；索引失败保留文件和 result hash。rescan 解析严格 frontmatter，只写 active 文档并清理已不存在或不 active 的派生行。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_publication_service.py tests/test_search_index.py tests/test_knowledge_routes.py -v
git add backend/app/knowledge/publication.py backend/app/services/search_index.py backend/app/api/routes_knowledge.py backend/tests/test_publication_service.py backend/tests/test_search_index.py backend/tests/test_knowledge_routes.py
git commit -m "feat(knowledge): publish drafts with recoverable index"
```

## Task 5：真实 knowledge.publish Graph 与 HITL Handler

**产出：** publish request 通过真实 run 创建 action；批准执行 publication；拒绝不写 Vault；重启可恢复。

- [x] **步骤 1：编写失败测试**

`backend/tests/test_knowledge_publication_graph.py` 覆盖：

```python
run = await runtime.request_draft_publication("draft-1")
waiting = await runtime.wait(run.id)
assert waiting.status == "waiting_for_approval"
action = (await runtime.list_actions("w1", status="pending"))[0]
assert action.action_type == "knowledge.publish"

await runtime.approve_action(action.id, approve_command(action))
completed = await runtime.wait(run.id)
assert completed.status == "completed"
assert list(vault.rglob("*.md"))
```

另测拒绝、编辑批准、相同 draft version 重复请求、handler delivery 失败后重启恢复。

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_publication_graph.py -v
```

- [x] **步骤 3：实现最小功能**

注册 `knowledge.publish` Graph version 1。Graph input 为 draft id/version/hash，创建 action 后 interrupt。Workspace Runtime 创建 Draft/Publication services，并把 `KnowledgePublishActionHandler` 注册到 R1.4 Registry。handler 对 rejected no-op；批准时保存允许的 title/markdown 编辑，再发布精确版本。`AgentRuntime.request_draft_publication` 复用同 draft version 的 waiting run。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_knowledge_publication_graph.py tests/test_hitl_service.py tests/test_hitl_restart.py -v
git add backend/app/runtime/knowledge_publication_graph.py backend/app/runtime/default_graphs.py backend/app/runtime/service.py backend/app/hitl/handlers.py backend/app/knowledge/publication.py backend/tests/test_knowledge_publication_graph.py
git commit -m "feat(knowledge): approve publication through runtime"
```

## Task 6：Draft REST API 与 Typed Errors

**产出：** list/detail/update/publish-request；版本和外部冲突稳定映射；API 不暴露绝对路径。

- [x] **步骤 1：编写失败测试**

`backend/tests/test_draft_routes.py` 覆盖 workspace 过滤、详情正文、PATCH version、stale 409、publish request 返回 session/run、Vault 在批准前为空、未知 draft 404、响应无绝对 path。

```python
response = client.post(f"/api/knowledge/drafts/{draft_id}/publish-request")
assert response.status_code == 202
assert response.json()["status"] in {"running", "waiting_for_approval"}
assert not list(vault.rglob("*.md"))
```

- [x] **步骤 2：运行 RED**

```bash
cd backend
.venv/bin/pytest tests/test_draft_routes.py -v
```

- [x] **步骤 3：实现最小功能**

新增 camelCase schemas 和 routes。PATCH 只接受 `{version, title?, markdown}`。publish-request 由 runtime 启动 Graph，不直接调用 writer。映射 `draft_version_changed`、`external_document_changed`、`publication_failed`，错误正文不返回内部异常。

- [x] **步骤 4：验证并提交**

```bash
cd backend
.venv/bin/pytest tests/test_draft_routes.py tests/test_hitl_routes.py tests/test_agent_routes.py -v
git add backend/app/schemas/drafts.py backend/app/api/routes_drafts.py backend/app/api/dependencies.py backend/app/main.py backend/tests/test_draft_routes.py
git commit -m "feat(knowledge): expose draft review workflow"
```

## Task 7：DraftReview、ActionCenter 复用与阶段收口

**产出：** 知识页可恢复、编辑、请求发布、同页确认并查看发布结果；完成浏览器和阶段文档验收。

- [x] **步骤 1：编写失败测试**

`DraftReview.test.tsx` 覆盖草稿加载、带版本编辑、409 后重载、publish request、pending 状态、published path、index-stale 和 external conflict。扩展 ActionCenter 测试，断言 `showDiagnostic={false}` 时无诊断按钮，`actionType="knowledge.publish"` 只展示发布 action。

- [x] **步骤 2：运行 RED**

```bash
cd frontend
pnpm test -- DraftReview.test.tsx KnowledgePage.test.tsx ActionCenter.test.tsx
```

- [x] **步骤 3：实现最小功能**

新增 typed draft API 与 DraftReview。知识页使用稳定 workspace id，上传后刷新持久化草稿。ActionCenter 增加可选 `showDiagnostic` 和 `actionType`，知识页关闭测试入口并过滤发布 action。决定完成后刷新 drafts/actions，不在请求发布时提前显示成功。

- [x] **步骤 4：完整自动验证**

```bash
cd backend && .venv/bin/pytest
cd ../frontend && pnpm test && pnpm exec tsc --noEmit && pnpm build
cd .. && git diff --check
```

- [ ] **步骤 5：浏览器和重启验收**

> 自动验证与文档门禁已通过；浏览器/重启人工验收步骤已写入 `docs/verification/r1_5_knowledge_publication.md` 第 4、5 节，由用户在本地执行（独立 app data/Workspace、桌面与移动宽度）。

在独立 app data/Workspace 完成：上传、刷新恢复、编辑、请求发布、批准、重复请求、拒绝、后端重启、外部修改冲突、index stale/rescan；检查 1440x1000 与 375x812 无溢出，控制台无 warning/error。

- [x] **步骤 6：整理本地文档并运行门禁**

将 `docs/verification/r1_5_knowledge_publication.md` 整理为最终用户指南，生成 `docs/learning/r1-5-knowledge-publication/` 七件套，对照 R1.4 深度后运行：

```bash
python3 scripts/check_stage_docs.py \
  --verification docs/verification/r1_5_knowledge_publication.md \
  --learning docs/learning/r1-5-knowledge-publication/
```

- [x] **步骤 7：提交阶段收口**

```bash
git add frontend/src/features/agent/ActionCenter.tsx frontend/src/features/agent/ActionCenter.test.tsx frontend/src/features/knowledge backend/app progress.md findings.md task_plan.md docs/superpowers/plans/2026-07-10-r1-5-knowledge-publication.md
git commit -m "feat(knowledge): review and publish knowledge drafts"
```

## R1.5 完成定义

- source 与 draft 均在 Vault 外；
- 浏览器刷新后草稿仍存在；
- stale version/hash 不覆盖新内容；
- 发布必须经过真实持久化 HITL；
- 批准只生成一份 deterministic Markdown；
- 拒绝不写 Vault；
- 外部修改保持不变并返回冲突；
- active index 只包含确认文档；
- index stale 可由 rescan 修复；
- 全量测试、构建、浏览器验收和阶段文档门禁通过。
