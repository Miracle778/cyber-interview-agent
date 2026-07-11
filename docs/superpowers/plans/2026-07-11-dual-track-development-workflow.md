# 双轨开发与项目所有权工作流实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Codex、Claude、新会话和上下文压缩后都能恢复的双轨规则，并生成首份 R1.2 掌握包。

**Architecture:** `AGENTS.md` 与 `CLAUDE.md` 是工具入口，共同引用唯一权威规格；`task_plan.md` 跟踪产品与掌握状态；被 Git 忽略的 `docs/learning/` 保存详细学习材料。

**Tech Stack:** Markdown、Git、现有 planning-with-files 文档体系。

## Global Constraints

- 用户练习不阻塞产品开发、提交、合并或下一阶段。
- 产品成熟度和用户掌握度分别记录。
- `docs/my_idea.md` 保持只读且不提交。
- 正式设计和计划只提交 `docs/superpowers/` 下的文档。
- `docs/verification/` 和 `docs/learning/` 为本地材料，分支合并时显式同步。
- 新会话以仓库文件和实际代码为权威证据。

---

### Task 1: Codex 与 Claude 仓库入口

**Files:**
- Create: `AGENTS.md`
- Create: `CLAUDE.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
- Produces: Codex 与 Claude Code 的强制会话恢复入口。

- [ ] **Step 1: 验证入口当前不存在**

Run: `test ! -e AGENTS.md && test ! -e CLAUDE.md`

Expected: exit 0。

- [ ] **Step 2: 创建 `AGENTS.md`**

写入以下完整规则：

```markdown
# Cyber Interview Agent Collaboration Rules

## Required Session Startup
Before project work, read in order:
1. `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`
2. `task_plan.md`
3. `findings.md`
4. `progress.md`
5. The current stage spec and implementation plan
6. Current Git branch, status, and recent commits

Repository files and executable state are authoritative; do not rely on chat memory alone.

## Non-Negotiable Workflow
- Keep product delivery and user ownership as separate tracks.
- User learning exercises never block implementation, commits, merges, or the next stage.
- Record unfinished learning as understanding debt.
- Maintain the local `docs/learning/<stage>/` ownership pack after each major stage.
- Batch product questions and provide recommended defaults.
- Codex owns complex cross-layer work, security boundaries, review, and acceptance.
- Claude may implement ordinary bounded tasks with minimal context; Codex verifies the result.
- Keep frontend behavior evolving with backend capabilities.
- Never modify or commit `docs/my_idea.md`.
- Only commit formal documents under `docs/superpowers/`; keep learning and verification files local and sync them after merges.

## Completion Reporting
Report product status, maturity boundary, ownership status, next product task, and the non-blocking user exercise separately.
```

- [ ] **Step 3: 创建 `CLAUDE.md`**

写入以下完整规则：

```markdown
# Claude Code Project Instructions

Before project work, read `AGENTS.md`, `docs/superpowers/specs/2026-07-11-dual-track-development-workflow-design.md`, `task_plan.md`, `findings.md`, `progress.md`, and the current stage spec and plan.

`AGENTS.md` is the concise cross-agent entry. The workflow design spec is the detailed source of truth. Do not let user learning exercises block product development. Use only the minimal repository context required by the assigned task. Codex owns review and final acceptance.
```

- [ ] **Step 4: 验证入口**

Run:

```bash
test -f AGENTS.md
test -f CLAUDE.md
rg -F "dual-track" AGENTS.md CLAUDE.md
rg -F "never block" AGENTS.md
rg -F "Do not let user learning exercises block" CLAUDE.md
git diff --check
```

Expected: 两个入口存在，均包含双轨与非阻塞规则，diff 检查通过。

- [ ] **Step 5: 提交入口**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: add cross-agent project instructions"
```

### Task 2: 掌握状态与理解债务

**Files:**
- Modify: `.gitignore`
- Modify: `task_plan.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: Task 1 的入口。
- Produces: 可跨会话读取的掌握状态和本地学习目录规则。

- [ ] **Step 1: 验证状态区不存在**

Run:

```bash
! rg -F "## 项目所有权与理解债务" task_plan.md
! rg -F "docs/learning/" .gitignore
```

Expected: exit 0。

- [ ] **Step 2: 显式忽略 `docs/learning/`**

在 `.gitignore` 本地文档规则加入：

```gitignore
docs/learning/
```

- [ ] **Step 3: 增加掌握状态表**

在 `task_plan.md` 当前状态后增加：

```markdown
## 项目所有权与理解债务

产品进度与掌握进度分别记录。掌握任务不阻塞产品开发、合并或下一阶段。

| 阶段 | 产品状态 | 已掌握 | 待掌握 | 待实践 | 非阻塞练习 |
|---|---|---|---|---|---|
| R1.1 | 可人工验证 | 待验证 | Provider adapter、模型绑定与 secret 边界 | Provider 请求链路 | 解释一次模型测试请求 |
| R1.2 | 可人工验证 | Runtime 总体分层 | RunManager、恢复语义、SSE 重放 | 增加 Runtime 查询能力 | 增加 Run 详情查询接口 |
| R1.3 | 待开始 | - | Workspace scope、路径与软链接安全 | SafePathResolver | 实现或审阅路径校验用例 |

- 已掌握：可以脱离文档解释并回答追问。
- 待掌握：已有或待生成材料，尚未完成讲解验证。
- 待实践：需要通过修改、调试或审阅证明。
```

- [ ] **Step 4: 更新 `progress.md`**

追加：

```markdown
### 双轨开发工作流

- 已确认产品进度与用户掌握进度分离。
- 用户所有权练习为非阻塞任务，未完成项进入理解债务。
- Codex 与 Claude 使用仓库级入口恢复同一规则。
- 本地掌握包写入 `docs/learning/<stage>/`，正式规格继续写入 `docs/superpowers/`。
```

- [ ] **Step 5: 验证 ignore 与状态**

Run:

```bash
mkdir -p docs/learning/.workflow-check
touch docs/learning/.workflow-check/probe.md
git check-ignore docs/learning/.workflow-check/probe.md
rg -F "## 项目所有权与理解债务" task_plan.md
rg -F "掌握任务不阻塞产品开发" task_plan.md
git diff --check
```

Expected: probe 被忽略，状态区可检索，diff 检查通过。

- [ ] **Step 6: 提交状态规则**

```bash
git add .gitignore task_plan.md progress.md
git commit -m "docs: track product ownership debt"
```

### Task 3: R1.2 首份所有权掌握包

**Files:**
- Create local: `docs/learning/r1-2-runtime/overview.md`
- Create local: `docs/learning/r1-2-runtime/architecture.md`
- Create local: `docs/learning/r1-2-runtime/code-walkthrough.md`
- Create local: `docs/learning/r1-2-runtime/failure-journal.md`
- Create local: `docs/learning/r1-2-runtime/interview-questions.md`
- Create local: `docs/learning/r1-2-runtime/exercises.md`
- Create local: `docs/learning/r1-2-runtime/presentation-script.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: R1.2 最终代码、设计、计划、验证指南和审阅记录。
- Produces: 第一份可延后学习的 Agent Harness 掌握包。

- [ ] **Step 1: 验证目录不存在**

Run: `test ! -d docs/learning/r1-2-runtime`

Expected: exit 0。

- [ ] **Step 2: 生成七份真实材料**

使用以下固定结构：

```text
overview.md
  - R1.2 解决的问题
  - 已实现的用户效果
  - 当前边界

architecture.md
  - Workspace Runtime 分层
  - Session/Run/Message/Event/Checkpoint
  - REST 命令、SSE 观察和恢复语义

code-walkthrough.md
  - RuntimeDiagnostics 发起请求
  - Agent API 与 AgentRuntime
  - RunManager、GraphRegistry 与 Checkpointer
  - Repository、EventStream 与 useAgentEvents

failure-journal.md
  - SQLite connection 与线程池
  - graceful shutdown 与 interrupted
  - running/task 创建窗口
  - checkpoint 缺失恢复
  - SSE keepalive 锁
  - 历史 run 和旧 EventSource 回调

interview-questions.md
  - 基础概念题
  - 架构取舍题
  - 故障与扩展追问
  - 每题参考答案要点

exercises.md
  - Run 详情查询主练习
  - Trace、Review、Debug 降级形式
  - 完成证据和不阻塞声明

presentation-script.md
  - 3 分钟讲解稿
  - 10 分钟讲解提纲
  - AI 协作的诚实表述
```

每份材料引用当前真实代码路径，不得声称 R1.3-R1.6 已完成。

- [ ] **Step 3: 验证完整性与 ignore**

Run:

```bash
test "$(find docs/learning/r1-2-runtime -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "7"
rg -F "R1.2" docs/learning/r1-2-runtime
rg -F "当前边界" docs/learning/r1-2-runtime/overview.md
git check-ignore docs/learning/r1-2-runtime/overview.md
git diff --check
```

Expected: 七份材料存在、边界明确、文件被 Git 忽略。

- [ ] **Step 4: 更新并提交索引状态**

在 `progress.md` 记录掌握包路径和非阻塞练习，然后提交：

```bash
git add progress.md docs/superpowers/plans/2026-07-11-dual-track-development-workflow.md
git commit -m "docs: establish ownership learning workflow"
```

## 完整验收

```bash
test -f AGENTS.md
test -f CLAUDE.md
rg -F "## 项目所有权与理解债务" task_plan.md
test "$(find docs/learning/r1-2-runtime -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')" = "7"
git check-ignore docs/learning/r1-2-runtime/overview.md
git diff --check
git status --short
```

Expected: 双入口、理解债务、首份掌握包和 ignore 规则全部有效，工作区干净。
