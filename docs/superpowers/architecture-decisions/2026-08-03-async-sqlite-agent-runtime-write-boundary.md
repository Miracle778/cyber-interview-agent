# ADR：异步 Agent 运行时的 SQLite 写入边界与诊断降级

- 状态：Accepted
- 决定日期：2026-08-03
- 适用范围：所有通过 `ProductEventStream` 发布运行事件、通过 Agent Trace 记录模型调用的 Agent
- 关联决定：`2026-07-29-agent-trace-ledger-and-evaluation-boundaries.md`

## 背景

一次复盘讨论中，模型已经完成首轮调用并提出多项只读 Tool 请求，随后任务以 `OperationalError: database is locked` 失败。运行中心能看到 `model.response` 和部分 Tool 事件，却看不到对应的 `model.request`。

调查确认这是两个相互独立、但同时暴露在同一次运行中的运行时边界问题：

1. Tool 审计使用异步 SQLite 连接和短写事务；产品事件发布却在异步事件循环中直接执行同步 SQLite 写入。同步写等待锁时会阻塞事件循环，而持锁的异步任务又需要事件循环继续执行才能提交，形成锁等待放大甚至近似死锁。
2. Trace 序列化把 LangChain Tool 当作普通 Pydantic Model 做 JSON dump。真实 Tool 的参数 Schema 含 Python 类型对象，序列化异常被 Trace 的 fail-open 边界吞掉，因此模型仍会执行，但整条 `model.request` 丢失。

WAL 和 `busy_timeout` 已经启用，但它们只能改善正常的短暂竞争，不能修复“同步等待阻塞了锁持有者所在事件循环”的调度错误；Trace 的 fail-open 也只能保护业务调用，不能替代一个永不抛错的诊断序列化器。

## 目标

- 同步 SQLite 写入不能阻塞 Agent 异步事件循环；
- 保留本地优先、单文件 SQLite 的部署方式；
- 不通过无限增加锁超时掩盖调度错误；
- 真实 Tool 无论包含什么内部 Python 对象，`model.request` 都必须可记录；
- Trace 继续遵守最小披露和密钥清理，不使用任意对象 `repr`；
- 用可复现测试验证事件循环活性和请求/响应 Trace 配对。

## 候选方案与 Tradeoff

### 方案 A：只增大 SQLite `busy_timeout`

否决为完整方案。它对正常的短暂单写者竞争有效，但在同步调用已经阻塞事件循环时，只会让界面卡得更久；持锁协程仍得不到调度。超时保留为最后一道瞬时竞争保护，不承担并发正确性。

### 方案 B：给所有写操作增加一个全局异步锁

暂不采用。单进程内它可以串行化写入，却无法覆盖其他进程，也不能自动修复锁内执行同步 I/O 的问题。全局锁还会把互不相关的 Agent 事件、Tool 审计和业务写入都绑定在同一排队点。

### 方案 C：把运行时数据库立即迁移到 PostgreSQL

否决。PostgreSQL 能提供更强并发，但会破坏当前个人工作台“下载即可运行、数据随工作区携带”的部署边界，并引入服务运维、迁移和凭据管理成本。当前真实负载尚不需要为吞吐量放弃本地 SQLite。

### 方案 D：按事件、审计、Checkpoint 拆分多个 SQLite 文件

暂不采用。拆库可减少写锁竞争，却引入跨库生命周期、备份、清理和诊断关联复杂度，也不能修复同步 I/O 阻塞事件循环这一根因。只有持续并发数据证明单库写吞吐成为主要瓶颈时才重新评估。

### 方案 E：同步仓储调用移出事件循环 + Trace 使用安全契约投影

采用。产品事件仍复用现有同步 Repository 和事务语义，但通过线程桥接执行；SQLite 锁等待发生在工作线程，不再阻塞持锁协程。Trace 不序列化 Tool 内部实现，只记录公开、可审计的工具契约。

## 决定

### 1. 异步事件发布不直接执行同步 SQLite

`ProductEventStream.publish` 通过 `asyncio.to_thread` 调用同步 `append_event`。现有线程本地连接为工作线程提供独立 SQLite connection；锁异常仍回到协程，由原有的有界退避重试处理。

边界含义是：

- 锁等待不能占用事件循环线程；
- 写事务必须保持短小，事务持有期间不得等待网络或其他协程；
- WAL 和 5 秒 `busy_timeout` 是安全网，不是并发协调机制；
- SQLite 的单写者上限仍然存在，线程桥接不等于提高数据库写吞吐。

### 2. Agent Trace 序列化必须是总函数

Trace 对 LangChain `BaseTool` 只保存：

- `name`；
- `description`；
- JSON-safe 的参数 Schema 属性；
- `return_direct`。

不保存回调、闭包、Repository、Pydantic Model 类或其他内部实现。普通 Pydantic Model 优先做 JSON dump；若 Provider 或框架对象不支持 JSON 序列化，再尝试 Python dump，仍失败则保存稳定的 `type + unserializable` 标记。任一局部字段不可序列化都不能让整条模型请求消失。

密钥字段清理规则和“不调用任意 `repr`”约束保持不变。

### 3. 用真实对象验证，而不是只测简化替身

新增两类回归：

- 使用真实复盘 Tool 集合经过 `AgentTraceMiddleware`，断言 `model.request` 与 `model.response` 同时存在，且 Tool 名称完整；
- 用会阻塞的同步 Repository 模拟 SQLite 锁等待，断言等待期间异步 heartbeat 仍能运行。

这两项分别保护“诊断不能静默丢请求”和“数据库等待不能冻结事件循环”。

## 结果

正向结果：

- 多 Tool 并发时，产品事件写锁等待不再阻塞 Tool 审计协程提交；
- 锁仍可能发生，但会表现为有界排队/重试，而不是事件循环互相等待；
- `model.request` 能记录真实 Tool 的公开合同，运行中心可核对模型为何发起 Tool 调用；
- 业务调用继续对诊断失败 fail-open，局部不可序列化值不会扩大成任务失败；
- 保持本地 SQLite 和现有数据结构，不需要迁移用户数据。

代价与风险：

- 每次产品事件写入增加一次线程调度；对当前低频控制事件可接受；
- SQLite 仍是单写者，持续高并发写入时仍会排队；
- Tool Trace 是公开合同投影，不是 Tool 对象的完整快照；诊断内部闭包必须依靠代码版本而非 Trace 还原；
- 其他异步路径若直接调用同步 Repository，仍需逐步按同一原则审计，不能由本次局部修复自动覆盖。

## 重新评估条件

- 同一工作区出现持续的高并发 Agent，锁重试率或事件写入延迟显著上升；
- 线程桥接开销在性能数据中成为瓶颈；
- 多进程写入成为默认部署方式；
- 第三个运行时存储模块需要统一写入协调器；
- 产品需要服务端多用户共享数据库，此时重新评估 PostgreSQL；
- Trace 需要可版本化的完整 Tool Schema，届时为合同投影增加显式版本，而不是恢复任意对象序列化。

## 面试讲述口径

这次问题表面是 SQLite `database is locked`，但只调大超时会把错误变成长时间卡顿。真正的根因是同步 SQLite 写入发生在异步事件循环：它等待异步 Tool 审计持有的锁，同时又阻止持锁协程获得调度去提交。

最终我保留了本地 SQLite 的可部署性，把同步 Repository 写入桥接到工作线程，让事件循环继续推进短事务，并保留有界锁重试。与此同时，补齐 Trace 序列化的总函数边界：真实 Tool 只记录公开 Schema，不序列化内部 Python 对象。代价是一次线程切换和 SQLite 单写者上限仍在；收益是避免伪死锁、诊断请求不再静默丢失，也没有为了局部并发问题引入服务端数据库。
