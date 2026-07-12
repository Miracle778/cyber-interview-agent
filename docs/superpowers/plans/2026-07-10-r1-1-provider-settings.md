# R1.1 Provider 与设置实施计划


**目标：** 持久化全局 Provider 和 Workspace，使用 SecretStore 保护 API Key，通过真实协议 adapter 逐模型测试连接，并为每个 Workspace 绑定模型用途。

**架构：** 新增应用级 SQLite 和 Repository 驱动的服务。Provider secret 只能通过 `SecretStore` 协议访问，REST 资源始终脱敏；现有设置页渐进扩展为 Provider/模型与 Workspace 绑定管理。

**技术栈：** FastAPI、Pydantic 2、sqlite3、platformdirs、keyring、LangChain OpenAI/Anthropic 集成、React、TypeScript、Vitest、pytest。

## 全局约束

- Provider 元数据全局保存，模型用途绑定按 Workspace 保存。
- Provider 连接状态记录到具体模型。
- API Key 只写不读，任何接口都不能返回其值。
- 连接测试失败不删除 Provider，也不阻止保存。
- 删除仍被绑定的 Provider/模型返回 `409 resource_in_use`。
- 自动测试使用 fake adapter 和 Fake SecretStore。
- 替换进程全局 `_workspace` 时保留现有 Workspace/Vault 初始化行为。

---

## 文件结构

新建：

- `backend/app/core/app_paths.py` — 解析各平台应用数据目录，支持测试覆盖。
- `backend/app/db/app_database.py` — 应用数据库连接和顺序迁移。
- `backend/app/db/migrations/app/001_initial.sql` — Provider, model, Workspace, binding, and test-run tables.
- `backend/app/repositories/provider_repository.py` — Provider/model persistence.
- `backend/app/repositories/workspace_repository.py` — Workspace registry and role bindings.
- `backend/app/services/secrets.py` — SecretStore protocol, keyring implementation, environment fallback, fake.
- `backend/app/providers/base.py` — adapter 协议和统一结果/错误类型。
- `backend/app/providers/openai_compatible.py` — OpenAI-compatible adapter.
- `backend/app/providers/anthropic_compatible.py` — Anthropic-compatible adapter.
- `backend/app/services/provider_service.py` — Provider CRUD, secret lifecycle, connection testing.
- `backend/app/services/workspace_service.py` — 注册、重新关联、可用性和模型用途绑定。
- `backend/app/api/dependencies.py` — 用依赖提供器替换硬编码全局对象。
- `backend/tests/test_app_database.py`
- `backend/tests/test_secret_store.py`
- `backend/tests/test_provider_service.py`
- `backend/tests/test_provider_routes.py`
- `backend/tests/test_workspace_registry.py`
- `frontend/src/features/settings/providerTypes.ts`
- `frontend/src/features/settings/ProviderManager.tsx`
- `frontend/src/features/settings/ProviderManager.test.tsx`
- `frontend/src/features/settings/ModelBindings.tsx`
- `frontend/src/features/settings/ModelBindings.test.tsx`

修改：

- `backend/pyproject.toml` — 添加 `platformdirs` 和 `keyring`。
- `backend/uv.lock` — 使用 `uv lock` 锁定依赖。
- `backend/app/schemas/settings.py` — 资源/请求 schema 和详细状态。
- `backend/app/api/routes_settings.py` — 面向资源的 endpoint。
- `backend/app/main.py` — CORS and router behavior if required by Settings API tests.
- `backend/tests/test_provider_registry.py` — 删除字符串前缀式假连接预期。
- `backend/tests/test_workspace.py` — 保留路径初始化覆盖。
- `frontend/src/shared/api/client.ts` — PATCH, PUT, DELETE helpers and empty-body handling.
- `frontend/src/shared/api/client.test.ts`
- `frontend/src/features/settings/settingsApi.ts` — 新 Provider/Workspace API。
- `frontend/src/features/settings/SettingsPage.tsx` — 组合 ProviderManager 与 ModelBindings。
- `frontend/src/features/settings/SettingsPage.test.tsx` — 用资源工作流替换单一假测试。

### 任务 1：应用数据目录与迁移

**接口：**
- 产出 `resolve_app_data_dir() -> Path` and `connect_app_database(data_dir: Path | None = None) -> sqlite3.Connection`.
- 后续任务依赖表 `providers`、`provider_models`、`workspaces`、`workspace_model_bindings` 和 `provider_test_runs`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_app_database.py`：

```python
from app.db.app_database import connect_app_database


def test_app_database_applies_initial_schema(tmp_path):
    connection = connect_app_database(tmp_path)
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"providers", "provider_models", "workspaces", "workspace_model_bindings", "provider_test_runs"} <= tables


def test_app_database_reopens_without_reapplying_migration(tmp_path):
    connect_app_database(tmp_path).close()
    connection = connect_app_database(tmp_path)
    assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_app_database.py -v`

预期：失败，因为 `app.db.app_database` 尚不存在。

- [ ] **步骤 3：实现最小功能**

新增 `backend/app/core/app_paths.py`：

```python
import os
from pathlib import Path
from platformdirs import user_data_path


def resolve_app_data_dir() -> Path:
    override = os.getenv("CYBER_INTERVIEW_AGENT_DATA_DIR")
    path = Path(override).expanduser() if override else user_data_path("cyber-interview-agent", appauthor=False)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
```

新增 `connect_app_database()`：打开 `<data_dir>/app.sqlite`、启用外键、在事务中按顺序执行一次迁移，并返回 `sqlite3.Row`。初始 SQL 必须定义五张契约表和 `schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)`；被绑定模型的外键使用 `ON DELETE RESTRICT`。

- [ ] **步骤 4：运行测试确认通过并锁定依赖**

运行：

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv lock
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_app_database.py -v
```

预期：2 个测试通过。

- [ ] **步骤 5：提交**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/app_paths.py backend/app/db/app_database.py backend/app/db/migrations/app/001_initial.sql backend/tests/test_app_database.py
git commit -m "feat(settings): add application database migrations"
```

### 任务 2：SecretStore

**接口：**
- 产出 `SecretStore.get(ref)`、`SecretStore.set(ref, value)` 和 `SecretStore.delete(ref)`。
- 产出 `KeyringSecretStore`、`EnvironmentSecretStore` 和 `FakeSecretStore`。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_secret_store.py`：

```python
import pytest
from app.services.secrets import EnvironmentSecretStore, FakeSecretStore, SecretNotFoundError


def test_fake_secret_store_never_exposes_values_in_repr():
    store = FakeSecretStore()
    store.set("provider:p1", "sk-secret")
    assert store.get("provider:p1") == "sk-secret"
    assert "sk-secret" not in repr(store)


def test_environment_store_reads_named_variable(monkeypatch):
    monkeypatch.setenv("CYBER_PROVIDER_TEST_KEY", "env-secret")
    assert EnvironmentSecretStore().get("CYBER_PROVIDER_TEST_KEY") == "env-secret"


def test_missing_environment_secret_is_typed(monkeypatch):
    monkeypatch.delenv("CYBER_PROVIDER_MISSING", raising=False)
    with pytest.raises(SecretNotFoundError):
        EnvironmentSecretStore().get("CYBER_PROVIDER_MISSING")
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_secret_store.py -v`

预期：失败，因为 `app.services.secrets` 尚不存在。

- [ ] **步骤 3：实现最小功能**

使用以下公共契约：

```python
from typing import Protocol


class SecretStore(Protocol):
    def get(self, ref: str) -> str: ...
    def set(self, ref: str, value: str) -> None: ...
    def delete(self, ref: str) -> None: ...


class SecretNotFoundError(LookupError):
    pass
```

`KeyringSecretStore` 使用 service name `cyber-interview-agent`，并把 keyring backend 错误转换为 `SecretStoreUnavailableError`。`EnvironmentSecretStore` 只读，调用 `set`/`delete` 时抛错。`FakeSecretStore.__repr__` 只返回已存 ref。

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_secret_store.py -v`

预期：3 个测试通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/services/secrets.py backend/tests/test_secret_store.py
git commit -m "feat(settings): add protected provider secret stores"
```

### 任务 3：Provider 与 Workspace Repository

**接口：**
- 产出 repository methods consumed only by services.
- Provider、模型和 Workspace ID 使用 UUID 字符串。
- 强制每个 `(workspace_id, role)` 只有一条绑定。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_workspace_registry.py`，覆盖注册 Workspace、重启数据库、保持 ID 重新关联路径、把 `answer_evaluation` 绑定到模型，以及直接删除被绑定模型时得到 `sqlite3.IntegrityError`。

创建 `backend/tests/test_provider_service.py`，先加入以下 Repository 断言：

```python
def test_provider_repository_round_trips_multiple_models(app_connection):
    repository = ProviderRepository(app_connection)
    provider = repository.create_provider(name="Local", api_format="openai-compatible", base_url="http://127.0.0.1:11434/v1", secret_source="environment", secret_ref="OLLAMA_KEY")
    first = repository.create_model(provider.id, "model-a", "Model A")
    second = repository.create_model(provider.id, "model-b", "Model B")
    loaded = repository.get_provider(provider.id)
    assert [model.model_id for model in loaded.models] == [first.model_id, second.model_id]
```

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_service.py tests/test_workspace_registry.py -v`

预期：失败，因为 Repository 和 fixture 尚不存在。

- [ ] **步骤 3：实现最小功能**

使用不可变 dataclass：`ProviderRecord`、`ProviderModelRecord`、`WorkspaceRecord` 和 `WorkspaceModelBindingRecord`。Repository 接收领域值、执行参数化 SQL，只在 service 事务边界提交，且永不读取 SecretStore。

每个测试模块使用调用 `connect_app_database(tmp_path)` 的本地 fixture，不创建全局测试数据库。

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_service.py tests/test_workspace_registry.py -v`

预期：Repository 测试通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/repositories/provider_repository.py backend/app/repositories/workspace_repository.py backend/tests/test_provider_service.py backend/tests/test_workspace_registry.py
git commit -m "feat(settings): persist providers models and workspaces"
```

### 任务 4：协议 Adapter 与 ProviderService

**接口：**
- 产出 `ProviderAdapter.test_connection(config, api_key) -> ProviderTestResult`。
- 产出 spec 中定义的统一 `ProviderErrorCode`。
- 产出 `ProviderService` CRUD 和 `test_model(model_id)`。

- [ ] **步骤 1：编写失败测试**

扩展 `backend/tests/test_provider_service.py`：

```python
@pytest.mark.asyncio
async def test_model_test_records_auth_failure(provider_service, fake_adapter):
    fake_adapter.next_result = ProviderTestResult(status="auth_failed", latency_ms=12, message="认证失败")
    result = await provider_service.test_model("model-1")
    assert result.connectivity_status == "auth_failed"
    assert result.last_latency_ms == 12


def test_provider_response_is_redacted(provider_service):
    created = provider_service.create_provider(CreateProviderCommand(name="P", api_format="openai-compatible", base_url="https://example.test/v1", api_key="sk-secret"))
    assert created.has_secret is True
    assert not hasattr(created, "api_key")
    assert "sk-secret" not in created.model_dump_json()
```

增加 adapter 契约测试：monkeypatch `ChatOpenAI.ainvoke` 和 `ChatAnthropic.ainvoke`，断言 adapter 使用配置的 Base URL/模型，并把 401、404、429、超时和错误响应转换为统一错误码。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_service.py -v`

预期：失败，因为 adapter 和 service 契约尚不存在。

- [ ] **步骤 3：实现最小功能**

定义：

```python
@dataclass(frozen=True)
class ProviderTestResult:
    status: ProviderErrorCode
    latency_ms: int
    message: str


class ProviderAdapter(Protocol):
    async def test_connection(self, *, base_url: str, model_id: str, api_key: str) -> ProviderTestResult: ...
```

Service 先写 keyring secret，再持久化元数据；数据库写入失败时删除刚写入的 secret。修改 URL/format/secret 后把所有模型状态重置为 `unknown`。测试只保存状态、延迟、时间戳和脱敏消息。

- [ ] **步骤 4：运行测试确认通过**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_service.py -v`

预期：Provider service 和 adapter 契约测试在无网络环境下通过。

- [ ] **步骤 5：删除旧的假 Registry 并提交**

所有 import 切换到 `ProviderService` 后删除 `backend/app/services/provider_registry.py`，并用新的 service/route 测试替换 `backend/tests/test_provider_registry.py`。

```bash
git add backend/app/providers backend/app/services/provider_service.py backend/app/schemas/settings.py backend/tests/test_provider_service.py backend/tests/test_provider_registry.py backend/app/services/provider_registry.py
git commit -m "feat(settings): add real provider adapters and model tests"
```

### 任务 5：设置 REST API 与依赖注入

**接口：**
- 产出 R1 spec 中精确定义的 Provider/Workspace endpoint。
- 响应使用 camelCase alias，永不包含 secret 值。

- [ ] **步骤 1：编写失败测试**

创建 `backend/tests/test_provider_routes.py`，覆盖 `get_provider_service` 和 `get_workspace_service` 依赖，然后验证：

```python
def test_create_provider_returns_redacted_resource(client):
    response = client.post("/api/settings/providers", json={"name": "P", "apiFormat": "openai-compatible", "baseUrl": "https://example.test/v1", "apiKey": "sk-secret"})
    assert response.status_code == 201
    assert response.json()["hasSecret"] is True
    assert "apiKey" not in response.json()


def test_delete_bound_model_returns_conflict(client):
    response = client.delete("/api/settings/provider-models/model-1")
    assert response.status_code == 409
    assert response.json()["code"] == "resource_in_use"
```

同时测试 Workspace 注册、列表、重新关联和模型绑定替换。

- [ ] **步骤 2：运行测试确认失败**

运行：`cd backend && UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_routes.py -v`

预期：失败，因为资源路由尚不存在。

- [ ] **步骤 3：实现最小功能**

在 `backend/app/api/dependencies.py` 创建 service 依赖。用 Repository 驱动的 WorkspaceService 替换 `_workspace`。在 R1.6 完成前保留 `GET/POST /api/settings/workspace` 作为弃用兼容层，但兼容层必须调用 WorkspaceService，不能使用进程全局变量。

为 typed service error 安装统一异常处理器，返回 `ErrorResponse(code, message)`。

- [ ] **步骤 4：运行测试确认通过并执行后端回归**

运行：

```bash
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest tests/test_provider_routes.py tests/test_workspace.py tests/test_schema.py -v
```

预期：全部聚焦测试通过。

- [ ] **步骤 5：提交**

```bash
git add backend/app/api/dependencies.py backend/app/api/routes_settings.py backend/app/core/errors.py backend/app/main.py backend/app/schemas/settings.py backend/app/services/workspace_service.py backend/tests/test_provider_routes.py backend/tests/test_workspace.py backend/tests/test_schema.py
git commit -m "feat(settings): expose provider and workspace resources"
```

### 任务 6：前端 API Client 与 Provider 管理

**接口：**
- 产出 typed API 方法 `listProviders`、`createProvider`、`updateProvider`、`deleteProvider`、`createProviderModel` 和 `testProviderModel`。
- `ProviderManager` 不持有 Workspace 绑定状态。

- [ ] **步骤 1：编写失败测试**

扩展 `frontend/src/shared/api/client.test.ts`，验证 PATCH/PUT/DELETE，包括 `204 No Content`。

创建使用 mocked fetch 的 `ProviderManager.test.tsx`，验证用户可以创建 Provider、添加两个模型、测试一个模型，并在 DOM 不出现 API Key 的前提下看到“认证失败”。

- [ ] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- client.test.ts ProviderManager.test.tsx`

预期：失败，因为 helper 和组件尚不存在。

- [ ] **步骤 3：实现最小功能**

新增通用 `apiRequest`，再暴露：

```ts
export const apiPatch = <TRequest, TResponse>(path: string, payload: TRequest) =>
  apiRequest<TResponse>(path, { method: "PATCH", body: JSON.stringify(payload) });

export const apiPut = <TRequest, TResponse>(path: string, payload: TRequest) =>
  apiRequest<TResponse>(path, { method: "PUT", body: JSON.stringify(payload) });

export const apiDelete = (path: string) => apiRequest<void>(path, { method: "DELETE" });
```

ProviderManager 渲染紧凑的 Provider 列表、协议选择、URL、只写 API Key、模型行、逐模型测试按钮和删除冲突反馈。API Key 不能进入 query cache 或 localStorage。

- [ ] **步骤 4：运行测试确认通过**

运行：`pnpm --dir frontend test -- client.test.ts ProviderManager.test.tsx`

预期：测试通过。

- [ ] **步骤 5：提交**

```bash
git add frontend/src/shared/api/client.ts frontend/src/shared/api/client.test.ts frontend/src/features/settings/providerTypes.ts frontend/src/features/settings/settingsApi.ts frontend/src/features/settings/ProviderManager.tsx frontend/src/features/settings/ProviderManager.test.tsx
git commit -m "feat(settings): manage providers and models in the browser"
```

### 任务 7：Workspace 模型用途绑定与切片验证

**接口：**
- 产出 `ModelBindings` for the four exact R1 roles.
- 修改 SettingsPage，组合 ProviderManager、ModelBindings 和现有 Workspace 控件。

- [ ] **步骤 1：编写失败测试**

创建 `ModelBindings.test.tsx`，断言四个带标签的选择器、持久化初值、包含四个 role 的 PUT 请求，以及 role 没有可用模型时的可见校验错误。

更新 `SettingsPage.test.tsx`，验证 Workspace 注册后出现 ProviderManager 和 ModelBindings，同时旧 Workspace 初始化仍可工作。

- [ ] **步骤 2：运行测试确认失败**

运行：`pnpm --dir frontend test -- ModelBindings.test.tsx SettingsPage.test.tsx`

预期：失败，因为 ModelBindings 尚不存在。

- [ ] **步骤 3：实现最小功能**

API payload 使用以下精确 role key：

```ts
export type ModelRole =
  | "question_generation"
  | "answer_evaluation"
  | "report_summarization"
  | "agent_chat";
```

每个 role 都引用已启用且已配置 secret 的模型后才能保存。保留当前测试依赖的中文 Workspace 标签。

- [ ] **步骤 4：运行切片完整验证**

运行：

```bash
pnpm --dir frontend test
pnpm --dir frontend build
cd backend
UV_CACHE_DIR=.uv-cache/backend uv run pytest
```

预期：全部前端测试、构建和后端测试通过。

- [ ] **步骤 5：编写本地验证记录并提交**

创建被忽略的 `docs/verification/r1_1_provider_settings.md`，记录浏览器步骤和真实 Provider 状态，然后提交受跟踪文件：

```bash
git add frontend/src/features/settings/ModelBindings.tsx frontend/src/features/settings/ModelBindings.test.tsx frontend/src/features/settings/SettingsPage.tsx frontend/src/features/settings/SettingsPage.test.tsx frontend/src/features/settings/settingsApi.ts
git commit -m "feat(settings): bind workspace model roles"
```

R1.1 验收：两个 Provider 和多个模型重启后仍存在；secret 值永不返回；连接测试按模型记录；四个 Workspace role 全部可以保存。
