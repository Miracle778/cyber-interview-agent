# ADR：所有 Runtime Agent 写入本地 JSONL 诊断轨迹

- 状态：Accepted
- 决定日期：2026-07-21
- 适用阶段：R2 及后续所有使用统一 Runtime AgentFactory 的产品阶段
- 关联设计：`docs/superpowers/specs/2026-07-21-r2-progressive-question-curation-design.md`

## 背景

现有 Runtime SQLite 保存 Session、Execution、Event、usage、warning、Tool audit 和 LangGraph checkpoint，但这些记录有意只保存产品事实、安全投影或恢复状态。它们不能还原一次模型调用真正收到的 system/user/tool messages、结构化 schema、模型参数、原始 assistant/tool response 和 Provider 错误上下文。

题目整理在真实 GLM Provider 上出现 timeout 与 `400 InvalidParameter` 时，只能通过临时脚本重放片段。用户要求当前所有 Agent 的对话记录落盘为 JSONL，以便按 session/execution 直接排查，而不依赖远程 observability 服务。

完整消息可能包含上传文档、简历、回答和 Tool 结果，因此该决定同时建立本地敏感数据边界。

## 候选方案

### 方案 A：继续依赖产品 Event、checkpoint 和普通 logging

拒绝。产品 Event 必须保持安全、稳定和面向 UI；checkpoint 面向恢复且格式由 Graph 状态决定；普通文本日志无法可靠关联 invocation、保留结构化 message 或独立解析。把调试正文塞进任一现有渠道都会破坏其边界。

### 方案 B：只接入远程 Langfuse/OpenTelemetry

拒绝作为首版。远程服务需要额外配置、网络和隐私授权，无法保证故障发生时可用，也不满足用户要求的本地 JSONL。未来可以从同一安全事件模型派生远程 sink，但不能替代本地事实。

### 方案 C：Runtime 统一 Middleware + 每 Execution 一个本地 JSONL

采用。`AgentFactory` 自动注入 Trace Middleware，Execution service 记录生命周期，内部摘要调用显式复用 writer。文件按 session/run 隔离，追加写入，不改变产品数据库或 API。

## 决定

1. 所有通过统一 `AgentFactory` 创建的 Runtime Agent 都必须记录 `model.request/response/error` 和 `tool.request/response/error`；调用方不得选择性漏装。
2. 轨迹保存在 workspace 的 `.cyber-interview-agent/agent-traces/<session-id>/<run-id>.jsonl`，由 `.gitignore` 排除，不进入 knowledge vault。
3. 实际发送和收到的 Agent message、source 片段、Tool 参数/结果及 structured response 完整保存，不做内容长度截断；每个事件带 schema version、sequence、role/name 和 invocation ID。
4. API key、Authorization/header、secret ref、环境变量、SDK client 和凭据容器永不序列化。安全 serializer 使用字段白名单，禁止对未知对象调用任意 `repr`。
5. Trace 不投影到 SSE、timeline 或普通 API。首版仅本地文件可读，不上传远程服务，也不自动删除。
6. 写入使用安全 workspace path、symlink 防护、进程级锁和 append；请求在 Provider 调用前 flush，Execution 终态 fsync。
7. Trace 是 best-effort 诊断旁路。写盘失败产生稳定 Runtime warning，但不改变 Agent 的业务结果。
8. Provider 健康 ping 等没有产品 Session/Execution 的调用不属于 Agent 对话，不写入该轨迹；内部 Agent 摘要模型调用属于轨迹范围。

## 结果

正向结果：

- 可按 session/run 直接还原某个 Agent 的完整 Provider 上下文和调用顺序；
- timeout、400、结构化输出失败和 Tool 循环不再需要临时复刻输入；
- JSONL 可用 `rg`、`jq` 或后续专用 viewer 逐行处理；
- 产品 Event、checkpoint、领域数据库和远程观测继续保持各自边界。

代价与风险：

- 本地文件会包含用户原文和回答，具有与 source/profile artifact 相同或更高的敏感级别；
- 不自动清理意味着长期运行会占用磁盘，需要后续基于真实用量设计保留策略；
- 完整 request 会重复部分历史消息，换取故障可重放性和直接可读性；
- 新增 serializer、并发 append、Trace Middleware 和摘要调用接线，需要专门的泄密与失败旁路测试。

## 2026-07-22 时间语义补充

用户直接查看 JSONL 时需要把 UTC 手工换算为北京时间。UTC 仍是跨机器排序和事件关联的权威时间，但新写入行升级 Trace schema，并同时记录：

```json
{
  "schema_version": 2,
  "timestamp": "2026-07-21T16:30:00.123+00:00",
  "local_timestamp": "2026-07-22T00:30:00.123+08:00",
  "timezone": "Asia/Shanghai"
}
```

- `timestamp` 保持 UTC 权威语义；
- `local_timestamp` 是北京时间可读投影，`timezone` 明确转换来源；
- 旧 schema v1 行继续可读，不重写已有诊断文件；
- latency/duration 使用单调时钟测量，不能通过两个本地时间字符串相减。

## 重新评估条件

- 本地轨迹占用达到需要自动清理或压缩的规模；
- 用户需要在 UI 中按 execution 下载、查看或主动删除轨迹；
- 多进程 Runtime 使进程级锁无法保证单文件顺序；
- 需要将同一安全事件模型发送到用户明确配置的远程 observability sink。
