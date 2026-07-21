# ADR：长时间 Agent 任务分离 Execution、领域任务与 Work Item

- 状态：Accepted
- 决定日期：2026-07-22
- 首次落地：R2 题目整理
- 后续适用：R3 `profile.ingest` 及其他有持久进度的长任务
- 关联设计：`../specs/2026-07-22-r2-curation-long-task-control-and-performance-design.md`
- 补充决定：`2026-07-16-unified-cancellable-execution-runtime.md`
- 部分取代：`2026-07-21-progressive-question-curation-pipeline.md` 中“每 6 个 section 一个单元”和“每次只推进一个 work item”的执行策略

## 背景

统一 Execution Runtime 已能取消一次运行，渐进式题目整理也已能持久化 completed work item。但真实长材料表明，一次 Execution 的终态不足以表达“任务暂停后继续”“服务中断后恢复”“用户永久终止”和“多次尝试累计进度”。过细分块与串行 Graph 还使约 4 万字材料产生近 180 次串行模型调用。

如果把 Batch 等同于 Execution，暂停后只能重建任务或滥用 failed；如果把所有状态放入通用 Runtime，又会让 Runtime 吸收题目、材料和候选等领域规则。

## 候选方案

### 方案 A：继续把 Execution 作为完整任务

改动小，但无法清晰区分暂停、终止、失败和进程中断；恢复历史、累计耗时和 completed work item 归属会继续依赖临时推断。

### 方案 B：引入通用工作流引擎或任务队列

可以提供调度与持久 worker，但当前单机产品不需要分布式队列；仍然不能替代领域幂等、候选状态和 Evidence/Proposal 边界。

### 方案 C：Execution、领域任务、Work Item 三层分离

采用。Execution 负责一次运行尝试，领域聚合负责用户可见长任务，work item 负责最小恢复断点。通用 Runtime 保持运行职责，领域服务保持业务状态所有权。

## 决定

1. Execution 是一次运行尝试，不是长任务本身；恢复创建新 Execution。
2. 领域聚合拥有长任务状态。R2 使用 Question Batch，R3 使用 MaterialVersion/领域处理状态。
3. Work Item 或领域 Receipt 是最小恢复断点；completed 输出不可变，恢复不重放。
4. 暂停是可恢复终态，终止是不可恢复终态；failed 和 interrupted 允许显式恢复。
5. 控制意图先持久化，再取消本地 task；启动时根据控制意图、Execution 和 work item 对账。
6. 同一领域任务最多一个活动 Execution；控制和恢复使用幂等键与 expected version。
7. Provider 调用只保证至少一次，领域结果通过摘要、状态条件和不可变 receipt 实现精确一次提交。
8. 并发属于确定性调度器。模型不决定并发数、work item、重试或停止条件。
9. R2 使用结构感知混合 Map–Reduce：明确题目规则优先，未覆盖文本才进入 LLM discovery；discovery/enrichment 默认最多并发 3。
10. 不立即创建通用 `LongTask` 表或领域无关状态机框架。第三个领域出现相同需求后再评估抽象。

## 用户语义

| 操作/事件 | Execution | 领域任务 | 是否可继续 |
|---|---|---|---|
| 暂停 | cancelled | paused | 是 |
| Provider 失败 | failed | failed | 是 |
| 服务退出 | interrupted | interrupted | 是 |
| 用户终止 | cancelled | terminated | 否 |
| 恢复 | 新 running Execution | generating/running | — |
| 全部完成 | completed | review_pending/ready | 否需恢复 |

取消与自然完成竞争时，数据库条件更新决定唯一终态。已原子提交的 completed work item 不回滚；尚未提交的当前调用在恢复时允许重发。

## 结果

正向结果：

- 页面状态与真实领域进度一致；
- 暂停、失败和进程中断可以复用同一恢复协议；
- 终止不会被误显示为可重试失败；
- 多次 Execution 可以计算累计有效耗时并保留审计；
- R2 与 R3 共享语义而不共享领域表；
- 有界并发不破坏单元级幂等和恢复。

代价与风险：

- Batch/MaterialVersion 与 Execution 需要额外关联和启动对账；
- 状态组合、幂等控制和竞争测试矩阵扩大；
- Provider best-effort cancel 可能仍产生 token 费用；
- 并发会触发 Provider 限流，需要遵守 `Retry-After` 并动态降级；
- 至少一次 Provider 调用不能避免网络不确定情况下的重复计费。

## 重新评估条件

- 产品迁移到多进程或分布式 worker；
- 三个以上领域重复实现同一任务 adapter；
- Provider 提供可靠的原生可恢复批处理和幂等请求；
- 并发限流或成本数据证明默认 3 不适合主要 Provider；
- 用户需要跨设备后台任务、优先级队列或计划调度。
