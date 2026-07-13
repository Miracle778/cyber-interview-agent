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

## Learning 深度审阅

- R1.2 为 1794 词、R1.3 为 1603 词；R1.4 仅 728 词、R1.6 仅 623 词、Runtime Middleware 仅 415 词。
- R1.5 虽只有 240 行但有 1513 词，说明行数不能代表掌握深度。
- 当前门禁只校验七个文件和少量标题，7 行 architecture 仍能通过；模板中的“不得比上一阶段退化”没有机器约束。
- 后续采用 foundation/stateful/integration/experience 风险档案；机器校验结构化证据，人工只做一次同档案深度复核，不设置总字数门槛。
- 设置页正式计划要求 `settings-experience-redesign` 七件套，但主仓库本地 learning 目录尚未同步该掌握包。
- 门禁 TDD 从 8 项扩展到 15 项；固定档案声明、两个风险驱动、五个架构章节、档案化链路/问题数量和故障证据均有失败用例。

## 约束

- R1.6 已合入 `main@eaf5edf`；后续产品阶段继续使用独立分支/worktree。
- 不修改或提交 `docs/my_idea.md`。
- `docs/verification/` 和 `docs/learning/` 本地保留，合并后显式同步。
- 当前切片由 Codex 负责到底，不委派。

## Pre-R2 体验稳定化发现

- source 文件与 metadata 现在由 Workspace 范围服务共同管理；跨文件系统/SQLite 的后续失败采用显式补偿清理。
- source 与 draft 保持独立生命周期，通过可空 draft ID 关联；列表 API 只返回安全相对路径。
- Markdown 阅读态禁用 raw HTML，并只隐藏有闭合分隔符的 YAML frontmatter；编辑态保留完整原文。
- 非诊断 ActionCenter 在无 watch/action/error 时从首帧隐藏；watch、超时重试和 pending action 是显式可见状态。
- 复习页只增加语义区域和响应式层级，没有新增 API、状态转换或 R2 行为。
- roadmap 的 context compression/token usage 仍未实现，下一切片必须单独补齐。

## 设置页体验重构发现

- 当前设置页把 Workspace、Provider、模型绑定、Runtime、安全和 HITL 完整卡片纵向平铺，没有任务域或配置顺序。
- 设置页现有业务组件边界可保留；主要改动是页面导航、概览摘要、Provider 创建表单和诊断详情的渐进披露。
- ProviderManager 与 ModelBindings 使用本地 effect 状态；概览摘要使用稳定 TanStack Query key，并在保存成功后显式失效，避免建立第二套业务状态。
- 诊断历史没有可复用的统一成功摘要，概览只承诺“待检查”或 pending action 数量，不虚构最近成功状态。
- 本切片没有后端改动，最终不重复执行后端全量回归。

## Runtime Middleware 架构决策

- Middleware 是跨 R1-R8 的全局架构规则，权威定义迁移到产品总设计；R1 shared foundation 只保留该阶段的落地引用与兼容边界。
- 现有 HITL 使用 LangGraph `interrupt`/`Command(resume=...)`，但 action 持久化、审批和恢复由项目服务编排，尚无 middleware 抽象。
- 后续保留 HITL repository、receipt、handler 和领域幂等语义，在其上增加 middleware/adapter；知识发布仍保持显式 Graph/Service 状态机。
- token/context 用量、context budget、压缩触发、会话标题总结、tracing、脱敏和普通工具审批属于跨 Agent 横切能力，优先实现为可组合 middleware。
- 待办事项由 post-processing middleware 提取候选，再交 Todo Service 去重和持久化；无限循环由 guard middleware 综合路径、工具参数、错误、无进展、token、时间与费用判断。
- Pipeline 固定为 Guard → Invocation → Post-processing；首批实现 token/context、压缩、标题、循环检测和 HITL adapter，待办候选只定义契约。
- 阶段调整为 Pre-R2 实现五项核心能力并只定义 TodoCandidate；R2 用多题复习验证，R4 才实现 Todo Service 和真实候选提取，R5/R6 分别扩展行动项与多 Agent 治理。
- 官方 `AgentMiddleware` 由 `create_agent` 组合，而当前业务使用手写 StateGraph；Middleware 1.0 采用统一 policy/repository 下的 RuntimeMiddleware pipeline + LangChain adapter，避免假设官方 hook 会自动作用于现有 Graph。
- 可观测性采用 OpenTelemetry `ObservabilitySink` + 本机 Langfuse v3：Task 1 建抽象/Compose，Task 2 在真实模型调试前接 OTLP，Task 3/4 补 middleware、工具、HITL、发布和重启关联；默认 metadata-only、后端故障 fail-open。
- 领域状态转换、Vault/索引副作用、长事务及补偿流程不放入通用 middleware；新增能力必须先判定归属并声明顺序、持久化、失败降级和幂等边界。
- Pipeline 扩展契约增加稳定 middleware ID、单项关闭、层内顺序区间和冲突校验；默认透传基类允许扩展只覆盖需要的 hook。
- 本机 Langfuse smoke test 发现 Alpine `localhost` 解析到 `::1` 会误判 ClickHouse unhealthy；健康检查固定使用 `127.0.0.1`。
- LangGraph checkpointer 在节点执行期间持有 SQLite 写事务；usage/summary 必须先缓冲并在退出 checkpointer 后幂等 flush，不能在 model hook 内直接写库。
- Langfuse OTLP 实测可把 `gen_ai.*` model spans 识别为 GENERATION；metadata-only 时 input/output 为空，测试 Provider usage 明确标记 estimated。
- Playwright 管理的 webServer 可能被强制终止而不触发 shutdown；开发观测启用时每个 run segment 与 post-processing 后执行受限 flush，默认 No-op 无额外成本。
- Trace segment 是诊断数据，start/finish 遇到 SQLite 锁必须 rollback 并 fail-open，不能把成功业务 run 改成 failed。

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
