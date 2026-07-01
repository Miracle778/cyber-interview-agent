# DU00 工程基线设计

日期：2026-07-01
状态：待用户审阅
适用范围：DU00 工程基线（定稿 §15 Week 1 首个单元）
依据：`docs/superpowers/specs/2026-07-01-career-agent-architecture-finalization-design.md`、`docs/architecture-review/2026-07-01-week1-replan.md`

## 1. 目标与边界

DU00 建立前后端工程骨架与质量门禁，不实现任何业务功能。骨架的分层目录、配置读取、健康检查契约和质量门禁要为 DU01+ 直接复用，不返工。

明确不在 DU00 范围：业务端点、SQLite 表、Alembic 迁移版本、ModelGateway、SSE、Artifact、Blob。全部 DU01+。

## 2. 技术选型（已确认）

- 仓库：Monorepo，根目录 `backend/` + `frontend/`。
- 后端：Python 3.12，uv 管依赖与虚拟环境，Ruff 做 lint/format，pytest 测试。
- 后端 DB 访问：SQLAlchemy 2.0 + Alembic（DU00 只建骨架，不生成迁移）。
- 前端：React + TypeScript + Vite，React Router，TanStack Query，shadcn/ui + Tailwind CSS。
- UI 测试：Vitest + Testing Library。
- 本地启动：根目录 Makefile，`make dev` 一键拉起前后端。
- 服务绑定：仅 `127.0.0.1`。
- 前端服务形态：DU00 仅 dev 模式（Vite dev server + FastAPI dev）。生产静态服务留待 DU12。

## 3. 仓库结构

```text
cyber-interview-agent/
├── Makefile
├── README.md
├── .gitignore
├── .python-version
├── backend/
│   ├── pyproject.toml          # uv 管理，Ruff + pytest 配置
│   ├── uv.lock
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── config.example.toml
│   └── src/cyber_interview/
│       ├── __init__.py
│       ├── main.py             # FastAPI app 工厂，绑定 127.0.0.1
│       ├── api/
│       │   ├── __init__.py
│       │   └── health.py
│       ├── app/                # Application Service，DU01+ 填充
│       ├── domain/             # 纯业务规则，DU01+ 填充
│       ├── harness/            # Career Harness Port + 实现，DU01+ 填充
│       ├── infra/              # SQLite repo、Blob、模型 adapter，DU01+ 填充
│       ├── config.py           # config.local.toml 读取 + 权限校验
│       ├── settings.py         # Pydantic Settings
│       └── tests/
│           ├── __init__.py
│           ├── conftest.py
│           ├── test_health.py
│           └── test_settings.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── components.json         # shadcn 配置
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── routes/
│       ├── lib/
│       │   ├── queryClient.ts
│       │   └── api.ts
│       ├── components/ui/      # shadcn 组件
│       └── pages/
│           ├── Home.tsx
│           └── NotFound.tsx
└── docs/                       # 已有
```

包名用 `cyber_interview`（下划线，对齐仓库名 `cyber-interview-agent`）。`pyproject.toml` 发行名 `cyber-interview-agent`，`packages = [{include = "cyber_interview", from = "src"}]`。

分层目录 `app/ domain/ harness/ infra/` 在 DU00 提前建好（带 docstring 的 `__init__.py`），DU00 只填 `api/health.py` + `config.py` + `settings.py` + `main.py`，DU01+ 直接往各层加文件。

`data/` 目录 DU00 不建，但 `.gitignore` 先收录。`backend/config.local.toml` 同理，并提供 `config.example.toml` 模板。

## 4. 后端骨架

### 4.1 main.py

FastAPI app 工厂，显式绑定 `127.0.0.1`：

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Cyber Interview Agent", version="0.0.0")
    app.include_router(health.router)
    return app

app = create_app()
```

启动命令（写进 Makefile）：`uv run uvicorn cyber_interview.main:app --host 127.0.0.1 --port 8000 --reload`。

### 4.2 健康检查契约

`GET /api/health` 是 DU00 唯一真实端点，也是 DU01+ 的健康基线：

```json
{
  "status": "ok",
  "version": "0.0.0",
  "checks": {
    "database": "skipped",
    "providers": "not_configured"
  }
}
```

- `checks` 是稳定契约：DU00 只放占位状态，DU01 接 SQLite 后 `database` 变 `ok`/`degraded`，接 ModelGateway 后 `providers` 填实际状态。前端不改。
- DU00 不做任何真实 I/O（不连库、不发请求），健康检查永远 ok、永远快。
- `/api` 前缀全局约定，与前端 Vite 代理对齐。

### 4.3 settings.py

Pydantic Settings，**仅承载非敏感应用配置**，从环境变量 + `.env` 读取。DU00 最小字段：

```python
class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("./data")
    model_config = SettingsConfigDict(env_prefix="CIA_", env_file=".env")
```

DU01 扩展 provider 的非敏感配置（默认模型名、超时、重试次数等）。

**敏感配置（API Key）不进 Settings、不进环境变量**，由 `config.py` 从 `config.local.toml` 读取（见 4.4，对齐审查决策 A）。两者职责分离：Settings = 应用配置，config.py = 密钥与敏感凭据。

### 4.4 config.py

`config.local.toml` 读取器（标准库 `tomllib`）。DU00 建好读取链路 + 权限校验（文件权限 ≤ 600，否则启动警告），但不验证 Key 内容。`config.local.toml` 进 `.gitignore`，提供 `config.example.toml` 模板。

### 4.5 Alembic

`alembic init` 生成骨架，`env.py` 用 `cyber_interview.settings` 的 `data_dir`。DU00 不生成任何迁移版本（无表），只保证 `alembic` 命令能跑、`versions/` 目录存在。DU01 接 SQLite 时生成首个迁移。

### 4.6 后端测试

- `tests/test_health.py`：`httpx.AsyncClient` + `ASGITransport` 打 `/api/health`，断言 200 + `status=="ok"` + `checks` 字段存在。不启真实服务器。
- `tests/test_settings.py`：断言默认值 + 环境变量覆盖。
- `tests/conftest.py`：提供 app fixture。

### 4.7 Ruff 配置

`pyproject.toml` 内：line-length 100、target Python 3.12、规则组 `E F I UP B`，`src/cyber_interview` 与 `tests` 均纳入。

## 5. 前端骨架

### 5.1 初始化

Vite `react-ts` 模板 + Tailwind + shadcn + React Router + TanStack Query。

### 5.2 Vite 配置

```ts
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
```

前端只请求 `/api/...`。开发时 Vite 代理到后端，生产同源（DU12 配静态服务，DU00 不碰）。

### 5.3 路由

React Router，DU00 两个路由验证刷新恢复 + 404 边界：

- `/` — 首页，调 `/api/health` 显示后端状态。
- `*` — 404 页。

### 5.4 TanStack Query

- `lib/queryClient.ts`：配置 `staleTime`、`retry`，全局 `QueryClient`。
- `lib/api.ts`：封装 `fetch` + 错误映射。**queryKey 规范**：始终以 scope 开头（DU00 用 `["health"]`，DU01+ 扩展为 `["workspace", id, ...]`），从一开始避免跨 scope 混 key（定稿 §13 要求）。
- `pages/Home.tsx`：`useQuery({ queryKey: ["health"], queryFn: () => api.getHealth() })`，展示 loading / success / error 三态。DU00 唯一真实联调点，也是 DU01 SSE 接入基础。

### 5.5 shadcn

`npx shadcn@latest init`，配 `components.json`、`tailwind.config.ts`、CSS 变量主题。DU00 只装 `Button`、`Card` 验证链路，其余按需加。

### 5.6 可访问性基线

- `index.html` 有 `lang="zh-CN"`。
- 主题用 CSS 变量，不只靠颜色传递状态（health 页 ok/error 同时用文字 + 颜色）。
- 焦点可见。

### 5.7 前端测试

Vitest + Testing Library：

- `Home.test.tsx`：mock `/api/health`，断言 loading → success 三态渲染。
- 一个最小组件测试验证 Testing Library 链路。

### 5.8 前端质量门禁

`npm run lint`（eslint）、`npm run typecheck`（`tsc --noEmit`）、`npm run build`、`npm run test`。

## 6. Makefile

根目录，跨前后端统一入口：

```makefile
.PHONY: install dev backend frontend test test-backend test-frontend lint lint-backend lint-frontend format check build

install:           # uv sync + npm ci
dev:               # 并行起 backend (uvicorn) + frontend (vite)，trap 清理
backend:           # 单起后端
frontend:          # 单起前端
test:              # test-backend + test-frontend
test-backend:      # uv run pytest
test-frontend:     # npm run test
lint:              # lint-backend + lint-frontend
lint-backend:      # uv run ruff check
lint-frontend:     # npm run lint && npm run typecheck
format:            # ruff format + eslint --fix
check:             # lint + test（CI 等价门禁，全绿才算过）
build:             # frontend npm run build
```

`dev` 目标用 `trap 'kill 0' EXIT` 同时起前后端，任一退出都清理双方，避免留僵尸进程。

## 7. .gitignore 修正

当前 `.gitignore` 错误地忽略了整个 `/docs/`——docs 是项目核心产出，必须入库。DU00 修正为：

```gitignore
# Python
backend/.venv/
backend/__pycache__/
*.pyc
backend/.ruff_cache/
backend/.pytest_cache/

# Node
frontend/node_modules/
frontend/dist/

# 本地数据与密钥（绝不入库）
backend/config.local.toml
data/

# OS
.DS_Store
.superpowers/
```

## 8. README

写明：

- 前置：Python 3.12、Node 20、uv。
- 启动：`make install` + `make dev`。
- 验收：`make check`。
- 端口约定：后端 8000 / 前端 5173。
- 健康检查端点：`GET /api/health`。
- 配置：复制 `config.example.toml` 为 `config.local.toml` 填 Key（DU00 可空）。

这是定稿 §15 Week 1「新环境可按文档一次启动」的载体。

## 9. DU00 验收门槛

1. 全新 clone 后，按 README `make install` + `make dev` 可一次拉起前后端。
2. 浏览器访问前端首页，能读到后端 `/api/health` 的 ok 状态（真实联调通电）。
3. `make check` 后端测试、前端测试、lint、typecheck、build 全部通过。
4. `/docs/` 已纳入 git（修正 .gitignore），docs 随仓库走。
5. `config.local.toml` 与 `data/` 确认被 gitignore，密钥绝无入库风险。

## 10. 为 DU01 留好的扩展点

- 分层目录已建空壳，DU01 直接加文件。
- `settings.py` provider 非敏感字段位预留；Key 走 `config.py`（toml）。
- `config.py` 读取链路就绪，DU01 接 Key。
- 健康检查 `checks` 契约稳定，DU01 填真实值。
- queryKey scope 规范已立，DU01 扩展。
- Alembic 骨架就绪，DU01 生成首个迁移。
