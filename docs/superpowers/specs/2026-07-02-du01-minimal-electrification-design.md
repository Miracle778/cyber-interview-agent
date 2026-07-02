# DU01 最小通电切片 — 设计

日期：2026-07-02
状态：待用户审阅
适用范围：DU01 单个交付单元

> 与 `docs/architecture-review/2026-07-01-week1-replan.md` §3「DU01」一致，是其在实现层的细化。与长期愿景文档冲突时，以定稿 `docs/superpowers/specs/2026-07-01-career-agent-architecture-finalization-design.md` 首月范围为准。

## 1. 目标与验收锚点

DU01 是一条**垂直切片（tracer bullet）**：用最薄的真实业务切片尽早通电「模型调用 → 流式 → 草稿 → 审批 → 发布」全链路，治理在真实负载下逐层加厚（DU02–DU04），而非先搭完整底座。

**验收锚点：** 真实模型调用 → 流式输出 → Profile 草稿 → 审批 → 发布 ProfileVersion。OpenAI 与 Anthropic 两家 adapter 均能跑通（真模型走 live eval，不进普通 CI）。

**DU01 = Profile 最小通电切片。** 明确不含：设置页、数据目录、版本历史、Run Center、Model/Tool Gate 全量、checkpoint/resume、command_id 幂等、global/workspace scope、Profile 完整结构化字段、视觉输入。见 §10。

## 2. 总体链路

```text
React Profile 页（粘贴文本）
  → POST /api/profile/runs {text, command_id}
  → ProfileService 创建 AgentRun(queued) + 首个 RunAttempt
  → Run Gate：校验输入非空、artifact kind=profile、锁定最小 manifest
  → asyncio.create_task 启动 AgentRuntime（loop 实现）
      → ModelGateway.stream(provider, model, messages)
      → RuntimeEventMapper：provider chunk → 稳定 RunEvent{delta/partial}
      → RunEvent 事务落库（sequence 严格递增）→ 通知 SSE 订阅者
  → Output Gate：校验 profile schema（facts 1–3，claim 非空）→ 不通过 run failed
  → 通过：创建 ArtifactVersion(status=draft)，自动 draft → pending + RunEvent{completed}
  → 前端 SSE 收到 completed → 拉 pending 草稿展示
  → 用户「批准发布」→ POST /api/profile/artifact-versions/{id}/approve
  → ArtifactApprovalService：单 SQLite 事务 pending → published
  → 前端展示 published
```

## 3. 分层落位（填 DU00 空壳目录）

DU00 已建 `app/ domain/ harness/ infra/` 空壳。DU01 填充：

| 层 | DU01 填充 |
|---|---|
| `domain/` | Artifact / ArtifactVersion 状态机（transitions 表）、AgentRun 状态机、ProfileVersion pydantic schema、状态转换纯函数 + 单测 |
| `app/` | `ProfileService`（创建 run）、`ArtifactApprovalService`（发布）、`AgentRunService`（编排 run 生命周期、事务边界） |
| `harness/` | `AgentRuntime` Port、轻量 loop 实现、`ModelGateway` Port、OpenAI/Anthropic adapter、`RuntimeEventMapper`、`RunEventRepository` Port、Policy `Gate` 抽象基类 + Run/Output 实现（Model/Tool 接口预留） |
| `infra/` | SQLite repos（6 表）、Alembic 首迁移、`RunEventRepository` SQLite 实现、`ModelGateway` adapter 实例化（读 `config.py` 的 `ProviderConfig`） |
| `api/` | `profile.py` router（4 端点）、SSE 端点、`ErrorEnvelope` 映射 |

依赖规则（继承定稿 §3.1）：Domain 纯 Python 不依赖 SDK/SQLite/FastAPI；Application 依赖 Domain + Port；Harness 持有 Port 定义；Infra 实现 Port。

## 4. 数据模型与 SQLite（首个 Alembic 迁移）

DU01 建表遵循「用到时才建」（replan §4）。6 张表，`workspace_id` / `thread_id` 字段**现在就留**（DU01 值暂固定/可空），DU03 加 scope 时只改约束不改 schema——骨架式增量。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `artifact` | id, workspace_id(可空), kind('profile'), created_at | 制品身份 |
| `artifact_version` | id, artifact_id, version_no, schema_name, schema_version, content_json, status, created_at, published_at | 不可变版本；status ∈ {draft,pending,published} |
| `agent_run` | id, artifact_id, status, command_id, input_text, created_at, completed_at | status ∈ {queued,running,completed,failed} |
| `run_attempt` | id, run_id, attempt_no, status, started_at, ended_at | DU01 一个 run 一个 attempt |
| `run_event` | id, run_id, sequence, event_type, payload_json, created_at | SSE 回放源；sequence 单调递增 |
| `model_call` | id, attempt_id, provider, model, request_id, tokens_in, tokens_out, latency_ms, cost | AuditTrace/Trace 最小 |

约束：`run_event` 上 `(run_id, sequence)` 唯一索引；`artifact_version.status` CHECK 约束；`artifact_version.content_json` 存权威 Pydantic JSON。

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

### 6.2 AgentRuntime

```python
class AgentRuntime(Protocol):
    async def run(self, ctx: RunContext) -> AsyncIterator[RunEvent]: ...
```

DU01 loop 实现：调 `ModelGateway.stream` → `RuntimeEventMapper` 映射 → yield `RunEvent`。**Port 签名预留 `checkpoint_ref` 字段（DU01 不用）**，DU03 替换为 LangGraph adapter 不破上层。`RunContext` 含 run_id、attempt_id、agent_definition、locked manifest、model 配置。

### 6.3 Policy Gate

`Gate` 抽象基类：`check`/`validate` → `None | raises`。DU01 实现 `RunGate`（输入/manifest）和 `OutputGate`（schema）。Model/Tool Gate 是接口预留，DU02/DU03 新增子类，pipeline 结构现在立好。

### 6.4 契约测试

为 `ModelGateway` 与 `AgentRuntime` 各写一套契约测试。DU01 的 loop 实现跑契约测试；真 OpenAI/Anthropic adapter 走 live eval 标记，不进普通 CI（避免成本与不稳定）。

## 7. 状态机（DU01 子集）

显式 transitions 表，非法转换 raise。DU02/DU03 加行不破现有。

```text
ArtifactVersion: draft → pending → published
AgentRun:         queued → running → completed | failed
```

- 流式完成、Output Gate 通过后，draft 自动转 pending（待审批）。
- 审批发布：pending → published，单 SQLite 事务（定稿 §5.4：发布不调用模型/工具/文件写入）。
- superseded/rejected（DU02）、waiting_input/interrupted/cancelled（DU03）不在 DU01。

## 8. HTTP API（4 端点）

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/profile/runs` | 提交文本，创建 AgentRun(queued)，返回 run_id。Body: `{text, command_id}` |
| GET | `/api/profile/runs/{run_id}/events` | SSE 流，按 sequence 推 RunEvent，支持 `Last-Event-ID` 回放 |
| GET | `/api/profile/runs/{run_id}` | 查 run 状态 + 当前 pending artifact_version |
| POST | `/api/profile/artifact-versions/{id}/approve` | pending → published（单事务） |

错误统一走 `ErrorEnvelope`（定稿 §10）：code/category/retryable/safe_message/diagnostic_id/next_actions。前端按 category 呈现，不解析字符串。

SSE 契约（定稿 §7.2）：RunEvent 成功落库后才能发前端；支持 `Last-Event-ID` 按 sequence 回放；前端按 `run_id + sequence` 去重；断线不取消 run。

## 9. 前端（一个 Profile 页）

- 文本框粘贴资料 → 点「抽取」→ 创建 run。
- SSE 订阅，展示 streaming 三态（loading / streaming / done）。
- 流式完成后展示 Profile 草稿（facts 列表）。
- 「批准发布」按钮 → 调 approve → 展示 published 状态。
- SSE 断线重连用 `Last-Event-ID`。

技术栈继承 DU00：TanStack Query 管理服务端状态，`queryKey` 以 scope 开头（DU01 `["profile", run_id, ...]`），SSE 事件按 `run_id + sequence` 去重。

## 10. 明确不做（边界）

设置页、数据目录 / Blob、版本历史 / diff、superseded / rejected 审批 UI、Run Center、Model Gate 全量（预算/PII/fallback）、Tool Gate、AuditTrace 全量、checkpoint / resume、command_id 幂等、global/workspace scope（DU01 单隐式 workspace/thread）、Profile 完整结构化字段、视觉输入。全部 DU02–DU04。

## 11. 测试策略

- **Domain 单测**：状态机转换合法/非法、Profile schema 校验、Artifact 不可变（draft 内容落库后不可改）。
- **契约测试**：ModelGateway（chunk 序列、重试、错误分类）、AgentRuntime（event 序列、checkpoint 参数存在）。
- **集成测试**：SQLite 事务（发布原子性、draft 不可原地改）、SSE replay（`Last-Event-ID` 回放、sequence 去重）、Output Gate 拦截坏 schema → run failed。
- **Fake Model**：自动化测试用 `FakeModelGateway`（注入预定义 chunk 序列 + 模拟瞬时错误），不耗真 key。
- **前端测试**：Profile 页三态、批准发布交互、SSE 断线重连（mock SSE）。

## 12. 扩展点（为 DU02–DU04 留好）

- 4-Gate pipeline 结构现在立好，DU01 填 2 个，DU02/DU03 加 2 个——增量非重写。
- Artifact / AgentRun 状态机 transitions 表可加行。
- `workspace_id` / `thread_id` 字段已留，DU03 只改约束。
- `AgentRuntime` Port 预留 `checkpoint_ref`，DU03 换 LangGraph adapter 不破上层。
- `evidence_ref` 字段已留，DU02 接 Blob 时填。
- `ModelGateway` Port 稳定，DU02 加 Model Gate（预算/PII）在 Gateway 外包一层，不改 adapter。
