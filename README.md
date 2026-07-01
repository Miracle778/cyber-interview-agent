# Cyber Interview Agent

本地优先的求职与面试 Agent，以及用于展示上下文隔离、制品交接、权限和可观测性的 Agent Harness。

## 环境要求

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+、22.13+ 或 24+
- npm

## 安装与启动

```bash
make install
cp backend/config.example.toml backend/config.local.toml
chmod 600 backend/config.local.toml
make dev
```

打开 <http://127.0.0.1:5173>。开发服务仅监听本机：

- 前端：`127.0.0.1:5173`
- 后端：`127.0.0.1:8000`
- 健康检查：`GET http://127.0.0.1:8000/api/health`

`backend/config.local.toml` 在 DU00 可以保留空 Key；该文件不会进入 Git。

## 质量门禁

```bash
make check
```

该命令依次验证后端和前端 lint、格式、TypeScript 类型、测试以及构建。

也可以单独执行：

```bash
make test
make lint
make typecheck
make build
```

## 项目结构

- `backend/`：FastAPI、领域与 Harness 后端。
- `frontend/`：React Web 客户端。
- `docs/`：架构、设计与实施计划。

