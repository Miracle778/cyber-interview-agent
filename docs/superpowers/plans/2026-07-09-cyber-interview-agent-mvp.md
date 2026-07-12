# Cyber Interview Agent MVP 实施计划

**目标：** 实现 MVP 复习闭环：配置 Provider 和工作区，初始化 Obsidian-compatible 知识库，导入资料，生成题库，运行 LangGraph 复习 agent，生成单轮报告和全局掌握度更新建议。

**架构：** 采用 Web 前后端分离架构，不做桌面端。前端是 React/Vite/TypeScript 单页应用；后端是 Python/FastAPI 服务，负责文件沙箱、Vault 读写、索引、Provider 调用和 LangGraph agent 工作流。知识库源数据始终是 Markdown + YAML frontmatter，SQLite/FTS、关系索引和 LangGraph checkpoint 都是可重建或可迁移的运行时数据。

**技术栈：** React 19、Vite、TypeScript、React Router、TanStack Query、FastAPI、Pydantic v2、Python 3.12、uv、LangGraph、LangChain provider adapters、SQLite FTS5、PyYAML、python-frontmatter、pypdf、pytest、Vitest、Playwright。

## 全局约束

- MVP 只做复习闭环：导入零散面试资料 -> 生成结构化题库 -> agent 对话练习 -> 生成掌握度报告 -> 用报告指导下一轮复习。
- 不做 Tauri/Electron/桌面端壳；第一版通过本地 Web 服务运行。
- 前端不能直接读写本地文件；所有文件操作必须走后端 API。
- 后端只能读写用户配置的 workspace 和 vault，必须做路径沙箱校验。
- 知识库是独立 Obsidian-compatible Vault，不是应用私有数据库。
- Markdown + frontmatter 是长期 source of truth。
- SQLite/FTS、manifest index、relation index、mastery index、LangGraph checkpoint 都是运行时数据，不是唯一真相。
- 摄取、覆盖已审核文档、更新全局掌握度等动作必须有人确认。
- MVP 默认不依赖 embedding；语义检索接口预留，先实现关键词检索和关系检索。
- API key 不写入 Vault；开发期使用后端本地配置文件，产品化时接系统密钥链或专用 secrets store。
- 第一版资料解析支持 Markdown、txt、可提取文本的 PDF。

---

## 技术选型结论

这次按你的方向调整为前后端分离：

- **前端：React + Vite + TypeScript。** React 负责交互 UI；Vite 负责开发服务器和构建；React Router 管页面；TanStack Query 管 API 状态、缓存和请求生命周期。
- **后端：Python + FastAPI。** FastAPI 适合类型清晰的本地/服务端 API，Pydantic schema 能和前端 DTO 对齐，也方便自动生成 OpenAPI。
- **Agent：LangGraph。** 复习 agent 天然是有状态、多节点、可中断、可恢复、需要 HITL 的工作流，LangGraph 比手写状态机更合适。
- **存储：文件系统 + SQLite。** Vault 文件保留给 Obsidian；SQLite 存 manifest、FTS5 搜索索引、关系索引、session/checkpoint 辅助状态。
- **向量库：MVP 不引入独立向量库。** 等关键词检索和关系检索跑通后，再评估 Chroma、LanceDB 或 SQLite 向量扩展。

参考过的官方文档：

- LangGraph 官方说明其适合 long-running、stateful agents，并支持 persistence、HITL、streaming。
- FastAPI 官方定位为基于 Python type hints 的 API 框架，内建 OpenAPI。
- Vite 官方支持 React TypeScript 模板和现代前端构建。
- React 官方建议在需要自定义约束时可用 Vite 从头搭建 React app。

## 计划文件结构

```text
cyber-interview-agent-new/
  frontend/
    package.json
    index.html
    vite.config.ts
    tsconfig.json
    src/
      app/
        App.tsx
        layout/AppShell.tsx
      features/
        settings/
          SettingsPage.tsx
          settingsApi.ts
        review/
          ReviewPage.tsx
          ReviewSessionList.tsx
          ReviewChat.tsx
          ReviewSetupPanel.tsx
          reviewApi.ts
          reviewTypes.ts
        knowledge/
          KnowledgePage.tsx
          knowledgeApi.ts
          knowledgeTypes.ts
      shared/
        api/client.ts
        ui/Button.tsx
        ui/Field.tsx
      test/setup.ts
  backend/
    pyproject.toml
    app/
      main.py
      api/
        routes_settings.py
        routes_knowledge.py
        routes_review.py
      core/
        errors.py
      schemas/
        settings.py
        knowledge.py
        review.py
      services/
        workspace.py
        vault.py
        markdown.py
        search_index.py
        provider_registry.py
        document_ingestion.py
      agents/
        review_state.py
        review_graph.py
        tools.py
      db/
        connection.py
        schema.sql
    tests/
      test_workspace.py
      test_vault.py
      test_search_index.py
      test_review_graph.py
  tests/
    e2e/
      mvp-smoke.spec.ts
  docs/
    superpowers/
      specs/2026-07-09-cyber-interview-agent-mvp-design.md
      plans/2026-07-09-cyber-interview-agent-mvp.md
```

## 稳定接口

前后端 DTO 使用 camelCase JSON：

```ts
export type ProviderFormat = "openai-compatible" | "anthropic-compatible";
export type DocumentStatus = "draft" | "review_pending" | "reviewed" | "ingested" | "stale" | "archived";
export type DocumentType = "source" | "question" | "concept" | "session_report" | "mastery_report";

export interface ProviderConfig {
  id: string;
  name: string;
  apiFormat: ProviderFormat;
  baseUrl: string;
  modelIds: string[];
  activeModelId: string;
  connectivityStatus: "unknown" | "ok" | "failed";
}

export interface WorkspaceConfig {
  workspacePath: string;
  vaultPath: string;
}

export interface VaultDocument {
  id: string;
  path: string;
  title: string;
  type: DocumentType;
  status: DocumentStatus;
  updatedAt: string;
}
```

后端统一错误响应：

```python
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    code: str
    message: str
```

Vault 固定目录：

```python
VAULT_DIRS = [
    "00_inbox",
    "10_question_bank",
    "20_review_sessions",
    "30_mastery",
    "40_concepts",
    "80_manifests",
    "90_exports",
    ".cyber-interview-agent",
]
```

---

### Task 0：搭建前后端工程骨架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/layout/AppShell.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/app/App.test.tsx`
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `pnpm --dir frontend test`、`pnpm --dir frontend build`、`cd backend && uv run pytest` 三条基线命令。

- [ ] **Step 1：创建前端 package**

```json
{
  "name": "cyber-interview-agent-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.0.0",
    "clsx": "^2.1.1",
    "lucide-react": "^0.468.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.0.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "@playwright/test": "^1.49.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.7.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2：创建前端配置和入口**

`frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "strict": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "jsx": "react-jsx",
    "noEmit": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "resolveJsonModule": true,
    "isolatedModules": true
  },
  "include": ["src"]
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Cyber Interview Agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/app/App.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3：创建前端 App**

`frontend/src/app/App.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "./layout/AppShell";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
    </QueryClientProvider>
  );
}

const root = document.getElementById("root");

if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
```

`frontend/src/app/layout/AppShell.tsx`:

```tsx
export function AppShell() {
  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <p>复习闭环 MVP</p>
    </main>
  );
}
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/src/app/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App", () => {
  it("renders the MVP shell", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Cyber Interview Agent" })).toBeInTheDocument();
    expect(screen.getByText("复习闭环 MVP")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4：创建后端工程**

`backend/pyproject.toml`:

```toml
[project]
name = "cyber-interview-agent-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi[standard]>=0.115.0",
  "pydantic>=2.10.0",
  "pydantic-settings>=2.6.0",
  "langgraph>=0.2.0",
  "langchain>=0.3.0",
  "langchain-openai>=0.2.0",
  "langchain-anthropic>=0.3.0",
  "python-frontmatter>=1.1.0",
  "pyyaml>=6.0.0",
  "pypdf>=5.0.0"
]

[dependency-groups]
dev = [
  "pytest>=8.3.0",
  "pytest-asyncio>=0.24.0",
  "httpx>=0.28.0"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="Cyber Interview Agent API")

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

`backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5：验证**

Run:

```bash
pnpm --dir frontend install
pnpm --dir frontend test
pnpm --dir frontend build
cd backend && uv sync && uv run pytest
```

Expected:

- 前端测试通过。
- 前端 build 成功。
- 后端 health 测试通过。

- [ ] **Step 6：提交**

```bash
git add frontend backend
git commit -m "chore: scaffold web frontend and python backend"
```

---

### Task 1：定义 API Schema、错误模型和基础客户端

**Files:**
- Create: `backend/app/core/errors.py`
- Create: `backend/app/schemas/settings.py`
- Create: `backend/app/schemas/knowledge.py`
- Create: `backend/app/schemas/review.py`
- Create: `frontend/src/shared/api/client.ts`
- Create: `frontend/src/features/settings/settingsApi.ts`
- Create: `frontend/src/features/knowledge/knowledgeTypes.ts`
- Create: `frontend/src/features/review/reviewTypes.ts`
- Test: `backend/tests/test_schema.py`
- Test: `frontend/src/shared/api/client.test.ts`

**Interfaces:**
- Produces: 前后端共享的 provider、workspace、document、review DTO。

- [ ] **Step 1：后端 schema**

`backend/app/core/errors.py`:

```python
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    code: str
    message: str
```

`backend/app/schemas/settings.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field

ProviderFormat = Literal["openai-compatible", "anthropic-compatible"]
ConnectivityStatus = Literal["unknown", "ok", "failed"]

class ProviderConfig(BaseModel):
    id: str
    name: str
    api_format: ProviderFormat = Field(alias="apiFormat")
    base_url: str = Field(alias="baseUrl")
    model_ids: list[str] = Field(alias="modelIds")
    active_model_id: str = Field(alias="activeModelId")
    connectivity_status: ConnectivityStatus = Field(default="unknown", alias="connectivityStatus")

    model_config = {"populate_by_name": True}

class WorkspaceConfig(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    vault_path: str = Field(alias="vaultPath")

    model_config = {"populate_by_name": True}
```

`backend/app/schemas/knowledge.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field

DocumentStatus = Literal["draft", "review_pending", "reviewed", "ingested", "stale", "archived"]
DocumentType = Literal["source", "question", "concept", "session_report", "mastery_report"]

class VaultDocument(BaseModel):
    id: str
    path: str
    title: str
    type: DocumentType
    status: DocumentStatus
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}
```

`backend/app/schemas/review.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field

ReviewMode = Literal["weak-point", "random-mixed", "topic-focused", "recent-mistake"]
MasteryState = Literal["unknown", "weak", "partial", "stable", "strong"]

class ReviewQuestion(BaseModel):
    id: str
    title: str
    question_text: str = Field(alias="questionText")
    reference_answer: str = Field(alias="referenceAnswer")
    topics: list[str]
    difficulty: Literal["easy", "medium", "hard"]
    key_points: list[str] = Field(alias="keyPoints")
    follow_ups: list[str] = Field(alias="followUps")
    mastery: MasteryState

    model_config = {"populate_by_name": True}

class ReviewRoundSettings(BaseModel):
    selected_topics: list[str] = Field(alias="selectedTopics")
    question_count: int = Field(alias="questionCount", ge=1, le=50)
    mode: ReviewMode

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2：schema 测试**

`backend/tests/test_schema.py`:

```python
from app.schemas.settings import ProviderConfig

def test_provider_schema_accepts_camel_case_json() -> None:
    provider = ProviderConfig.model_validate({
        "id": "p1",
        "name": "OpenAI Compatible",
        "apiFormat": "openai-compatible",
        "baseUrl": "https://api.example.com/v1",
        "modelIds": ["model-a"],
        "activeModelId": "model-a",
        "connectivityStatus": "unknown",
    })
    assert provider.api_format == "openai-compatible"
    assert provider.model_dump(by_alias=True)["activeModelId"] == "model-a"
```

- [ ] **Step 3：前端 API client 和类型**

`frontend/src/shared/api/client.ts`:

```ts
export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(body.code ?? "api_error", body.message ?? "请求失败");
  }
  return body as T;
}

export async function apiPost<TRequest, TResponse>(path: string, payload: TRequest): Promise<TResponse> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new ApiError(body.code ?? "api_error", body.message ?? "请求失败");
  }
  return body as TResponse;
}
```

`frontend/src/features/settings/settingsApi.ts`:

```ts
import { apiGet, apiPost } from "../../shared/api/client";

export type ProviderFormat = "openai-compatible" | "anthropic-compatible";

export interface ProviderConfig {
  id: string;
  name: string;
  apiFormat: ProviderFormat;
  baseUrl: string;
  modelIds: string[];
  activeModelId: string;
  connectivityStatus: "unknown" | "ok" | "failed";
}

export interface WorkspaceConfig {
  workspacePath: string;
  vaultPath: string;
}

export function getWorkspace(): Promise<WorkspaceConfig | null> {
  return apiGet<WorkspaceConfig | null>("/api/settings/workspace");
}

export function initializeWorkspace(workspacePath: string): Promise<WorkspaceConfig> {
  return apiPost<{ workspacePath: string }, WorkspaceConfig>("/api/settings/workspace", { workspacePath });
}
```

`frontend/src/features/knowledge/knowledgeTypes.ts`:

```ts
export type DocumentStatus = "draft" | "review_pending" | "reviewed" | "ingested" | "stale" | "archived";
export type DocumentType = "source" | "question" | "concept" | "session_report" | "mastery_report";

export interface VaultDocument {
  id: string;
  path: string;
  title: string;
  type: DocumentType;
  status: DocumentStatus;
  updatedAt: string;
}
```

`frontend/src/features/review/reviewTypes.ts`:

```ts
export type ReviewMode = "weak-point" | "random-mixed" | "topic-focused" | "recent-mistake";
export type MasteryState = "unknown" | "weak" | "partial" | "stable" | "strong";

export interface ReviewQuestion {
  id: string;
  title: string;
  questionText: string;
  referenceAnswer: string;
  topics: string[];
  difficulty: "easy" | "medium" | "hard";
  keyPoints: string[];
  followUps: string[];
  mastery: MasteryState;
}
```

- [ ] **Step 4：前端 client 测试**

`frontend/src/shared/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiGet", () => {
  it("returns json for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }))));
    await expect(apiGet<{ status: string }>("/api/health")).resolves.toEqual({ status: "ok" });
  });

  it("throws ApiError for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "bad", message: "坏请求" }), { status: 400 })));
    await expect(apiGet("/api/fail")).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 5：验证和提交**

```bash
pnpm --dir frontend test
cd backend && uv run pytest
git add frontend backend
git commit -m "feat: add shared api contracts"
```

---

### Task 2：实现 Workspace 沙箱和 Vault 初始化

**Files:**
- Create: `backend/app/services/workspace.py`
- Create: `backend/app/services/vault.py`
- Create: `backend/app/api/routes_settings.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_workspace.py`
- Test: `backend/tests/test_vault.py`

**Interfaces:**
- Produces: `POST /api/settings/workspace`、`GET /api/settings/workspace`。

- [ ] **Step 1：workspace 沙箱服务**

`backend/app/services/workspace.py`:

```python
from pathlib import Path

class WorkspaceError(ValueError):
    pass

def resolve_workspace(path: str) -> Path:
    workspace = Path(path).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

def ensure_inside_workspace(workspace: Path, target: Path) -> Path:
    workspace = workspace.resolve()
    target = target.expanduser().resolve()
    if target == workspace or workspace in target.parents:
        return target
    raise WorkspaceError("目标路径超出 workspace 沙箱")
```

`backend/tests/test_workspace.py`:

```python
from pathlib import Path

import pytest

from app.services.workspace import WorkspaceError, ensure_inside_workspace

def test_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("x")
    with pytest.raises(WorkspaceError):
        ensure_inside_workspace(workspace, outside)
```

- [ ] **Step 2：Vault 初始化服务**

`backend/app/services/vault.py`:

```python
from pathlib import Path

VAULT_DIRS = [
    "00_inbox",
    "10_question_bank",
    "20_review_sessions",
    "30_mastery",
    "40_concepts",
    "80_manifests",
    "90_exports",
    ".cyber-interview-agent",
]

def initialize_vault(workspace: Path) -> Path:
    vault = workspace / "knowledge-vault"
    for dirname in VAULT_DIRS:
        (vault / dirname).mkdir(parents=True, exist_ok=True)
    return vault
```

`backend/tests/test_vault.py`:

```python
from pathlib import Path

from app.services.vault import VAULT_DIRS, initialize_vault

def test_initialize_vault_creates_required_dirs(tmp_path: Path) -> None:
    vault = initialize_vault(tmp_path)
    for dirname in VAULT_DIRS:
        assert (vault / dirname).is_dir()
```

- [ ] **Step 3：设置 API**

`backend/app/api/routes_settings.py`:

```python
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.settings import WorkspaceConfig
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace

router = APIRouter(prefix="/api/settings", tags=["settings"])

_workspace: WorkspaceConfig | None = None

class WorkspaceRequest(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    model_config = {"populate_by_name": True}

@router.get("/workspace")
def get_workspace() -> WorkspaceConfig | None:
    return _workspace

@router.post("/workspace")
def set_workspace(request: WorkspaceRequest) -> WorkspaceConfig:
    global _workspace
    workspace = resolve_workspace(request.workspace_path)
    vault = initialize_vault(workspace)
    _workspace = WorkspaceConfig(workspacePath=str(workspace), vaultPath=str(vault))
    return _workspace
```

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.api.routes_settings import router as settings_router

app = FastAPI(title="Cyber Interview Agent API")
app.include_router(settings_router)

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4：验证和提交**

```bash
cd backend && uv run pytest
git add backend
git commit -m "feat: initialize workspace vault"
```

---

### Task 3：实现 Markdown 模板、Manifest 和 SQLite FTS 索引

**Files:**
- Create: `backend/app/services/markdown.py`
- Create: `backend/app/db/schema.sql`
- Create: `backend/app/db/connection.py`
- Create: `backend/app/services/search_index.py`
- Test: `backend/tests/test_search_index.py`

**Interfaces:**
- Produces: `render_question_markdown()`、`upsert_document()`、`search_documents()`。

- [ ] **Step 1：Markdown 渲染**

`backend/app/services/markdown.py`:

```python
import frontmatter

from app.schemas.review import ReviewQuestion

def render_question_markdown(question: ReviewQuestion, status: str = "review_pending") -> str:
    post = frontmatter.Post(
        content=(
            f"# {question.title}\n\n"
            f"## 问题\n\n{question.question_text}\n\n"
            f"## 参考答案\n\n{question.reference_answer}\n\n"
            "## 关键得分点\n\n"
            + "\n".join(f"- {point}" for point in question.key_points)
        ),
        type="question",
        id=question.id,
        status=status,
        topics=question.topics,
        difficulty=question.difficulty,
        mastery=question.mastery,
    )
    return frontmatter.dumps(post)
```

- [ ] **Step 2：DB schema 和连接**

`backend/app/db/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS manifest_documents (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  title TEXT NOT NULL,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  checksum TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_fts
USING fts5(id UNINDEXED, title, body);
```

`backend/app/db/connection.py`:

```python
import sqlite3
from pathlib import Path

def connect_index(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn
```

- [ ] **Step 3：索引服务**

`backend/app/services/search_index.py`:

```python
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class IndexedDocument:
    id: str
    path: str
    title: str
    type: str
    status: str
    body: str

def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def upsert_document(conn: sqlite3.Connection, document: IndexedDocument) -> None:
    now = datetime.now(timezone.utc).isoformat()
    digest = checksum(document.body)
    conn.execute(
        """
        INSERT INTO manifest_documents (id, path, title, type, status, checksum, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          path=excluded.path,
          title=excluded.title,
          type=excluded.type,
          status=excluded.status,
          checksum=excluded.checksum,
          updated_at=excluded.updated_at
        """,
        (document.id, document.path, document.title, document.type, document.status, digest, now),
    )
    conn.execute("DELETE FROM document_fts WHERE id = ?", (document.id,))
    conn.execute(
        "INSERT INTO document_fts (id, title, body) VALUES (?, ?, ?)",
        (document.id, document.title, document.body),
    )
    conn.commit()

def search_documents(conn: sqlite3.Connection, query: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM document_fts WHERE document_fts MATCH ? ORDER BY rank LIMIT 20",
        (query,),
    ).fetchall()
    return [row[0] for row in rows]
```

`backend/tests/test_search_index.py`:

```python
from app.db.connection import connect_index
from app.services.search_index import IndexedDocument, search_documents, upsert_document

def test_search_documents(tmp_path):
    conn = connect_index(tmp_path / "index.sqlite")
    upsert_document(conn, IndexedDocument(
        id="q1",
        path="10_question_bank/q1.md",
        title="缓存穿透",
        type="question",
        status="ingested",
        body="缓存穿透 布隆过滤器",
    ))
    assert search_documents(conn, "缓存") == ["q1"]
```

- [ ] **Step 4：验证和提交**

```bash
cd backend && uv run pytest
git add backend
git commit -m "feat: add vault manifest search index"
```

---

### Task 4：实现 Provider 配置和连通性测试

**Files:**
- Create: `backend/app/services/provider_registry.py`
- Modify: `backend/app/api/routes_settings.py`
- Create: `frontend/src/features/settings/SettingsPage.tsx`
- Create: `frontend/src/shared/ui/Button.tsx`
- Create: `frontend/src/shared/ui/Field.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Test: `backend/tests/test_provider_registry.py`
- Test: `frontend/src/features/settings/SettingsPage.test.tsx`

**Interfaces:**
- Produces: `POST /api/settings/providers/test` 和设置页 UI。

- [ ] **Step 1：Provider registry**

`backend/app/services/provider_registry.py`:

```python
from app.schemas.settings import ProviderConfig

def test_provider_connection(provider: ProviderConfig) -> ProviderConfig:
    status = "ok" if provider.base_url.startswith("http") and provider.active_model_id else "failed"
    return provider.model_copy(update={"connectivity_status": status})
```

`backend/tests/test_provider_registry.py`:

```python
from app.schemas.settings import ProviderConfig
from app.services.provider_registry import test_provider_connection

def test_provider_connection_marks_http_provider_ok() -> None:
    provider = ProviderConfig(
        id="p1",
        name="OpenAI Compatible",
        apiFormat="openai-compatible",
        baseUrl="https://api.example.com/v1",
        modelIds=["model-a"],
        activeModelId="model-a",
    )
    checked = test_provider_connection(provider)
    assert checked.connectivity_status == "ok"
```

- [ ] **Step 2：Provider API**

Append to `backend/app/api/routes_settings.py`:

```python
from app.schemas.settings import ProviderConfig
from app.services.provider_registry import test_provider_connection

@router.post("/providers/test")
def test_provider(provider: ProviderConfig) -> ProviderConfig:
    return test_provider_connection(provider)
```

- [ ] **Step 3：设置页 UI**

`frontend/src/shared/ui/Button.tsx`:

```tsx
import type { ButtonHTMLAttributes, ReactNode } from "react";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
}

export function Button({ children, type = "button", ...props }: ButtonProps) {
  return <button type={type} {...props}>{children}</button>;
}
```

`frontend/src/shared/ui/Field.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
}

export function Field({ label, id, ...props }: FieldProps) {
  const inputId = id ?? props.name ?? label;
  return (
    <label htmlFor={inputId}>
      <span>{label}</span>
      <input id={inputId} {...props} />
    </label>
  );
}
```

`frontend/src/features/settings/SettingsPage.tsx`:

```tsx
import { Button } from "../../shared/ui/Button";
import { Field } from "../../shared/ui/Field";

export function SettingsPage() {
  return (
    <section aria-labelledby="settings-title">
      <h2 id="settings-title">设置</h2>
      <form>
        <Field label="Provider 名称" name="providerName" />
        <Field label="Base URL" name="baseUrl" />
        <Field label="Model ID" name="modelId" />
        <Field label="Workspace Path" name="workspacePath" />
        <Button>测试连接</Button>
        <Button>初始化工作区</Button>
      </form>
    </section>
  );
}
```

Modify `frontend/src/app/layout/AppShell.tsx`:

```tsx
import { SettingsPage } from "../../features/settings/SettingsPage";

export function AppShell() {
  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <SettingsPage />
    </main>
  );
}
```

- [ ] **Step 4：设置页测试**

`frontend/src/features/settings/SettingsPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  it("renders provider and workspace fields", () => {
    render(<SettingsPage />);
    expect(screen.getByLabelText("Provider 名称")).toBeInTheDocument();
    expect(screen.getByLabelText("Base URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Workspace Path")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5：验证和提交**

```bash
pnpm --dir frontend test
cd backend && uv run pytest
git add frontend backend
git commit -m "feat: add settings provider workflow"
```

---

### Task 5：实现资料上传、解析和题库草稿生成

**Files:**
- Create: `backend/app/services/document_ingestion.py`
- Create: `backend/app/api/routes_knowledge.py`
- Modify: `backend/app/main.py`
- Create: `frontend/src/features/knowledge/knowledgeApi.ts`
- Create: `frontend/src/features/knowledge/KnowledgePage.tsx`
- Test: `backend/tests/test_document_ingestion.py`
- Test: `frontend/src/features/knowledge/KnowledgePage.test.tsx`

**Interfaces:**
- Produces: `POST /api/knowledge/sources`，写入 `00_inbox/`，返回 draft question。

- [ ] **Step 1：文档摄取服务**

`backend/app/services/document_ingestion.py`:

```python
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from app.schemas.review import ReviewQuestion

def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")

def create_question_draft(text: str) -> ReviewQuestion:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "未命名问题")
    return ReviewQuestion(
        id=f"q_{uuid4().hex[:12]}",
        title=first_line[:60],
        questionText=first_line,
        referenceAnswer=text[:1200],
        topics=["uncategorized"],
        difficulty="medium",
        keyPoints=[first_line[:80]],
        followUps=[],
        mastery="unknown",
    )
```

`backend/tests/test_document_ingestion.py`:

```python
from app.services.document_ingestion import create_question_draft

def test_create_question_draft_from_text() -> None:
    draft = create_question_draft("缓存穿透是什么？\n参考答案")
    assert draft.title == "缓存穿透是什么？"
    assert draft.topics == ["uncategorized"]
```

- [ ] **Step 2：知识库 API**

`backend/app/api/routes_knowledge.py`:

```python
from pathlib import Path
from shutil import copyfileobj

from fastapi import APIRouter, File, Form, UploadFile

from app.schemas.review import ReviewQuestion
from app.services.document_ingestion import create_question_draft, extract_text
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

@router.post("/sources")
async def upload_source(workspace_path: str = Form(..., alias="workspacePath"), file: UploadFile = File(...)) -> ReviewQuestion:
    workspace = resolve_workspace(workspace_path)
    vault = initialize_vault(workspace)
    inbox = vault / "00_inbox"
    destination = inbox / file.filename
    with destination.open("wb") as target:
        copyfileobj(file.file, target)
    text = extract_text(Path(destination))
    return create_question_draft(text)
```

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_settings import router as settings_router

app = FastAPI(title="Cyber Interview Agent API")
app.include_router(settings_router)
app.include_router(knowledge_router)

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 3：知识文档页**

`frontend/src/features/knowledge/knowledgeApi.ts`:

```ts
import type { ReviewQuestion } from "../review/reviewTypes";

export async function uploadSource(workspacePath: string, file: File): Promise<ReviewQuestion> {
  const form = new FormData();
  form.set("workspacePath", workspacePath);
  form.set("file", file);
  const response = await fetch("/api/knowledge/sources", { method: "POST", body: form });
  if (!response.ok) throw new Error("上传失败");
  return response.json();
}
```

`frontend/src/features/knowledge/KnowledgePage.tsx`:

```tsx
export function KnowledgePage() {
  return (
    <section aria-labelledby="knowledge-title">
      <h2 id="knowledge-title">知识文档</h2>
      <button type="button">上传资料</button>
      <button type="button">重新扫描 Vault</button>
      <p>暂无文档</p>
    </section>
  );
}
```

Modify `frontend/src/app/layout/AppShell.tsx`:

```tsx
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { SettingsPage } from "../../features/settings/SettingsPage";

export function AppShell() {
  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <SettingsPage />
      <KnowledgePage />
    </main>
  );
}
```

- [ ] **Step 4：知识页测试**

`frontend/src/features/knowledge/KnowledgePage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KnowledgePage } from "./KnowledgePage";

describe("KnowledgePage", () => {
  it("renders upload and rescan actions", () => {
    render(<KnowledgePage />);
    expect(screen.getByRole("heading", { name: "知识文档" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传资料" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新扫描 Vault" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 5：验证和提交**

```bash
pnpm --dir frontend test
cd backend && uv run pytest
git add frontend backend
git commit -m "feat: ingest sources into question drafts"
```

---

### Task 6：实现 LangGraph 复习 Agent

**Files:**
- Create: `backend/app/agents/review_state.py`
- Create: `backend/app/agents/tools.py`
- Create: `backend/app/agents/review_graph.py`
- Test: `backend/tests/test_review_graph.py`

**Interfaces:**
- Produces: `build_review_graph()`，支持选题、评估、报告建议。

- [ ] **Step 1：定义 agent state**

`backend/app/agents/review_state.py`:

```python
from typing import Literal, TypedDict

from app.schemas.review import ReviewQuestion, ReviewRoundSettings

class AnswerEvaluation(TypedDict):
    question_id: str
    score: Literal["poor", "partial", "good"]
    missing_key_points: list[str]
    evidence: str

class ReviewState(TypedDict, total=False):
    settings: ReviewRoundSettings
    questions: list[ReviewQuestion]
    current_question: ReviewQuestion
    user_answer: str
    evaluation: AnswerEvaluation
    report_markdown: str
```

- [ ] **Step 2：实现工具函数**

`backend/app/agents/tools.py`:

```python
from app.agents.review_state import AnswerEvaluation
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

MASTERY_RANK = {"weak": 0, "partial": 1, "unknown": 2, "stable": 3, "strong": 4}

def select_next_question(questions: list[ReviewQuestion], settings: ReviewRoundSettings) -> ReviewQuestion:
    scoped = [
        question for question in questions
        if not settings.selected_topics or any(topic in settings.selected_topics for topic in question.topics)
    ]
    if not scoped:
        raise ValueError("没有可用题目")
    return sorted(scoped, key=lambda question: MASTERY_RANK[question.mastery])[0]

def evaluate_answer(question: ReviewQuestion, answer: str) -> AnswerEvaluation:
    missing = [point for point in question.key_points if point.lower() not in answer.lower()]
    if not missing:
        score = "good"
    elif len(missing) < len(question.key_points):
        score = "partial"
    else:
        score = "poor"
    return {
        "question_id": question.id,
        "score": score,
        "missing_key_points": missing,
        "evidence": answer,
    }
```

- [ ] **Step 3：实现 LangGraph**

`backend/app/agents/review_graph.py`:

```python
from langgraph.graph import END, START, StateGraph

from app.agents.review_state import ReviewState
from app.agents.tools import evaluate_answer, select_next_question

def choose_question(state: ReviewState) -> ReviewState:
    return {"current_question": select_next_question(state["questions"], state["settings"])}

def evaluate_current_answer(state: ReviewState) -> ReviewState:
    return {"evaluation": evaluate_answer(state["current_question"], state.get("user_answer", ""))}

def generate_report(state: ReviewState) -> ReviewState:
    evaluation = state["evaluation"]
    markdown = (
        "---\n"
        "type: session_report\n"
        "status: review_pending\n"
        "---\n\n"
        "# 单轮复习报告\n\n"
        f"- question: {evaluation['question_id']}\n"
        f"- score: {evaluation['score']}\n"
        f"- missing: {', '.join(evaluation['missing_key_points']) or '无'}\n"
    )
    return {"report_markdown": markdown}

def build_review_graph():
    graph = StateGraph(ReviewState)
    graph.add_node("choose_question", choose_question)
    graph.add_node("evaluate_answer", evaluate_current_answer)
    graph.add_node("generate_report", generate_report)
    graph.add_edge(START, "choose_question")
    graph.add_edge("choose_question", "evaluate_answer")
    graph.add_edge("evaluate_answer", "generate_report")
    graph.add_edge("generate_report", END)
    return graph.compile()
```

- [ ] **Step 4：Agent 测试**

`backend/tests/test_review_graph.py`:

```python
from app.agents.review_graph import build_review_graph
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

def test_review_graph_generates_report() -> None:
    graph = build_review_graph()
    question = ReviewQuestion(
        id="q1",
        title="缓存穿透",
        questionText="缓存穿透是什么？",
        referenceAnswer="缓存空值或布隆过滤器可以减少不存在数据请求打到数据库。",
        topics=["backend"],
        difficulty="medium",
        keyPoints=["缓存空值", "布隆过滤器"],
        followUps=[],
        mastery="weak",
    )
    settings = ReviewRoundSettings(selectedTopics=[], questionCount=1, mode="weak-point")
    result = graph.invoke({"questions": [question], "settings": settings, "user_answer": "缓存空值"})
    assert result["evaluation"]["score"] == "partial"
    assert "status: review_pending" in result["report_markdown"]
```

- [ ] **Step 5：验证和提交**

```bash
cd backend && uv run pytest
git add backend
git commit -m "feat: add langgraph review agent"
```

---

### Task 7：实现复习 API 和复习页 UI

**Files:**
- Create: `backend/app/api/routes_review.py`
- Modify: `backend/app/main.py`
- Create: `frontend/src/features/review/reviewApi.ts`
- Create: `frontend/src/features/review/ReviewPage.tsx`
- Create: `frontend/src/features/review/ReviewSessionList.tsx`
- Create: `frontend/src/features/review/ReviewChat.tsx`
- Create: `frontend/src/features/review/ReviewSetupPanel.tsx`
- Modify: `frontend/src/app/layout/AppShell.tsx`
- Test: `frontend/src/features/review/ReviewPage.test.tsx`

**Interfaces:**
- Produces: `POST /api/review/run`，UI 三栏结构。

- [ ] **Step 1：复习 API**

`backend/app/api/routes_review.py`:

```python
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agents.review_graph import build_review_graph
from app.schemas.review import ReviewQuestion, ReviewRoundSettings

router = APIRouter(prefix="/api/review", tags=["review"])

class ReviewRunRequest(BaseModel):
    questions: list[ReviewQuestion]
    settings: ReviewRoundSettings
    user_answer: str = Field(alias="userAnswer")
    model_config = {"populate_by_name": True}

@router.post("/run")
def run_review(request: ReviewRunRequest) -> dict:
    graph = build_review_graph()
    return graph.invoke({
        "questions": request.questions,
        "settings": request.settings,
        "user_answer": request.user_answer,
    })
```

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI

from app.api.routes_knowledge import router as knowledge_router
from app.api.routes_review import router as review_router
from app.api.routes_settings import router as settings_router

app = FastAPI(title="Cyber Interview Agent API")
app.include_router(settings_router)
app.include_router(knowledge_router)
app.include_router(review_router)

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 2：前端复习 API**

`frontend/src/features/review/reviewApi.ts`:

```ts
import { apiPost } from "../../shared/api/client";
import type { ReviewQuestion } from "./reviewTypes";

export interface ReviewRunRequest {
  questions: ReviewQuestion[];
  settings: {
    selectedTopics: string[];
    questionCount: number;
    mode: "weak-point" | "random-mixed" | "topic-focused" | "recent-mistake";
  };
  userAnswer: string;
}

export function runReview(payload: ReviewRunRequest): Promise<Record<string, unknown>> {
  return apiPost<ReviewRunRequest, Record<string, unknown>>("/api/review/run", payload);
}
```

- [ ] **Step 3：复习 UI**

`frontend/src/features/review/ReviewSessionList.tsx`:

```tsx
export function ReviewSessionList() {
  return (
    <aside aria-label="复习会话">
      <h2>会话</h2>
      <p>暂无会话</p>
    </aside>
  );
}
```

`frontend/src/features/review/ReviewSetupPanel.tsx`:

```tsx
export function ReviewSetupPanel() {
  return (
    <section aria-label="复习设置">
      <h2>复习设置</h2>
      <label>
        题量
        <input defaultValue="10" inputMode="numeric" />
      </label>
      <label>
        模式
        <select defaultValue="weak-point">
          <option value="weak-point">薄弱点优先</option>
          <option value="random-mixed">随机混合</option>
          <option value="topic-focused">单主题巩固</option>
          <option value="recent-mistake">最近错误复现</option>
        </select>
      </label>
    </section>
  );
}
```

`frontend/src/features/review/ReviewChat.tsx`:

```tsx
export function ReviewChat() {
  return (
    <section aria-label="复习对话">
      <h2>复习对话</h2>
      <div role="log" aria-label="对话记录">准备开始一轮复习</div>
      <textarea aria-label="回答输入" />
      <button type="button">发送回答</button>
    </section>
  );
}
```

`frontend/src/features/review/ReviewPage.tsx`:

```tsx
import { ReviewChat } from "./ReviewChat";
import { ReviewSessionList } from "./ReviewSessionList";
import { ReviewSetupPanel } from "./ReviewSetupPanel";

export function ReviewPage() {
  return (
    <section aria-labelledby="review-title">
      <h2 id="review-title">复习</h2>
      <ReviewSessionList />
      <ReviewChat />
      <ReviewSetupPanel />
    </section>
  );
}
```

Modify `frontend/src/app/layout/AppShell.tsx`:

```tsx
import { KnowledgePage } from "../../features/knowledge/KnowledgePage";
import { ReviewPage } from "../../features/review/ReviewPage";
import { SettingsPage } from "../../features/settings/SettingsPage";

export function AppShell() {
  return (
    <main>
      <h1>Cyber Interview Agent</h1>
      <SettingsPage />
      <ReviewPage />
      <KnowledgePage />
    </main>
  );
}
```

- [ ] **Step 4：UI 测试**

`frontend/src/features/review/ReviewPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReviewPage } from "./ReviewPage";

describe("ReviewPage", () => {
  it("renders session list chat and setup panel", () => {
    render(<ReviewPage />);
    expect(screen.getByLabelText("复习会话")).toBeInTheDocument();
    expect(screen.getByLabelText("复习对话")).toBeInTheDocument();
    expect(screen.getByLabelText("复习设置")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5：验证和提交**

```bash
pnpm --dir frontend test
cd backend && uv run pytest
git add frontend backend
git commit -m "feat: add review api and workspace ui"
```

---

### Task 8：实现报告保存、掌握度更新建议和人工确认点

**Files:**
- Create: `backend/app/services/mastery.py`
- Modify: `backend/app/api/routes_review.py`
- Test: `backend/tests/test_mastery.py`

**Interfaces:**
- Produces: `POST /api/review/reports/confirm`，写入 `20_review_sessions/` 和 `30_mastery/`。

- [ ] **Step 1：mastery 服务**

`backend/app/services/mastery.py`:

```python
from pathlib import Path
from time import time

def save_session_report(vault: Path, markdown: str) -> Path:
    report_dir = vault / "20_review_sessions"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"session_report_{int(time())}.md"
    path.write_text(markdown, encoding="utf-8")
    return path

def build_global_mastery_update(report_markdown: str) -> str:
    return (
        "---\n"
        "type: mastery_report\n"
        "status: review_pending\n"
        "---\n\n"
        "# 全局掌握度更新建议\n\n"
        "## 本轮证据\n\n"
        f"{report_markdown[:1200]}\n"
    )
```

`backend/tests/test_mastery.py`:

```python
from app.services.mastery import build_global_mastery_update, save_session_report

def test_save_session_report(tmp_path):
    path = save_session_report(tmp_path, "# report")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# report"

def test_build_global_mastery_update():
    markdown = build_global_mastery_update("# 单轮报告")
    assert "type: mastery_report" in markdown
    assert "全局掌握度更新建议" in markdown
```

- [ ] **Step 2：确认 API**

Append to `backend/app/api/routes_review.py`:

```python
from pydantic import BaseModel, Field

from app.services.mastery import build_global_mastery_update, save_session_report
from app.services.vault import initialize_vault
from app.services.workspace import resolve_workspace

class ConfirmReportRequest(BaseModel):
    workspace_path: str = Field(alias="workspacePath")
    report_markdown: str = Field(alias="reportMarkdown")
    model_config = {"populate_by_name": True}

@router.post("/reports/confirm")
def confirm_report(request: ConfirmReportRequest) -> dict[str, str]:
    workspace = resolve_workspace(request.workspace_path)
    vault = initialize_vault(workspace)
    report_path = save_session_report(vault, request.report_markdown)
    mastery_markdown = build_global_mastery_update(request.report_markdown)
    mastery_path = vault / "30_mastery" / "global_mastery_review_pending.md"
    mastery_path.write_text(mastery_markdown, encoding="utf-8")
    return {"reportPath": str(report_path), "masteryPath": str(mastery_path)}
```

- [ ] **Step 3：验证和提交**

```bash
cd backend && uv run pytest
git add backend
git commit -m "feat: add mastery confirmation flow"
```

---

### Task 9：实现恢复、重新扫描和端到端冒烟测试

**Files:**
- Create: `tests/e2e/mvp-smoke.spec.ts`
- Create: `playwright.config.ts`
- Modify: `frontend/package.json`
- Modify: `backend/app/api/routes_knowledge.py`
- Test: `tests/e2e/mvp-smoke.spec.ts`

**Interfaces:**
- Produces: `POST /api/knowledge/rescan` 和 E2E smoke。

- [ ] **Step 1：知识库 rescan API**

Append to `backend/app/api/routes_knowledge.py`:

```python
from app.db.connection import connect_index
from app.services.search_index import IndexedDocument, upsert_document

@router.post("/rescan")
def rescan_vault(workspace_path: str = Form(..., alias="workspacePath")) -> dict[str, int]:
    workspace = resolve_workspace(workspace_path)
    vault = initialize_vault(workspace)
    db_path = vault / ".cyber-interview-agent" / "index.sqlite"
    conn = connect_index(db_path)
    count = 0
    for path in vault.rglob("*.md"):
        body = path.read_text(encoding="utf-8")
        upsert_document(conn, IndexedDocument(
            id=path.stem,
            path=str(path.relative_to(vault)),
            title=path.stem,
            type="source",
            status="reviewed",
            body=body,
        ))
        count += 1
    return {"indexed": count}
```

- [ ] **Step 2：Playwright 配置**

Add script to `frontend/package.json`:

```json
"e2e": "playwright test --config ../playwright.config.ts"
```

`playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  webServer: {
    command: "pnpm --dir frontend dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
  use: {
    baseURL: "http://127.0.0.1:5173",
  },
});
```

`tests/e2e/mvp-smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("mvp shell exposes settings review and knowledge sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Cyber Interview Agent" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "复习" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "知识文档" })).toBeVisible();
});
```

- [ ] **Step 3：最终验证**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend && uv run pytest
pnpm --dir frontend e2e
```

Expected:

- 前端单元测试通过。
- 前端 build 成功。
- 后端 pytest 通过。
- E2E 能看到设置、复习、知识文档三个入口。

- [ ] **Step 4：提交**

```bash
git add frontend backend tests playwright.config.ts
git commit -m "feat: add vault rescan and mvp smoke test"
```

---

## 自查

规格覆盖：

- Provider 和 workspace：Task 2、Task 4。
- Obsidian-compatible Vault：Task 2、Task 3。
- 资料上传与题库草稿：Task 5。
- LangGraph 复习 agent：Task 6。
- 复习 UI 和 API：Task 7。
- 报告、掌握度和人工确认点：Task 8。
- 恢复、rescan、冒烟测试：Task 9。

技术一致性：

- 不再使用 Tauri、Rust command 或桌面端假设。
- 所有本地文件读写都在 Python 后端。
- 前端只通过 `/api/*` 访问数据。
- LangGraph 位于后端 agent 层，后续可以加 checkpoint、streaming、HITL interrupt。

已知后续增强，不阻塞 MVP：

- Provider 连通性测试第一步只做配置形态校验；真实模型调用在 agent 接入具体 provider 时增强。
- PDF 第一版只要求能提取文本；扫描件 OCR 不进入 MVP。
- embedding/vector search 不进入 MVP，接口保留到检索质量需要提升时再引入。

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-07-09-cyber-interview-agent-mvp.md`. Two execution options:

1. **Subagent-Driven（推荐）**：每个任务派一个新 subagent，任务间 review，适合这个多模块项目。
2. **Inline Execution**：我在当前会话中按任务顺序执行，分批 checkpoint。

请选择执行方式。
