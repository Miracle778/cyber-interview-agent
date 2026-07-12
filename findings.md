# Cyber Interview Agent 当前发现

## R1.5 审阅结论

- 后端 234 项、前端 56 项测试以及 TypeScript/build 当前通过。
- 请求发布后只刷新 `knowledge-drafts`，未刷新 `pending-actions`，同页 ActionCenter 不能稳定出现新 action。
- ActionCenter 决定后未刷新草稿和 publication 结果。
- 生产代码未写入草稿 `review_pending` / `rejected`，现有前端测试通过 mock 构造了不存在的状态。
- DraftReview 把 artifacts `contentPath` 错当成 Vault 发布路径。
- publication journal 已保存 target path/state，但缺少面向前端的查询资源；`index_stale` 无法展示。
- external-document conflict 发生在批准 delivery，而非 publish-request；现有前端测试覆盖了错误端点。
- 浏览器验收尚未执行，但 learning 文档错误声称已覆盖。
- RunManager 偶发 SQLite 写锁争用为 R1.2/R1.3 遗留风险；本轮不扩大 R1.5 范围，最终验收中持续观察。

## 提速发现

- 原启动入口 `task_plan/findings/progress` 共 1,279 行，且每次恢复还要读取 332 行工作流和当前 spec/plan，是主要固定 token 成本。
- R1.4/R1.5 大量时间集中在最终跨层 UI、浏览器、审阅和文档，而不是早期数据层任务。
- 每任务全量回归造成重复测试与日志；定向 TDD + 最终全量回归更合适。
- 计划中的 `superpowers:*` 是未安装模板残留，没有仓库执行实现；应删除强制声明。
- 当前未发现 skill 死循环；主要浪费来自宽范围读取、重复回归、环境故障和中途交接。

## 约束

- R1.6 已合入 `main@eaf5edf`；后续产品阶段继续使用独立分支/worktree。
- 不修改或提交 `docs/my_idea.md`。
- `docs/verification/` 和 `docs/learning/` 本地保留，合并后显式同步。
- 当前切片由 Codex 负责到底，不委派。

## R1.5 修正结果

- publish-request 成功后以 version/hash 把草稿推进为 `review_pending`；启动后状态推进失败会取消 run。
- rejection delivery 把绑定的精确草稿版本推进为 `rejected`；批准仍由 publication service 推进为 `published`。
- 草稿 API 现在附带最新 publication 的 `state/targetPath/errorCode`，不再把 artifacts 路径当发布路径。
- KnowledgePage 用 publish run id 驱动 ActionCenter 获取对应 action，决定完成后统一刷新 drafts/actions。
- ActionCenter watch query key 使用 memo 保持稳定，避免 render 触发重复轮询。

## R1.6 启动发现

- Runtime 已保存 run model-binding snapshot，GraphDefinition 已声明 `required_model_roles`；R1.6 应复用，不新建第二套运行绑定状态。
- OpenAI/Anthropic adapter 当前只实现最小连接测试，业务结构化/流式调用需要窄 ChatModelGateway。
- 现有复习页仍调用 `/api/review/run` 与 `/api/review/reports/confirm`，是必须移除的 Runtime/HITL 绕过路径。
- 旧实施计划有 6 个任务，按新执行预算合并为 4 个纵向任务。
- RunManager SQLite 写锁风险单独跟踪，不混入 R1.6 业务范围，除非定向测试证明它阻塞新链路。
- knowledge.publish 节点恢复时会再次进入 request_action；副作用必须按 action.status 保持幂等。
- 新 worktree 安装依赖受 DNS 限制；复用 main 锁定的 venv/node_modules 避免了网络重试。
- action resource 不暴露 payload；Review 刷新所需 draftId/question/evaluation 放入安全 preview。
- 真实 OpenAI-compatible GLM 不支持默认 `json_schema` response format；adapter 必须显式使用兼容面更广的 function calling。
- 真实 OpenAI-compatible 结构化评价与 Anthropic-compatible 流式报告均已通过，不再有外部协议阻塞。
