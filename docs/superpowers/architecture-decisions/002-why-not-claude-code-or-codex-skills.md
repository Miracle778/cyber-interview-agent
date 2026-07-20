# ADR-002: 为什么不直接用 Claude Code / Codex + Skills

## 状态

已确认（2026-07-14 讨论）

## 背景

Claude Code、Codex 等通用 AI 编码工具支持自定义 skill、会话恢复、文件读写、代码执行。质疑：面试题库整理、模拟面试等功能用这些工具 + skill 也能实现，为什么要单独建项目？

本文档按最终形态（docs/my_idea.md + product roadmap 的完整功能）进行对比。

## 决策

不使用通用 AI 工具 + skill 替代本项目，而是构建领域专属的面试准备工作台。

## 核心区别：恢复的是什么

Claude Code / Codex 的会话**是可恢复的**（`--resume` / `--continue`）。但会话恢复的是**对话历史**（chat log），不是**执行状态**。这两者完全不同：

| | Claude Code 会话恢复 | 本项目的状态恢复 |
|---|---|---|
| 恢复的是什么 | 对话历史（聊天记录） | 执行状态（graph checkpoint + 产品投影 + pending action + 事件 cursor） |
| 多步流程的位置 | 不在对话里--得靠人记或翻文件 | checkpoint 自动记录到节点边界，重启从断点续跑 |
| 崩溃时在途操作 | 操作丢失，resume 后需人工重新发起 | reconciliation 自动重试 pending action，publication journal 保证幂等 |
| 跨会话聚合 | 不能--每个会话独立，无法跨会话查询 | 全局掌握度从最近三份报告聚合，任何会话都能查 |
| HITL 待审状态 | 不在对话里--审到一半崩了，状态可能丢 | pending action + receipt 持久化，重启后继续审 |
| 知识库版本 | 文件覆盖，无版本/hash/冲突检测 | publication journal + 版本/hash + 外部修改检测 |

**一句话**：Claude Code 恢复的是"我们聊到哪了"，我们恢复的是"系统执行到哪了、哪些操作在途、哪些待审、知识库什么版本"。

## 理由

### 1. 状态管理：对话历史 ≠ 领域状态

面试准备是一个持续数周到数月的过程，涉及结构化领域实体：题库（catalog）、复习轮次（round）、答题尝试（attempt）、掌握度（mastery）、报告（report）、知识发布（publication）。这些实体有：

- **状态机**：draft -> review_pending -> published；waiting_for_input -> running -> completed。
- **版本与一致性**：draft version + content hash，乐观并发，外部修改检测。
- **跨会话聚合**：全局掌握度 = 最近三份已确认报告的聚合，驱动下一轮选题。
- **幂等与恢复**：HITL receipt + publication journal，崩溃后 reconciliation 自动重试。

Claude Code 的会话是对话上下文，不是领域模型。可以在对话里"聊"面试题，但"第 3 轮复习的第 5 题评价是什么"、"缓存的掌握度最近三次变化趋势"、"这道题的 draft 版本和已发布版本 hash 是否一致"--这些查询需要结构化数据，不是翻聊天记录能做的。

### 2. 自动化：人驱动 ≠ 系统编排

| | Claude Code + Skill | 本项目 |
|---|---|---|
| 触发方式 | 人发起 skill，工具执行，返回结果 | 系统编排：掌握度驱动选题、整理完自动进题库、发布自动建索引 |
| 执行模式 | 同步交互（人等结果） | 异步后台（启动后返回 202，SSE 推进度） |
| 多 Agent 协调 | 单会话单 Agent，多 Agent 需开多个会话手动衔接 | 多 Agent 共享知识库，流转有协议（整理 -> 审核 -> active catalog -> 复习 -> mastery -> 模拟面试） |
| 上下文管理 | 会话 compaction（截断） | 按角色隔离 thread + 官方 SummarizationMiddleware（结构化压缩） |

Claude Code 的自动化是"人发指令，工具执行"。我们的是"系统编排，人只做关键决策（HITL）"。面试准备需要后者--用户不想每天手动想"今天复习什么"，系统应按掌握度自动安排。

### 3. 多 Agent 协调 + 共享知识库

最终形态有 5+ 个 Agent（整理、复习、个人信息、岗位追踪、面试复盘、模拟面试），共享一个知识库，有明确流转关系：

```
整理 Agent -> 题库（confirmed）
                    ↓
复习 Agent -> 掌握度（mastery）
                    ↓
模拟面试 Agent -> 复盘 Agent -> 知识库（新经验）
                    ↓
岗位 Agent -> JD 差距分析 -> 复习建议
```

Claude Code 是单会话单 Agent。可以开多个会话，但：
- 没有**共享状态**（知识库、掌握度跨会话一致）。
- 没有**流转协议**（整理完自动进题库，题库变自动影响复习选题）。
- 没有**一致性保证**（只有 confirmed 知识进 active scope，draft 不污染）。

在 Claude Code 里实现这些，要用文件做 Agent 间通信--那就是重新发明我们的知识发布协议、active scope、publication journal。

### 4. 产品级 UX

Claude Code 的 UX 是终端聊天。面试准备需要结构化 UI：

- 题库工作台：三栏（会话列表/对话/运行状态），候选题卡片，搜索/筛选/Topic/难度。
- 复习工作台：轮次历史/答题对话/评价卡/进度条/掌握度趋势。
- 知识库管理：文档列表、Markdown 渲染/编辑切换、来源证据、关系图。
- 模拟面试：多轮对话、暂停恢复、表现汇总。
- 移动端（R8）：微信/飞书碎片化复习。

这些是**结构化交互界面**，不是聊天界面能替代的。在终端里看一道题的参考答案、关键点、掌握度、来源证据--体验远不如设计好的卡片界面。

### 5. 恢复与可靠性

面试准备持续数周到数月，可靠性是基本要求：

- **崩溃恢复**：我们的 checkpoint + reconciliation + publication journal 幂等。Claude Code 的会话可 resume，但崩溃时在途的操作（如"正在评价第 3 题回答"）没有 checkpoint，需人工重新发起。
- **HITL 持久化**：我们的 pending action + receipt 持久化，重启后继续审。Claude Code 的审批状态在对话上下文里，崩溃时可能丢失未持久化的审批。
- **事件重放**：我们的 SSE cursor + 事件表，断线重连补发。Claude Code 没有事件日志，断了就断了。

### 6. 多模型 + 成本效率

本项目按用途绑定不同模型（question_generation / answer_evaluation / report_summarization / agent_chat），可用便宜模型做简单任务、强模型做复杂任务。

Claude Code 用单一模型干所有事。面试准备涉及大量题目生成和评价（R2 验收：10 题用 102094 tokens），全用强模型成本高。按角色分配模型能省 60-80% 成本。

### 7. 数据所有权 + 可移植性

- 本项目：用户数据在本地（Workspace + Obsidian-compatible Vault），Markdown + frontmatter，可被其他工具读取，不锁定。
- Claude Code：数据在会话上下文或 Anthropic 云端，格式非结构化，工具绑定。

面试题库、掌握度历史、复习报告是用户的核心资产，必须在本地、可导出、可备份、不被工具绑定。

### 8. 领域级安全

本项目有领域级安全：
- Workspace 路径沙箱（Agent 不能读写 workspace 外）。
- 工具 allowlist + scope（每个 Agent 只用授权工具）。
- HITL 审批（修改资料/发布知识要人确认）。
- 脱敏审计（事件/日志不泄露 secret）。

Claude Code 有通用安全（权限、沙箱），但没有领域级安全。skill-based 面试工具要自己建这套，否则 Agent 可能读到用户其他文件、随意修改、无审批地发布错误知识。

## 讲解口径

> 这个问题的本质是：通用工具能不能替代领域产品？
>
> 能用 Excel + 邮件做 CRM 吗？能。但 Salesforce 存在的原因不是"Excel 做不到"，而是 CRM 需要状态管理、流程编排、多角色协调、可靠性、UX--这些是产品价值，不是单个任务能不能完成的问题。
>
> Claude Code / Codex 是优秀的通用工具，会话可恢复、能写 skill、能读写文件。但面试准备是一个持续数周的流程，需要：
>
> 1. **结构化状态管理**：不是恢复对话历史，是恢复执行状态--graph checkpoint、pending action、publication journal、跨会话掌握度。对话历史不等于领域状态。
> 2. **系统编排**：多 Agent 共享知识库、掌握度驱动选题、后台异步执行 + SSE。不是人发指令工具执行，是系统编排人审批。
> 3. **产品级体验**：结构化 UI、移动端、数据所有权（本地 Obsidian Vault）。
>
> 如果用 Claude Code skill 实现这些，实际上是在重建我们的项目--只是建在 Claude Code 上面，还绑定了 Anthropic 的基础设施。

## 参考

- 产品路线：`docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md`
- 原始意图：`docs/my_idea.md`（本地，不提交）
- 收敛设计（多 Agent + 共享知识库 + 状态所有权）：`docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md`
- ADR-001（整理 Agent 不内置 web 搜索）：`docs/architecture-decisions/001-no-web-search-in-curation-agent.md`
