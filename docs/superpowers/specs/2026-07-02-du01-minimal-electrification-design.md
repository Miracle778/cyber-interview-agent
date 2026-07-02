# DU01 最小通电切片 — 设计

日期：2026-07-02
状态：待用户审阅（review v2 已修订）
适用范围：DU01 单个交付单元

> 与 `docs/architecture-review/2026-07-01-week1-replan.md` §3「DU01」一致，是其在实现层的细化。与长期愿景文档冲突时，以定稿 `docs/superpowers/specs/2026-07-01-career-agent-architecture-finalization-design.md` 首月范围为准。状态名、状态机、安全不变量等一律以定稿为权威。

## 1. 目标与验收锚点

DU01 是一条**垂直切片（tracer bullet）**：用最薄的真实业务切片尽早通电「模型调用 → 流式 → 草稿 → 审批 → 发布」全链路，治理在真实负载下逐层加厚（DU02–DU04），而非先搭完整底座。

**验收锚点：** 真实模型调用 → 流式输出 → Profile 草稿 → 审批 → 发布 ProfileVersion。OpenAI 与 Anthropic 两家 adapter 均能跑通（真模型走 live eval，不进普通 CI）。

**DU01 = Profile 最小通电切片。** 明确不含：设置页、数据目录、版本历史、Run Center、Model/Tool Gate 全量、checkpoint/resume、command_id 幂等、global/workspace scope、Profile 完整结构化字段、视觉输入。见 §10。

## 2. 总体链路

```text
React Profile 页（粘贴文本）
  → POST /api/profile/runs {text}
  → ProfileService 定位/创建唯一 Profile Artifact（见 §7.4）
    → 创建 AgentRun(queued) + 首个 RunAttempt(queued)（短事务提交，返回 run_id）
  → Run Gate（调度前执行）：校验输入非空、artifact kind=profile、锁定最小 manifest
    → Gate 失败：queued → failed 短事务（见 §7.3），返回 run_id，前端经 SSE 收 failed
  → AgentRunService 经 TaskRegistry 调度 asyncio.create_task
    → TaskRegistry 接管后、模型调用前，短事务：AgentRun queued→running + RunAttempt queued→running(写 started_at)
    → 启动 AgentRuntime（loop 实现）
      → ModelGateway.stream → RuntimeEventMapper → 产出 RuntimeOutput 流
      → DeltaOutput：逐条落库为 RunEvent{delta} + 通知 SSE
      → 末尾 FinalOutputResult：交给 AgentRunService
  → AgentRunService 执行 Output Gate + 终态事务（terminal event 唯一持久化，见 §7.2/§7.3）
  → 成功路径原子事务：ArtifactVersion(draft→pending_approval) + RunAttempt(completed) + AgentRun(completed) + completed RunEvent → 提交 → 通知 SSE
  → 前端 SSE 收到 completed → 拉 pending_approval 草稿展示
  → 用户「批准发布」→ POST /api/profile/artifact-versions/{id}/approve
  → ArtifactApprovalService：单 SQLite 事务 pending_approval → published（已有 published 则拒绝，见 §7.5）
  → 前端展示 published
```

## 3. 分层落位（填 DU00 空壳目录）

DU00 已建 `app/ domain/ harness/ infra/` 空壳。DU01 填充：

| 层 | DU01 填充 |
|---|---|
| `domain/` | Artifact / ArtifactVersion 状态机（transitions 表）、AgentRun 状态机、ProfileVersion pydantic schema、状态转换纯函数 + 单测 |
| `app/` | `ProfileService`（创建 run）、`ArtifactApprovalService`（发布）、`AgentRunService`（编排 run 生命周期、事务边界、TaskRegistry 所有权） |
| `harness/` | `AgentRuntime` Port、轻量 loop 实现、`ModelGateway` Port、OpenAI/Anthropic adapter、`RuntimeEventMapper`、`FinalOutputParser`、`RunEventRepository` Port、`TaskRegistry`、Policy `Gate` 抽象基类 + Run/Output 实现（Model/Tool 接口预留） |
| `infra/` | SQLite repos（6 表）、Alembic 首迁移、`RunEventRepository` SQLite 实现、`ModelGateway` adapter 实例化（读 `config.py` 的 `ProviderConfig`） |
| `api/` | `profile.py` router（4 端点）、SSE 端点、`ErrorEnvelope` 映射 |

依赖规则（继承定稿 §3.1）：Domain 纯 Python 不依赖 SDK/SQLite/FastAPI；Application 依赖 Domain + Port；Harness 持有 Port 定义；Infra 实现 Port。

## 4. 数据模型与 SQLite（首个 Alembic 迁移）

DU01 建表遵循「用到时才建」（replan §4）。6 张表。`workspace_id`、`thread_id` 字段**现在就留**（DU01 可空、固定单 workspace/单隐式线程），归属见下表——DU03 加 scope 时**不新增业务标识列，但通过迁移收紧约束**（nullable → NOT NULL，仍需 migration，但不动列结构）。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `artifact` | id, workspace_id(可空,DU01写固定非空常量), kind('profile'), created_at | 制品身份 |
| `artifact_version` | id, artifact_id, version_no, schema_name, schema_version, content_json, status, created_at, published_at | 不可变版本；status ∈ {draft, pending_approval, published} |
| `agent_run` | id, artifact_id, workspace_id(可空,DU01写固定非空常量), thread_id(可空), status, command_id(可空), input_text, created_at, completed_at | status ∈ {queued, running, completed, failed} |
| `run_attempt` | id, run_id, attempt_no, status, started_at, ended_at | DU01 一个 run 一个 attempt；status 同 agent_run |
| `run_event` | id, run_id, sequence, event_type, payload_json, created_at | SSE 回放源；sequence 单调递增 |
| `model_call` | id, attempt_id, provider, model, request_id, tokens_in, tokens_out, latency_ms, cost_usd_micros | AuditTrace/Trace 最小 |

`workspace_id` 同时出现在 `artifact` 与 `agent_run`（两者须一致，DU01 由 ProfileService 在创建时写入同一固定值）；`thread_id` 归属 `agent_run`（DU03 才真正多线程）。

### 4.1 约束

- `(run_id, sequence)` UNIQUE（run_event）——保证 SSE 回放无歧义。
- `(artifact_id, version_no)` UNIQUE（artifact_version）——版本号在制品内唯一。
- `(run_id, attempt_no)` UNIQUE（run_attempt）——attempt 号在 run 内唯一。
- `(workspace_id, kind)` UNIQUE（artifact）——单 workspace 下每种 kind 唯一（见 §7.4）。**依赖 workspace_id 非空**，DU01 写固定常量 UUID。
- `status` 字段 CHECK 约束枚举值（artifact_version / agent_run / run_attempt 各自的合法集合）。
- `run_event.event_type` CHECK 枚举（DU01：`delta`/`partial`/`completed`/`failed`）。
- **部分唯一索引**（artifact_version）：`CREATE UNIQUE INDEX uq_artifact_one_published ON artifact_version(artifact_id) WHERE status = 'published';`——数据库级保证每个 artifact 最多一个 published 版本，作为 §7.5 Application 检查的最终防线。DU02 引入 superseded 后该索引仍适用（superseded 是独立状态，published 仍唯一），无需移除。
- 外键 + 删除策略：`ON DELETE RESTRICT`（artifact_version→artifact、agent_run→artifact、run_attempt→agent_run、run_event→agent_run、model_call→run_attempt）。DU01 不级联删除，避免孤儿事件/版本。
- 时间字段统一 UTC，存储 ISO-8601 字符串或 epoch 整数（迁移内统一一种，推荐 epoch ms）。
- `model_call.cost_usd_micros` 用**整数百万分之一美元**（micro-USD），不用浮点也不用美分——小模型调用常 <1 美分，美分会大量记为 0；micros 足够精度。`provider`/`model` 记录实际调用模型。
- `content_json` 存权威 Pydantic JSON（TEXT）。

**不建**（DU02–DU03）：workspace、agent_thread、tool_call、context_manifest、checkpoint、blob、source_snapshot、user_profile 聚合表（DU01 用 `artifact` kind=profile 代替）。

## 5. Profile 权威 Schema

```jsonc
{
  "schema_name": "profile",
  "schema_version": 1,
  "facts": [
    { "claim": "三年 Python 后端经验", "evidence_ref": null }
  ]
}
```

- `facts` 长度 1–3（验收锚点要求）；`claim` 非空字符串。
- `evidence_ref` 字段 DU01 留 null，DU02 接 SourceSnapshot 时填，避免 schema 迁移。
- Output Gate 在 DU01 **只校验该 schema**（字段齐全、claim 非空、长度 1–3），不做证据检查（DU02）。

## 6. 关键 Port 与接口

### 6.1 ModelGateway

```python
class ModelGateway(Protocol):
    async def stream(
        self, provider: str, model: str, messages: list[Message], *, max_tokens: int | None = None
    ) -> AsyncIterator[ModelChunk]: ...
```

`ModelChunk{type: "delta"|"done", text?, finish_reason?, usage?}`。OpenAI adapter 走 Responses API stream；Anthropic 走 messages stream。重试（瞬时错误、指数退避 + jitter）在 Gateway 内；认证失败、非法请求、内容拒绝不重试（定稿 §10.1）。`base_url` 来自 `ProviderConfig`。

两家 adapter 的结构化输出统一方式：DU01 **不依赖供应商的结构化输出特性**（避免 OpenAI/Anthropic schema 工具差异），而是要求模型直接输出 JSON 文本，由 `FinalOutputParser` 容错提取（见 §6.5）。prompt 明确指示「只输出符合 ProfileVersion schema 的 JSON，不要 markdown 围栏」。

### 6.2 AgentRuntime

```python
class AgentRuntime(Protocol):
    def run(self, ctx: RunContext) -> AsyncIterator[RuntimeOutput]: ...
```

`RuntimeOutput` 是 harness 层内部联合类型（非 RunEvent）：

- `DeltaOutput(text: str)` —— 流式文本片段。
- `FinalOutputResult(profile: ProfileVersion | None, error: OutputError | None)` —— 流结束的终态产物。

DU01 loop 实现：调 `ModelGateway.stream` → 每个 chunk 映射为 `DeltaOutput` yield；流结束后由 `FinalOutputParser` 解析，yield 一个 `FinalOutputResult` 后关闭迭代器。

Application 层（`AgentRunService`）消费该流时分流：`DeltaOutput` → 落库为 `RunEvent{delta}` + 通知 SSE；`FinalOutputResult` → 进入终态事务（§7.2/§7.3）。

**terminal event 所有权：** AgentRuntime **不产生** completed/failed RunEvent，只产 `DeltaOutput` 和一个 `FinalOutputResult`。completed/failed RunEvent 由 `AgentRunService` 在终态事务中唯一持久化——保证 terminal event 与 ArtifactVersion/状态更新原子提交，且只落库一次。

> 选 `AsyncIterator[RuntimeOutput]` 而非「yield + return」：Python async generator 不允许 `return <value>`（SyntaxError），调用方也无法从 `async for` 取返回值；统一为单一输出流是最简可实现契约。

**Port 签名预留 `checkpoint_ref` 字段（DU01 不用）**，DU03 替换为 LangGraph adapter 不破上层。`RunContext` 含 run_id、attempt_id、agent_definition、locked manifest、model 配置。

### 6.3 Policy Gate

`Gate` 抽象基类：`check`/`validate` → `None | raises`。DU01 实现 `RunGate`（输入/manifest/scope）和 `OutputGate`（schema 校验）。Model/Tool Gate 是接口预留，DU02/DU03 新增子类，pipeline 结构现在立好。

### 6.4 TaskRegistry（后台任务所有权）

`AgentRunService` 不裸调 `asyncio.create_task`，而是经 `TaskRegistry` 持有 task 引用，保证：

- **所有权**：registry 按 run_id 持有 Task 引用，run 完成后移除。
- **未订阅 SSE 不影响**：task 生命周期与 SSE 订阅解耦，无人订阅时仍执行到 terminal。
- **统一异常边界**：task 体内所有未捕获异常由 registry 的包装捕获，转成 run failed + failed RunEvent（同事务，见 §7.2），绝不让 run 永久停在 running。
- **应用关闭**：FastAPI lifespan shutdown 时 registry 取消所有活跃 task，对应 run 标记为 failed（DU01 不支持恢复，重启后由 DU03 的 interrupted 机制处理；DU01 重启后遗留 running 视为 failed，写入 failed event）。
- **测试清理**：测试 fixture 在 teardown 调 `registry.cancel_all()`，不遗留 task 跨用例。

### 6.5 FinalOutputParser（模型输出 → FinalOutputResult）

链路：`ModelChunk(delta)` 累积完整文本 → 提取 JSON → `ProfileVersion.model_validate_json` → 返回 `FinalOutputResult`。

- **累积**：loop 把所有 `delta.text` 拼接为 `full_text`，流结束（`ModelChunk(type=done)`）后解析。
- **提取**：`FinalOutputParser` 容错处理常见杂质——剥离 markdown 围栏（```json ... ```）、定位首个 `{` 到末个 `}` 的子串。提取失败视为解析失败。
- **解析**：`ProfileVersion.model_validate_json(extracted)`，pydantic 校验 schema（facts 1–3、claim 非空、evidence_ref 可空）。
- **产出**：`FinalOutputParser` 的结果是 `FinalOutputResult`（dataclass），含 `profile: ProfileVersion | None` 和 `error: OutputError | None`（二选一）。成功时 profile 非空，失败时 error 携带 category/safe_message/finish_reason。它作为 `AgentRuntime.run` 流的最后一个 `RuntimeOutput` 交给 `AgentRunService`，**不包装成 RunEvent**。
- **partial 事件**：DU01 不发 `partial`（已解析的中间 facts）；`partial` 是 RunEvent 枚举预留位，DU02 按需启用。流式期间只发 `delta`（原始文本片段）。

四种结果（普通 CI 必须覆盖）：

| 情况 | 触发 | FinalOutputResult | Application 层处理 |
|---|---|---|---|
| 合法 JSON | full_text 提取后通过 model_validate | profile=ProfileVersion | Output Gate → 成功事务 §7.2 |
| 非法 JSON | 提取到的子串不是合法 JSON | error(category=model,「无法解析为 JSON」) | 失败事务 §7.3 |
| 截断输出 | 流未正常 done 或 finish_reason=length 且 JSON 不完整 | error(category=model, 记录 finish_reason) | 失败事务 §7.3 |
| schema 不合法 | JSON 合法但字段缺失/长度超限 | error(category=policy) | 失败事务 §7.3（Output Gate 拒绝） |

Output Gate 接收 `FinalOutputResult`：profile 非空时 Gate 再做一次 schema 断言（防御性，DU02 加证据检查时 Gate 才真正有逻辑）；error 非空时 Gate 转 policy/model 错误进入失败事务。

### 6.6 契约测试

为 `ModelGateway`、`AgentRuntime`、`FinalOutputParser` 各写一套契约测试。DU01 的 loop 实现跑契约测试；真 OpenAI/Anthropic adapter 走 live eval 标记，不进普通 CI（避免成本与不稳定）。`FinalOutputParser` 契约测试覆盖 §6.5 四种情况。

## 7. 状态机与事务顺序

### 7.1 状态机（DU01 子集）

显式 transitions 表，非法转换 raise。DU02/DU03 加行不破现有。

```text
ArtifactVersion: draft → pending_approval → published
AgentRun:         queued → running → completed | failed
                 queued → failed   (Run Gate 失败，未进入 running)
```

- 流式完成、Output Gate 通过后，draft 自动转 pending_approval（待审批）。
- 审批发布：pending_approval → published，单 SQLite 事务（定稿 §5.4：发布不调用模型/工具/文件写入）。
- `queued → failed`：Run Gate 在调度前失败时直接转 failed，不经过 running（§7.3 失败事务同样适用，attempt 也置 failed）。
- superseded/rejected（DU02）、waiting_input/interrupted/cancelled（DU03）不在 DU01。

### 7.2 成功路径事务顺序（原子）

`AgentRunService` 收到 `AgentRuntime.run` 返回的 `FinalOutputResult`（profile 非空）后，单 SQLite 事务，按序：

1. Output Gate 校验 `FinalOutputResult.profile`（纯内存，无 DB 写）。
2. 创建 `ArtifactVersion(status=draft, content_json=ProfileVersion JSON)`。
3. ArtifactVersion `draft → pending_approval`（写 status；published_at 保持 null）。
4. `RunAttempt` status → `completed`，写 `ended_at`。
5. `AgentRun` status → `completed`，写 `completed_at`。
6. 写 `RunEvent{event_type=completed, sequence=下一序号}`。
7. **提交事务**。
8. 提交成功后通知 SSE 订阅者（事务外）。

步骤 2–6 在同一事务，要么全成要么全失败——避免「Run 已 completed 但 ArtifactVersion/Attempt 未更新」的中间状态。terminal RunEvent 只在此处持久化一次（AgentRuntime 不产 terminal event）。SSE 通知在提交后，避免「前端收到 completed 但查不到草稿」。

### 7.3 失败路径事务顺序（原子）

`AgentRunService` 捕获到 `FinalOutputResult.error` 或未捕获异常后，单 SQLite 事务：

1. `RunAttempt` status → `failed`，写 `ended_at`。
2. `AgentRun` status → `failed`，写 `completed_at`。
3. 写 `RunEvent{event_type=failed, payload={category, safe_message, diagnostic_id}, sequence=下一序号}`。
4. **提交事务**。
5. 提交成功后通知 SSE 订阅者。

failed 状态、RunAttempt 状态与 failed event 同事务提交，保证前端看到 failed 时一定能查到失败原因与 attempt 终态。

### 7.4 Artifact 创建/复用规则

DU01 是「单隐式 workspace 下唯一 kind=profile 的 Artifact」：

- DU01 使用一个**固定非空常量 UUID** 作为隐式 workspace_id（domain 常量 `DEFAULT_WORKSPACE_ID`）。`workspace_id` 列虽标注 nullable（为 DU02/DU03 留迁移空间），但 DU01 写入时**始终用该常量非空值**，使 `(workspace_id, kind)` UNIQUE 真正生效——SQLite UNIQUE 允许多个 NULL，写 NULL 会破坏唯一性。
- DU03 多 workspace 时，该常量成为 default workspace 的真实 id，不破坏既有数据。
- `ProfileService` 创建 run 时，先按 `(workspace_id=DEFAULT_WORKSPACE_ID, kind='profile')` 查找现有 Artifact；不存在则创建。
- 所有 Profile run 的 `agent_run.artifact_id` 都指向这同一个 Artifact。
- 「当前版本」= 该 Artifact 下 status ∈ {pending_approval, published} 中 `version_no` 最大的版本。
- **版本数量规则**：允许多个 pending_approval 版本并存（多次 run 各产草稿）；但最多一个 published（由 §7.5 的部分唯一索引保证）。不限制 pending_approval 数量，避免误加「pending 唯一」约束。

### 7.5 多 published 防护（DU01 临时规则）

DU01 不实现 superseded（DU02），为避免同一 Artifact 出现多个 published 版本破坏权威唯一性，采用**双层防护**：

- **Application 层（友好错误）**：`ArtifactApprovalService` 在发布事务内检查该 Artifact 是否已存在 published 版本。已有 → 拒绝，返回 `ErrorEnvelope(category=policy, code=already_published)`，不修改状态。无 → 正常 `pending_approval → published`。
- **数据库层（最终防线）**：部分唯一索引 `uq_artifact_one_published`（§4.1）保证每个 artifact 最多一个 published，即使 Application 检查被绕过或并发漏检也无法插入第二个 published（违反约束时事务回滚）。

这条规则在 DU02 实现 supersede 后移除 Application 检查；DB 索引保留（superseded 不影响 published 唯一）。

并发审批：发布检查与状态更新在同一事务，加上 DB 部分唯一索引兜底，杜绝两个并发 approve 同时把两个版本置 published。集成测试覆盖：对同一 artifact 两个 pending_approval 版本并发 approve，断言最终只有一个 published、另一个仍 pending_approval 或因约束冲突回滚。

## 8. HTTP API（4 端点）

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/profile/runs` | 提交文本，创建 AgentRun(queued)，返回 run_id。Body: `{text}` |
| GET | `/api/profile/runs/{run_id}/events` | SSE 流，按 sequence 推 RunEvent，支持 `Last-Event-ID` 回放 |
| GET | `/api/profile/runs/{run_id}` | 查 run 状态 + 当前 pending_approval artifact_version |
| POST | `/api/profile/artifact-versions/{id}/approve` | pending_approval → published（单事务） |

### 8.1 command_id 边界（DU01 不启用）

`command_id` 在 DU01 **不接受客户端传入，仅作为 nullable 列预留**：

- POST body 不含 `command_id` 字段；`agent_run.command_id` 始终为 null。
- DU01 不实现幂等，行为确定：每次 POST 创建一个新 run，无重复值语义问题。
- 字段与表结构现在留好，表内**不存在任何非空重复值**，DU04 启用幂等时可直接加唯一约束 + 去重逻辑，无需数据清理 migration。

这样 DU01 接口契约干净（无虚假幂等承诺），又为 DU04 预留了字段且不埋迁移雷。

### 8.2 SSE wire-level 契约

每个事件必须按 SSE 规范写出三行：

```text
id: <sequence>
event: <event_type>
data: <RunEvent JSON>

```

- `id:` = run_event.sequence（整数）。**服务端必须实际写出 `id:` 字段**——浏览器原生 `EventSource` 依赖它自动在重连时发送 `Last-Event-ID`，不能只在 `data` JSON 里放 sequence。
- `event:` = event_type（`delta`/`partial`/`completed`/`failed`）。
- `data:` = 稳定 JSON RunEvent（含 run_id、sequence、event_type、payload、created_at）。
- `Content-Type: text/event-stream`；禁用代理缓存（`Cache-Control: no-cache`、`X-Accel-Buffering: no`）。
- `Last-Event-ID` 语义为 **exclusive**：回放 sequence > Last-Event-ID 的事件（Last-Event-ID 本身已投递，不重发）。无 Last-Event-ID 时从 sequence=1 开始。
- terminal event（completed/failed）发送后服务端关闭连接。
- **心跳**：连接空闲时每 15s 发 `: ping\n\n`（SSE 注释行），防中间代理超时断连。
- **不存在的 run_id**：直接返回 **HTTP 404 + `ErrorEnvelope`**（category=`input`，code=`run_not_found`）。不合成 failed event——不存在 AgentRun 时无法满足外键、无法落库 RunEvent，合成事件会违反「先落库再发送」不变量。前端 `EventSource` 收到 onerror 后，先调用 `GET /api/profile/runs/{run_id}` 区分 404（run 不存在，停止重连）与临时断线（run 存在，继续重连），避免无限重连。
- RunEvent 必须成功落库后才能发送（定稿 §7.2）；断线不取消 run（task 与 SSE 解耦，见 §6.4）。

错误统一走 `ErrorEnvelope`（定稿 §10）：code/category/retryable/safe_message/diagnostic_id/next_actions。前端按 category 呈现，不解析字符串。

## 9. 前端（一个 Profile 页）

- 文本框粘贴资料 → 点「抽取」→ 创建 run。
- SSE 订阅（`EventSource`），展示 streaming 三态（loading / streaming / done）。
- 流式完成后展示 Profile 草稿（facts 列表）。
- 「批准发布」按钮 → 调 approve → 展示 published 状态。
- SSE 断线重连用 `Last-Event-ID`（`EventSource` 自动发送）。`onerror` 时先调 `GET /api/profile/runs/{run_id}` 区分 404（停止重连）与临时断线（继续重连）。

技术栈继承 DU00：TanStack Query 管理服务端状态，`queryKey` 以 scope 开头（DU01 `["profile", run_id, ...]`），SSE 事件按 `run_id + sequence` 去重。

## 10. 明确不做（边界）

设置页、数据目录 / Blob、版本历史 / diff、superseded / rejected 审批 UI、Run Center、Model Gate 全量（预算/PII/fallback）、Tool Gate、AuditTrace 全量、checkpoint / resume、command_id 幂等（DU01 仅预留字段，见 §8.1）、global/workspace scope（DU01 单隐式 workspace/thread）、Profile 完整结构化字段、视觉输入。全部 DU02–DU04。

## 11. 测试策略

- **Domain 单测**：状态机转换合法/非法、Profile schema 校验、Artifact 不可变（draft/pending_approval 内容落库后不可改）。
- **契约测试**：ModelGateway（chunk 序列、重试、错误分类）、AgentRuntime（产出 DeltaOutput 流 + 末尾一个 FinalOutputResult、不产 terminal RunEvent、checkpoint 参数存在）、FinalOutputParser（§6.5 四种情况）。
- **集成测试**：
  - SQLite 事务（发布原子性、draft 不可原地改、`(artifact_id,version_no)`/`(run_id,attempt_no)`/`(run_id,sequence)`/`(workspace_id,kind)` 唯一约束生效）。
  - 成功/失败路径事务顺序（§7.2/§7.3）——断言 completed+artifact_version+run_attempt 同事务、failed+run_attempt+failed_event 同事务。
  - terminal event 唯一持久化——AgentRuntime 不产 terminal event，断言 run 只有一个 completed 或 failed event。
  - 多 published 防护（§7.5）——对同一 artifact 并发 approve 两个版本，断言最终只一个 published。
  - Artifact 复用（§7.4）——两次 run 复用同一 artifact_id。
  - SSE replay（`Last-Event-ID` exclusive 回放、sequence 去重、terminal 后关连接、心跳）。
  - 不存在 run_id 返回 404（不合成 event）。
  - Output Gate 拦截坏 schema → run failed。
  - TaskRegistry：未订阅 SSE run 仍到 terminal、未捕获异常→failed、shutdown 取消、测试无遗留 task。
- **Fake Model**：自动化测试用 `FakeModelGateway`（注入预定义 chunk 序列 + 模拟瞬时错误 + 模拟截断/非法 JSON），不耗真 key。
- **前端测试**：Profile 页三态、批准发布交互、SSE 断线重连 + onerror 区分 404（mock SSE）。

## 12. 扩展点（为 DU02–DU04 留好）

- 4-Gate pipeline 结构现在立好，DU01 填 2 个，DU02/DU03 加 2 个——增量非重写。
- Artifact / AgentRun 状态机 transitions 表可加行。
- `workspace_id` / `thread_id` 字段已留，DU03 不新增列但通过迁移收紧约束（nullable→NOT NULL）。
- `AgentRuntime` Port 预留 `checkpoint_ref`，DU03 换 LangGraph adapter 不破上层。
- `evidence_ref` 字段已留，DU02 接 Blob 时填。
- `ModelGateway` Port 稳定，DU02 加 Model Gate（预算/PII）在 Gateway 外包一层，不改 adapter。
- `command_id` 字段已留，DU04 加唯一约束 + 幂等去重，不改 schema。
- `RunEvent.event_type` 的 `partial` 枚举已留，DU02 按需启用。
