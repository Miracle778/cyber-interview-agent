# R1.5 知识发布实施计划

> **面向执行 Agent：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 在 Vault 外持久化领域草稿，允许用户审核和编辑，并把已批准版本精确发布一次到 Obsidian-compatible Markdown，同时保证索引更新可恢复。

**架构：** KnowledgeDraftService 管理 Workspace artifacts 下的文件和 Runtime SQLite 中的元数据。PublicationService 用带 journal 的状态机处理 `knowledge.publish` HITL action：校验版本/hash、原子写入标准 Markdown、更新派生索引，并记录完成或 index-stale 恢复状态。

**技术栈：** FastAPI、Pydantic 2、SQLite、python-frontmatter、pathlib/os 原子替换、现有 Vault/manifest/FTS 服务、React、TypeScript、Vitest、pytest。

## 全局约束

- Source 和草稿在明确批准前始终留在 Vault 外。
- 草稿更新使用 version 乐观并发。
- 发布路径由稳定文档 ID/type 决定，不能只依赖用户标题。
- 重复处理 action 返回原路径，不创建重复文件。
- Markdown 写入成功就是发布事实；索引失败标记 index stale。
- 外部已修改的 Vault 文件不能被静默覆盖。
- 只有 `status=ingested` 且 `confirmed_by_user=true` 才进入 active retrieval。

---

## 文件结构

新建：

- `backend/app/db/migrations/runtime/004_publication.sql` — 草稿和 publication journal。
- `backend/app/knowledge/drafts.py` — 草稿 record、文件路径和乐观更新。
- `backend/app/knowledge/document_types.py` — 类型 Registry 和标准 Vault 目录。
- `backend/app/knowledge/frontmatter.py` — 已发布文档 schema 校验和渲染。
- `backend/app/knowledge/atomic_writer.py` — temp/fsync/replace helper。
- `backend/app/knowledge/publication.py` — 发布状态机和 HITL handler。
- `backend/app/schemas/drafts.py` — 草稿资源/命令。
- `backend/app/api/routes_drafts.py` — 列表/详情/更新/请求发布。
- `backend/tests/test_knowledge_drafts.py`
- `backend/tests/test_frontmatter.py`
- `backend/tests/test_atomic_writer.py`
- `backend/tests/test_publication_service.py`
- `backend/tests/test_draft_routes.py`
- `frontend/src/features/knowledge/draftTypes.ts`
- `frontend/src/features/knowledge/draftApi.ts`
- `frontend/src/features/knowledge/DraftReview.tsx`
- `frontend/src/features/knowledge/DraftReview.test.tsx`

修改：

- `backend/app/hitl/handlers.py` — 注册知识发布 handler。
- `backend/app/services/search_index.py` — 感知状态的 upsert 和 stale 修复。
- `backend/app/api/routes_knowledge.py` — rescan active 状态和草稿引用。
- `backend/app/schemas/knowledge.py` — 已发布 provenance/frontmatter 类型。
- `backend/app/services/markdown.py` — 委派标准发布渲染。
- `frontend/src/features/knowledge/KnowledgePage.tsx` — 展示草稿审核/发布状态。
- `frontend/src/features/knowledge/KnowledgePage.test.tsx`.

### 任务 1：草稿迁移与 KnowledgeDraftService

**接口：**
- 产出 `create_draft`, `get_draft`, `list_drafts`, and `update_draft(expected_version)`.
- 草稿正文保存在 `artifacts/<domain>/drafts/<draft-id>.md`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_knowledge_drafts.py`：

```python
def test_create_draft_writes_outside_vault(draft_service, workspace_root):
    draft = draft_service.create_draft(CreateDraftCommand(domain="review", document_type="question", title="缓存穿透", markdown="# 缓存穿透", source_refs=["source-1"], relation_refs=[]))
    assert draft.content_path.startswith("artifacts/review/drafts/")
    assert (workspace_root / draft.content_path).read_text(encoding="utf-8") == "# 缓存穿透"
    assert not list((workspace_root / "knowledge-vault").rglob("*.md"))


def test_update_rejects_stale_version(draft_service, created_draft):
    draft_service.update_draft(created_draft.id, expected_version=created_draft.version, markdown="# edited")
    with pytest.raises(DraftVersionChangedError):
        draft_service.update_draft(created_draft.id, expected_version=created_draft.version, markdown="# stale")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_knowledge_drafts.py -v`

预期：失败，因为草稿 schema/service 尚不存在。

- [ ] **步骤 3：实现最小功能**

Migration creates `knowledge_drafts` and the complete `publication_runs` journal schema up front. Drafts use stable ID, source/relation JSON, relative content path, status/version/hash, and timestamps. Publication rows use unique action ID, stable target path, expected hash, result hash, state, error code, and timestamps. Service uses WorkspacePathPolicy `review.drafts`, writes UTF-8 Markdown atomically, increments version, and recomputes SHA-256 inside one operation boundary.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_knowledge_drafts.py -v`

```bash
git add backend/app/db/migrations/runtime/004_publication.sql backend/app/knowledge/drafts.py backend/tests/test_knowledge_drafts.py
git commit -m "feat(knowledge): persist domain drafts outside vault"
```

### 任务 2：文档类型 Registry 与 Frontmatter

**接口：**
- 产出 `DocumentTypeRegistry.resolve(document_type)` and canonical renderer.
- R1 types: source, question, concept, session_report, mastery_report.

- [ ] **步骤 1：编写失败测试**

Create `backend/tests/test_frontmatter.py` asserting each R1 type maps to its canonical directory, rendered frontmatter includes schema version/ingested/confirmed/provenance, and forbidden metadata keys (`api_key`, `authorization`, `system_prompt`, `checkpoint`) raise validation errors.

使用以下核心断言：

```python
rendered = render_published_document(document)
parsed = frontmatter.loads(rendered)
assert parsed["status"] == "ingested"
assert parsed["ingestion"]["confirmed_by_user"] is True
assert parsed["provenance"]["session_id"] == "s1"
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_frontmatter.py -v`

预期：失败，因为 Registry/renderer 尚不存在。

- [ ] **步骤 3：实现最小功能**

Map exact directories already used by Vault. Generate deterministic relative path `<directory>/<document-id>.md`; title remains human-readable inside Markdown. Pydantic models reject extra provenance/ingestion fields and serialize snake_case frontmatter.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_frontmatter.py -v`

```bash
git add backend/app/knowledge/document_types.py backend/app/knowledge/frontmatter.py backend/app/schemas/knowledge.py backend/app/services/markdown.py backend/tests/test_frontmatter.py
git commit -m "feat(knowledge): render canonical published documents"
```

### 任务 3：原子写入与 Publication Journal

**接口：**
- 产出 `atomic_write_text(target, content, expected_existing_hash)`.
- 产出 publication 状态 prepared/file_written/indexed/completed/index_stale/failed。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_atomic_writer.py`，验证临时文件被替换、通过可注入 helper 调用 fsync、expected hash 不一致时目标保持不变，以及失败后清理临时文件。

Extend runtime migration tests to assert the already-created `publication_runs` table has unique action ID and stable target path. Do not edit migration `004_publication.sql` after Task 1 has committed it.

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_atomic_writer.py -v`

预期：失败，因为 writer/journal 尚不存在。

- [ ] **步骤 3：实现最小功能**

写入同目录临时文件，flush/fsync，重新检查现有 hash，再执行 `os.replace`。Publication journal 状态转换必须带 expected state，保存 target/hash/result，并为重复 action ID 返回已完成 record。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_atomic_writer.py -v`

```bash
git add backend/app/knowledge/atomic_writer.py backend/app/knowledge/publication.py backend/tests/test_atomic_writer.py backend/tests/test_knowledge_drafts.py
git commit -m "feat(knowledge): journal atomic vault publication"
```

### 任务 4：PublicationService 与索引恢复

**接口：**
- 产出 `request_publication(draft_id)` and `publish_approved_draft(action)`.
- 为 `knowledge.publish` 注册 handler。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_publication_service.py`，覆盖批准发布、编辑 payload 生成新草稿版本、重复 action 返回同一路径、过期草稿版本失败、外部编辑冲突失败、索引异常返回 `index_stale`，以及 rescan 修复 active 文档。

```python
result = service.publish_approved_draft(approved_action)
assert result.status == "completed"
assert result.relative_path == "10_question_bank/question-1.md"
again = service.publish_approved_draft(approved_action)
assert again.relative_path == result.relative_path
assert len(list((vault / "10_question_bank").glob("*.md"))) == 1
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_publication_service.py -v`

预期：失败，因为完整 Publication service/handler 尚不存在。

- [ ] **步骤 3：实现最小功能**

请求创建一个以 `draft-id:version:knowledge.publish` 为 key 的 pending action。批准 handler 校验 action/draft/hash，执行渲染、写入、索引和 journal 转换，标记草稿 published 并发送发布事件。文件写入成功但索引失败时保留 Markdown，标记 index stale，发送 `publication.index_stale`，并允许 rescan 补全索引。

覆盖已有 ID 路径前比较 manifest checksum 与真实文件 hash。不一致时抛出 `ExternalDocumentChangedError`，文件保持不变。

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_publication_service.py tests/test_search_index.py -v`

```bash
git add backend/app/knowledge/publication.py backend/app/hitl/handlers.py backend/app/services/search_index.py backend/app/api/routes_knowledge.py backend/tests/test_publication_service.py backend/tests/test_search_index.py
git commit -m "feat(knowledge): publish approved drafts to vault"
```

### 任务 5：草稿 REST API

**接口：**
- 产出 list/detail/update/publish-request endpoints from the spec.
- Update requires current version; publish-request never writes Vault directly.

- [ ] **步骤 1：编写失败测试**

Create `backend/tests/test_draft_routes.py` verifying workspace filtering, full detail, optimistic PATCH, stale 409, publish-request returns pending action, and Vault remains unchanged until action approval.

```python
response = client.post(f"/api/knowledge/drafts/{draft_id}/publish-request", json={})
assert response.status_code == 202
assert response.json()["actionType"] == "knowledge.publish"
assert not list(vault.rglob("*.md"))
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_draft_routes.py -v`

预期：失败，因为草稿 API 尚不存在。

- [ ] **步骤 3：实现最小功能**

PATCH accepts `{version, markdown}` only. Publish request resolves Workspace/session ownership from draft metadata and delegates to PublicationService. Register route and typed errors.

- [ ] **步骤 4：运行测试确认通过并提交**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_draft_routes.py -v`

```bash
git add backend/app/schemas/drafts.py backend/app/api/routes_drafts.py backend/app/api/dependencies.py backend/app/main.py backend/tests/test_draft_routes.py
git commit -m "feat(knowledge): expose draft review and publish requests"
```

### 任务 6：前端草稿审核与切片验证

**接口：**
- 产出 DraftReview and typed draft API.
- KnowledgePage 展示 active draft 及其 publication/action 状态。

- [ ] **步骤 1：编写失败测试**

创建 `DraftReview.test.tsx`，覆盖草稿列表/详情、带版本编辑、过期冲突重载、发布请求、交给 ActionCenter 批准、完成路径、index-stale 建议和外部编辑冲突。

更新 KnowledgePage 测试：后端返回 draft resource 后，通过 DraftReview 展示上传生成草稿，而不是只依赖 AppShell 内存题目状态。

- [ ] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- DraftReview.test.tsx KnowledgePage.test.tsx`

预期：失败，因为 DraftReview/API 尚不存在。

- [ ] **步骤 3：实现最小功能**

定义：

```ts
export interface KnowledgeDraft {
  id: string;
  workspaceId: string;
  documentType: "source" | "question" | "concept" | "session_report" | "mastery_report";
  title: string;
  markdown: string;
  status: "draft" | "review_pending" | "rejected" | "published";
  version: number;
  contentHash: string;
}
```

DraftReview 使用已加载资源的 version 发起 PATCH。请求发布后展示 pending ActionCenter，不能假装发布已经完成。

- [ ] **步骤 4：验证完整切片并提交**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

Create ignored `docs/verification/r1_5_knowledge_publication.md`, then:

```bash
git add frontend/src/features/knowledge/draftTypes.ts frontend/src/features/knowledge/draftApi.ts frontend/src/features/knowledge/DraftReview.tsx frontend/src/features/knowledge/DraftReview.test.tsx frontend/src/features/knowledge/KnowledgePage.tsx frontend/src/features/knowledge/KnowledgePage.test.tsx
git commit -m "feat(knowledge): review and publish knowledge drafts"
```

R1.5 验收：草稿文件保留在 Vault 外；拒绝过期编辑；批准发布只写入一个确定性 Markdown；重复批准幂等；保留外部编辑；索引失败可由 rescan 修复。
