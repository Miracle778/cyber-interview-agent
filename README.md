<div align="center">

# Cyber Interview Agent

### A local-first, evidence-driven multi-agent system for interview preparation

把零散资料、个人经历、目标岗位和训练反馈，持续转化为可追溯、可确认、可恢复的个人面试准备闭环。

`Python 3.12+` · `FastAPI` · `LangGraph` · `React 19` · `SQLite` · `SSE`

</div>

## 它解决什么问题

真正的面试准备通常散落在简历、项目文档、随手笔记、JD、聊天记录和一次次失败的回答里。通用对话工具可以帮你处理其中某个任务，但很少替你长期维护“哪些事实可信、哪些建议待确认、某个岗位还差什么、上次练到哪里、失败后怎样继续”。

Cyber Interview Agent 为此建立一组职责明确的领域 Agent：

- 题目整理与复习 Agent，把不规范笔记整理成候选题，经确认后进入题库，并根据练习结果持续更新掌握度；
- 个人画像 Agent，从简历和补充资料中形成工作经历、项目、技能与职业方向，同时保留来源和版本；
- 岗位与项目深挖 Agent，分析 JD、映射个人经历、识别差距，并把重点项目练成经得起追问的叙事和项目题；
- 规划中的复盘、模拟面试和 Research Agent，将继续消费同一套可信资产，而不是每次从一段临时 Prompt 重新认识你。

![多个 Agent 共同管理长期面试准备](assets/readme/01-interview-preparation-loop.png)

## 为什么不只是“再做一个通用 Agent”

[Codex](https://developers.openai.com/codex/use-cases) 和 [Claude Code](https://code.claude.com/docs/en/sub-agents) 已经能够完成广泛的编码、研究、自动化和多 Agent 任务；Codex 也支持插件与长期工作流，Claude Code 具备记忆、子 Agent 与文件检查点能力。这里的差异不是“谁更智能”，而是产品责任不同：

**Codex、Claude 是面向广泛任务的通用 Agent 工作环境；Cyber Interview Agent 把面试准备本身做成具有长期档案、明确流程和专属界面的领域产品。**

通用 Agent 可以帮助完成一项面试准备任务；本项目负责持续管理整套面试准备系统：个人事实如何进入画像、模型建议何时生效、岗位差距如何追踪、一次训练如何回流、一次失败执行如何恢复，都有稳定的产品语义。

## 真实产品界面

以下画面由 [`README Demo`](examples/readme-demo/) 虚构数据通过项目真实领域服务生成，不是静态 UI 稿，也不包含个人资料。

<table>
  <tr>
    <td width="50%"><img src="assets/readme/04-product-question-curation.jpg" alt="候选题整理工作台"></td>
    <td width="50%"><img src="assets/readme/05-product-profile.jpg" alt="个人画像工作台"></td>
  </tr>
  <tr>
    <td><strong>资料 → 候选题 → 人工确认</strong><br>完整保留来源、候选状态、Agent 会话和发布入口。</td>
    <td><strong>简历 → 结构化画像 → 岗位上下文</strong><br>经历、项目、技能与职业方向成为可复用的长期资产。</td>
  </tr>
</table>

<img src="assets/readme/06-product-agent-runtime.jpg" alt="项目深挖 Agent 会话与运行状态">

<p align="center"><strong>项目深挖 Agent：</strong>对话、当前阶段、参考范围、草稿、耗时与控制动作处于同一工作台。</p>

## 什么让它成为一个 Agent 项目

这里的 Agent 不等同于“调用一次大模型并展示文字”。系统包含完整的 Agentic Application 运行边界：

1. **目标与状态**：领域 Graph 管理多步骤任务、等待输入、暂停、终止和恢复。
2. **上下文与记忆**：`ContextAssembler` 按用途、资源范围和预算装配资料；长会话支持摘要压缩，领域正文留在 repository，以稳定引用按需读取。
3. **工具与权限**：已知输入的任务不增加无意义的工具循环；只有探索任务获得最小只读 Tool，并由 workspace、scope、次数和 token 预算约束。
4. **可恢复执行**：`Session / Message / Execution / Event` 分离。模型失败或用户停止后，重试创建新的 Execution，而不是复制一条用户消息污染上下文。
5. **人机协作**：模型输出 proposal；正式画像、题目和知识发布必须经过证据校验、版本检查、HITL 确认和幂等回执。
6. **多模型运行时**：OpenAI、Anthropic 等 Provider 通过统一 binding 接入，角色可以独立选择模型与推理强度。

![受控的混合 Agent 架构与边界](assets/readme/02-hybrid-agent-architecture.png)

这是一种 **Hybrid Agentic Application**：确定性路径由代码和领域 Graph 控制，模型负责语义理解、评估、追问和生成。它并不追求把每个功能都改成自由 ReAct。Anthropic 的 [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)、OpenAI Agents SDK 的 [Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/) 与 LangGraph 的 [Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) 都强调根据可预测性和任务开放程度选择工作流或 Agent；本项目把这一原则落实到了写权限、恢复和长期资产边界。

## Agent Runtime：让长任务真的可以继续

题目整理、简历解析和岗位分析不适合被当作一次性的 HTTP 请求。系统把用户语义和运行尝试分开持久化，并用 SQLite checkpoint、领域工作单元与 SSE 事件流支持：

- 处理中实时进度、耗时、token 与上下文状态；
- 暂停、终止、失败重试和进程重启后恢复；
- 已完成工作单元跳过，写入通过版本与幂等回执防止重复；
- 失败消息可重试、替换或放弃，只有有效语义进入后续上下文；
- 大材料不直接塞进 Agent state，原文与证据按领域版本留存。

![一次失败为什么不必从头再来的可恢复 Agent Runtime](assets/readme/03-agent-runtime-and-roadmap.png)

## 产品路线

项目能力围绕可信资产、岗位训练和面试反馈逐步扩展：

| 状态 | 能力 | 作用与产出 |
|---|---|---|
| **已具备** | Agent Runtime 与可信知识基础 | 工作区隔离、知识 Vault、版本、HITL、checkpoint、事件流和上下文装配，为所有领域 Agent 提供共同底座。 |
| **已具备** | 题目整理与复习 | 从杂乱材料生成候选题，人工确认后发布；支持轮次练习、追问、评价、掌握度和深入讨论。 |
| **已具备** | 可信个人画像 | 上传 Markdown、PDF、DOCX 简历，生成待确认画像；管理经历、项目、技能、来源、版本和画像助手会话。 |
| **建设中** | 求职目标与项目训练 | 解析 JD、确认岗位要求、映射画像、选择重点项目、项目深挖并沉淀岗位专属项目题。 |
| **规划中** | 面试复盘 Agent | 导入笔记或转录，提取问题、回答和追问，评估表现，并生成待确认的题库、项目叙事和画像变更。 |
| **规划中** | 模拟面试 Agent | 支持技术、项目与 HR 场景；按预算自适应追问，分离面试官与评估者角色，产出可复用报告。 |
| **规划中** | 受控面试情报 Research Agent | 用户明确授权后执行 `Plan → Search → Read → Cross-check → Synthesize`；保留来源 URL、时间与置信度，只生成待确认情报，不直接污染题库和画像。 |
| **规划中** | 本地产品化与外部入口 | 语义检索、关系视图、Obsidian 冲突同步、评测与 tracing、导出备份，以及微信/飞书中的碎片输入与审核。 |

## 快速开始

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/) 和 Node.js / pnpm。

```bash
git clone https://github.com/Miracle778/cyber-interview-agent.git
cd cyber-interview-agent

# Terminal 1
cd backend
uv sync
uv run fastapi dev app/main.py

# Terminal 2
cd frontend
pnpm install
pnpm dev
```

打开 `http://127.0.0.1:5173`，先在「设置」中创建工作区、配置 Provider 和模型绑定，再导入第一份资料。

<details>
<summary><strong>生成与查看 README Demo</strong></summary>

演示人物、公司、项目、指标与 JD 全部为虚构内容。脚本仅允许重置带有专用 marker 的 Demo 目录。

```bash
cd backend
uv run python ../scripts/seed_readme_demo.py \
  --workspace-root /private/tmp/cyber-interview-agent-readme-demo \
  --app-data-dir /private/tmp/cyber-interview-agent-readme-app \
  --reset --register

CYBER_INTERVIEW_AGENT_DATA_DIR=/private/tmp/cyber-interview-agent-readme-app \
  uv run fastapi dev app/main.py
```

另开终端运行 `pnpm --dir frontend dev`。种子脚本默认使用确定性 fallback，不需要真实模型，也不会接触你的常用 workspace。

</details>

## 技术栈与数据边界

- **Backend**：FastAPI、Pydantic、LangGraph、LangChain、SQLite / aiosqlite、OpenTelemetry。
- **Frontend**：React 19、TypeScript、Vite、TanStack Query。
- **Storage**：本地 workspace、Markdown Vault、运行库与 checkpoint；长期领域事实不以聊天记录作为唯一来源。
- **Security**：API Key 不进入前端持久化、Vault 或业务日志；模型只接收当前任务所需的有界上下文。

“本地优先”不等于“离线推理”：文件、索引、状态和 checkpoint 默认保存在本机；当使用外部模型 Provider 时，经过范围裁剪的上下文仍会发送给相应服务商。

当前适用范围是：**单用户、本地优先、SQLite、单进程可恢复执行**。它不是分布式 Agent 平台、招聘信息聚合器或自动投递系统。

### Agent Trace 诊断维护

Trace 正文是本地私有诊断数据，元数据索引可以从 JSONL 重建。维护命令必须传入明确的 Workspace 根目录；脚本拒绝 `/`、用户主目录和不含应用数据目录的宽泛目标。

```bash
# 只读检查；存在缺文件、损坏行或失效偏移时返回非零
python3 scripts/check_agent_trace_consistency.py \
  --workspace-root /absolute/path/to/workspace

# 仅重建 Agent Trace 索引表，不改业务表、Trace JSONL 或领域产物
python3 scripts/rebuild_agent_trace_index.py \
  --workspace-root /absolute/path/to/workspace \
  --workspace-id <workspace-id>
```

已按保留策略删除的正文不会由索引重建恢复；需要从备份恢复原 JSONL 后再重建。检查命令默认不执行修复。

## 架构文档

- [产品总体路线](docs/superpowers/specs/2026-07-10-product-development-roadmap-design.md)
- [Agent Runtime 框架收敛](docs/superpowers/specs/2026-07-13-agent-runtime-framework-convergence-design.md)
- [领域 Agent 的 Tool 与写入边界](docs/superpowers/architecture-decisions/2026-07-20-domain-agent-tool-and-write-boundaries.md)
- [全路线 Agent 能力分配](docs/superpowers/architecture-decisions/2026-07-20-agent-capability-allocation-across-roadmap.md)
- [统一可取消执行 Runtime](docs/superpowers/architecture-decisions/2026-07-16-unified-cancellable-execution-runtime.md)
- [可恢复 Agent 任务边界](docs/superpowers/architecture-decisions/2026-07-22-resumable-agent-task-boundary.md)
- [统一个人画像与来源模型](docs/superpowers/architecture-decisions/2026-07-24-unified-profile-and-source-model.md)
- [岗位目标与项目训练边界](docs/superpowers/architecture-decisions/2026-07-25-job-target-project-training-runtime-boundaries.md)

项目持续围绕三项原则演进：模型判断可解释、关键变更可确认、长任务可恢复，并让每次准备和训练最终沉淀为真正属于用户的面试能力。
