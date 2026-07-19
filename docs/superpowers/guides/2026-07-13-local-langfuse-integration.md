# 本机 Langfuse 对接指南

本文说明如何在本机启动 Langfuse v3，并将 Cyber Interview Agent 的
OpenTelemetry trace 发送到 Langfuse。该集成用于开发和调试，不是生产部署方案。

## 一、工作原理

Agent 不直接依赖 Langfuse SDK，业务代码只依赖项目自己的
`ObservabilitySink`。启用观测后，链路如下：

```text
Agent Middleware
  -> OpenTelemetry OTLP/HTTP exporter
  -> http://127.0.0.1:3000/api/public/otel/v1/traces
  -> Langfuse v3
```

Langfuse 是调试投影，不是业务真相源。session、execution、usage、HITL
和发布状态仍然以本地 Runtime SQLite 为准。Langfuse 不可用时，Agent
应该继续运行。

当前默认只发送安全元数据，例如 session、execution、Agent 类型、模型调用
类型和消息数量；默认不发送 Prompt、模型回复、个人资料、Vault 正文或工具参数。

## 二、前置条件

需要安装并运行：

- Docker Desktop，且 Docker daemon 已启动；
- `curl`；
- `openssl`（用于生成随机密钥）；
- 已安装项目后端依赖和前端依赖。

Langfuse v3 本机栈包含 Web、Worker、PostgreSQL、ClickHouse、Redis 和
MinIO，首次启动会下载镜像并占用较多磁盘空间。

## 三、创建 Langfuse 配置文件

推荐直接执行下面这一段。它会自动生成全部随机密钥、项目 key、登录密码和
OTLP Basic Auth，不需要手工填写十几个配置项：

```bash
cd /Users/miracle778/Project/cyber-interview-agent-new/infra/observability/langfuse
if [ -e .env ]; then
  echo "已存在 .env，跳过生成；如需重新生成请先备份后删除它。"
else
  umask 077
  project_public="pk-lf-local-$(openssl rand -hex 12)"
  project_secret="sk-lf-local-$(openssl rand -hex 24)"
  login_password="$(openssl rand -hex 16)"
  nextauth_secret="$(openssl rand -hex 32)"
  salt="$(openssl rand -hex 32)"
  encryption_key="$(openssl rand -hex 32)"
  postgres_password="$(openssl rand -hex 24)"
  clickhouse_password="$(openssl rand -hex 24)"
  redis_auth="$(openssl rand -hex 24)"
  minio_password="$(openssl rand -hex 24)"
  otlp_auth="$(printf '%s' "${project_public}:${project_secret}" | base64 | tr -d '\n')"

  cat > .env <<EOF
LANGFUSE_INIT_ORG_ID=local-org
LANGFUSE_INIT_ORG_NAME="Local Development"
LANGFUSE_INIT_PROJECT_ID=cyber-interview-agent
LANGFUSE_INIT_PROJECT_NAME="Cyber Interview Agent"
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=${project_public}
LANGFUSE_INIT_PROJECT_SECRET_KEY=${project_secret}
LANGFUSE_INIT_USER_EMAIL=local@example.invalid
LANGFUSE_INIT_USER_NAME="Local Developer"
LANGFUSE_INIT_USER_PASSWORD=${login_password}
NEXTAUTH_SECRET=${nextauth_secret}
SALT=${salt}
ENCRYPTION_KEY=${encryption_key}
POSTGRES_PASSWORD=${postgres_password}
CLICKHOUSE_PASSWORD=${clickhouse_password}
REDIS_AUTH=${redis_auth}
MINIO_ROOT_PASSWORD=${minio_password}
LANGFUSE_OTLP_AUTH=${otlp_auth}
EOF

  printf '\nLangfuse 配置已生成：%s/.env\n' "$PWD"
  printf '登录邮箱：local@example.invalid\n登录密码：%s\n' "$login_password"
  printf 'OTLP Auth 已写入 .env，不要提交或公开该文件。\n\n'
fi
```

`.env` 已被 Git 忽略，不要提交它，也不要把真实密钥粘贴到代码、截图或文档中。

如果 `.env` 已存在，脚本不会覆盖已有 Langfuse 数据对应的配置。忘记登录密码或
需要完全重新初始化时，先备份 `.env`，再执行 `docker compose down -v` 并重新运行
上面的生成命令。

### 3.1 手工配置（通常不需要）

只有需要固定项目 key、固定登录密码或接入已有 Langfuse 项目时，才需要手工配置。
否则跳过本节，直接执行“启动和检查 Langfuse”。

建议在终端分别生成以下值：

```bash
openssl rand -hex 32   # NEXTAUTH_SECRET
openssl rand -hex 32   # SALT
openssl rand -hex 32   # ENCRYPTION_KEY
openssl rand -hex 24   # POSTGRES_PASSWORD
openssl rand -hex 24   # CLICKHOUSE_PASSWORD
openssl rand -hex 24   # REDIS_AUTH
openssl rand -hex 24   # MINIO_ROOT_PASSWORD
```

将输出分别填入 `infra/observability/langfuse/.env`。其中：

- `NEXTAUTH_SECRET`、`SALT`、`ENCRYPTION_KEY` 是 Langfuse Web 的安全密钥；
- 其余四项是本地依赖服务的密码；
- `ENCRYPTION_KEY` 至少需要 32 字节，使用上面的 64 位十六进制值即可。

### 3.2 设置项目和登录信息

开发环境可以保留模板中的组织和项目 ID，但必须修改项目密钥和登录密码：

```env
LANGFUSE_INIT_ORG_ID=local-org
LANGFUSE_INIT_ORG_NAME=Local Development
LANGFUSE_INIT_PROJECT_ID=cyber-interview-agent
LANGFUSE_INIT_PROJECT_NAME=Cyber Interview Agent
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-local-替换为项目公钥
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-local-替换为项目私钥
LANGFUSE_INIT_USER_EMAIL=local@example.invalid
LANGFUSE_INIT_USER_NAME=Local Developer
LANGFUSE_INIT_USER_PASSWORD=替换为本机登录密码
```

项目 public key 和 secret key 是一对，后面生成 OTLP Basic Auth 时必须使用同一对值。

### 3.3 生成 OTLP Basic Auth

Langfuse OTLP 接口使用 `PUBLIC_KEY:SECRET_KEY` 的 Base64 值作为 Basic Auth：

```bash
PUBLIC_KEY='pk-lf-local-你的项目公钥'
SECRET_KEY='sk-lf-local-你的项目私钥'
printf '%s' "${PUBLIC_KEY}:${SECRET_KEY}" | base64
```

将命令输出填入 `.env`：

```env
LANGFUSE_OTLP_AUTH=上一步输出的Base64字符串
```

不要对整段值再次加引号，也不要在 Base64 字符串中插入换行。

## 四、启动和检查 Langfuse

启动前先检查 Compose 展开结果：

```bash
docker compose config
```

如果仍能看到 `replace-`、`change-me` 或未替换的随机密钥，先修正 `.env`。

启动服务：

```bash
docker compose up -d
```

检查容器状态：

```bash
docker compose ps
docker compose logs --tail=80 langfuse-web langfuse-worker
```

检查健康接口：

```bash
curl --fail http://127.0.0.1:3000/api/public/health
```

健康检查成功后打开 <http://127.0.0.1:3000>，使用 `.env` 中的
`LANGFUSE_INIT_USER_EMAIL` 和 `LANGFUSE_INIT_USER_PASSWORD` 登录。

首次启动可能需要等待数据库迁移完成；健康检查失败时先等待一两分钟，再查看
`docker compose logs`，不要反复删除 volume。

停止但保留数据：

```bash
docker compose down
```

删除本地 Langfuse 的所有数据（不可恢复）：

```bash
docker compose down -v
```

## 五、配置 Agent 后端

在启动后端的同一个终端设置环境变量：

```bash
export CYBER_OBSERVABILITY_ENABLED=true
export CYBER_OBSERVABILITY_SERVICE_NAME=cyber-interview-agent
export CYBER_OTLP_ENDPOINT=http://127.0.0.1:3000/api/public/otel/v1/traces
export CYBER_OTLP_HEADERS="Authorization=Basic ${LANGFUSE_OTLP_AUTH}"
```

如果当前终端没有加载 Compose 的 `.env`，可以显式读取其中的值，或直接复制
Base64 字符串：

```bash
export CYBER_OTLP_HEADERS='Authorization=Basic 这里填LANGFUSE_OTLP_AUTH'
```

推荐从 `.env` 中只读取 OTLP Auth，再启动后端（关闭终端后失效）。不要直接
`source .env`，因为 Compose 配置中包含带空格的显示名称：

```bash
cd /Users/miracle778/Project/cyber-interview-agent-new/infra/observability/langfuse
LANGFUSE_OTLP_AUTH="$(sed -n 's/^LANGFUSE_OTLP_AUTH=//p' .env)"
export CYBER_OBSERVABILITY_ENABLED=true
export CYBER_OTLP_ENDPOINT=http://127.0.0.1:3000/api/public/otel/v1/traces
export CYBER_OTLP_HEADERS="Authorization=Basic ${LANGFUSE_OTLP_AUTH}"
```

不要把这些变量加入公共 shell 配置，也不要在共享终端或录屏中显示它们。

可选配置：

```bash
export CYBER_OBSERVABILITY_FLUSH_TIMEOUT_MS=2000
export CYBER_OBSERVABILITY_CAPTURE_CONTENT=false
```

然后从当前项目启动后端：

```bash
cd /Users/miracle778/Project/cyber-interview-agent-new/backend
.venv/bin/uvicorn app.main:app --reload --port 8011
```

不要把这些 `export` 写入 Git 管理的 `.env` 或提交到仓库。若希望每次启动都配置，
可以在本机 shell profile 中维护私有变量，或使用未跟踪的本地启动脚本。

## 六、触发一次真实 trace

启动服务本身不会产生 Agent trace。需要完成一次真实模型调用：

1. 启动前端；
2. 初始化或选择 Workspace；
3. 在设置页配置 Provider 和模型；
4. 为 `answer_evaluation` 和 `report_summarization` 设置模型绑定；
5. 进入复习页提交一个回答；
6. 等待 Agent 执行至少一次模型调用。

在 Langfuse 中按 session 或最近时间查看 trace。当前主要 span 名称是：

```text
agent.model.call
```

可用于筛选和关联的属性包括：

```text
cyber.workspace.id
cyber.session.id
langfuse.session.id
cyber.execution.id
cyber.agent.kind
cyber.agent.version
gen_ai.operation.name
gen_ai.request.model_type
gen_ai.input.messages
```

## 七、验证是否真的接通

按以下顺序判断：

1. `curl http://127.0.0.1:3000/api/public/health` 成功；
2. 后端启动日志没有持续出现 `observability_export_failed`；
3. 完成一次真实复习调用；
4. Langfuse 中出现对应的 `agent.model.call`；
5. Langfuse 中的 `langfuse.session.id` 与页面使用的 session ID 一致。

如果 Langfuse 未启动，后端可能记录 `observability_export_failed` 或
`observability_flush_failed`，但业务执行不应因此失败。

## 八、常见问题

### 页面打开但没有 trace

- 确认后端启动时设置了 `CYBER_OBSERVABILITY_ENABLED=true`；
- 确认设置变量的是启动 `uvicorn` 的同一个终端；
- 确认执行过真实模型调用，而不只是打开页面；
- 确认 `CYBER_OTLP_HEADERS` 使用的是项目 key，而不是登录密码；
- 确认 OTLP endpoint 末尾是 `/api/public/otel/v1/traces`。

### Langfuse 返回 401 或 403

重新用当前 `.env` 中的 public/secret key 生成 Base64：

```bash
printf '%s' "${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}:${LANGFUSE_INIT_PROJECT_SECRET_KEY}" | base64
```

然后重启后端。修改 Langfuse 项目 key 后，旧的 `CYBER_OTLP_HEADERS` 不会自动更新。

### Docker 容器反复重启

```bash
docker compose ps
docker compose logs --tail=120 langfuse-web langfuse-worker postgres clickhouse redis minio
```

常见原因是 `.env` 仍有占位符、Docker 资源不足或首次数据库迁移尚未完成。

### 停止 Langfuse 后 Agent 失败

这不符合当前设计。先确认后端使用的是当前项目代码，并检查是否只是 warning；
OTLP exporter 失败应该由 `SafeObservabilitySink` 吞掉，业务 session、execution、
usage、HITL 和发布状态仍由本地 Runtime SQLite 负责。

## 九、安全和数据边界

- `.env`、Langfuse 登录密码、项目 secret key 和 OTLP Basic Auth 不得提交；
- 只在本机绑定 `127.0.0.1`，不要把该 Compose 配置直接暴露到公网；
- 不要在 span attributes 中加入 Prompt、回复、个人资料、Vault 正文或工具参数；
- `docker compose down` 不会删除数据；需要清理时必须明确使用 `down -v`；
- Langfuse 是调试投影，不可用时不能阻断 Agent 业务。

## 十、相关代码和配置

- `infra/observability/langfuse/compose.yaml`：本机 Langfuse v3 栈；
- `infra/observability/langfuse/.env.example`：环境变量模板；
- `backend/app/infrastructure/observability.py`：OTLP exporter 和 fail-open sink；
- `backend/app/middleware/observability_middleware.py`：Agent model span middleware；
- `docs/verification/runtime-middleware-1-0.md`：阶段验收证据和人工验收流程。
