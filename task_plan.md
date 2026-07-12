# Cyber Interview Agent 当前任务规划

## 产品目标

建设由复习、个人信息、岗位追踪、面试复盘和模拟面试等场景 Agent 组成的个人面试准备工作台。产品交付与用户学习保持双轨，学习不阻塞实现。

## 当前产品状态

| 阶段 | 状态 | 成熟度边界 |
|---|---|---|
| R0 | 可人工验证 | 单题单轮技术切片 |
| R1.1-R1.4 | 可人工验证并已合入 main | Provider、Runtime、工具安全、持久化 HITL |
| R1.5 | 修正与验收中 | 后端发布机制已实现；前端闭环、发布结果和浏览器证据待补 |
| R1.6 | 待开始 | 单题复习迁移到共享 Runtime |
| R2-R8 | 待开始 | 见正式产品路线 |

## 当前任务：R1.5 收口与流程提速

1. **协作流程优化（完成）**
   - 压缩启动上下文并归档历史。
   - 明确定向测试、全量回归、浏览器和文档预算。
   - 删除未安装 `superpowers:*` skill 的强制模板文案。
   - 加强阶段文档证据一致性门禁。
2. **R1.5 产品修正（完成）**
   - 同步 pending action 与 knowledge draft 查询。
   - 实现 `review_pending` / `rejected` 真实状态转换。
   - 暴露 publication target path、state 和 index-stale。
   - 增加真实发布闭环测试。
3. **R1.5 最终验收（进行中）**
   - 一次最终全量后端/前端/type/build。
   - 一次浏览器与重启验收。
   - 修正文档、运行门禁、独立静态复核。
4. **合并收尾（待开始）**
   - 合入 main。
   - 同步 verification/learning 到主仓库。

## 执行预算

- 启动必读入口合计不超过 400 行。
- 单次工具输出默认不超过 4,000 tokens。
- 针对性 TDD；本次剩余工作只做一次最终全量回归。
- 完整浏览器验收一次；失败只重跑受影响场景。
- 中途 Agent 交接为 0；不创建 subagent。
- 相同失败最多重复一次，第二次相同失败转根因诊断。
- 每个纵向任务 handoff 摘要不超过 10 行。

## 所有权状态

- 已掌握：尚未由用户验收。
- 待掌握：R1.1-R1.5 架构和代码链路。
- 待实践：发布请求到 Vault 写入追踪、SQLite 并发诊断。
- 学习练习不阻塞 R1.5 修正、合并或 R1.6。

## 权威资料

- 工作流：`docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- 产品路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- 当前设计：`docs/superpowers/specs/2026-07-12-r1-5-knowledge-publication-design-review.md`
- 当前实施：`docs/superpowers/plans/2026-07-10-r1-5-knowledge-publication.md`
- 历史归档：`docs/superpowers/history/2026-07-12-pre-context-optimization/`
