# 面试复盘准确转写文档与题目提取前置流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将录音转写先整理成一份可直接阅读、可整体编辑、可确认版本的准确转写文档，再以该文档作为题目提取和复盘分析的唯一输入；窗口、模型调用和重试只留在运行中心，不再变成用户需要逐段处理的产品对象。

**Architecture:** 保留现有 `SourceVersion → CleanupVersion → AnalysisRun` 外键链以兼容未合并特性代码和历史数据，但把 `CleanupVersion` 的产品含义收敛为 `CleanTranscriptVersion`。Cleanup 内部采用非重叠目标区间加只读前后文的 Map/Reduce：模型只返回当前目标区间的 `correctedTarget` 与少量不确定项，程序按目标区间确定性拼接为唯一 `documentBody`。用户只审核连续文档和稀疏问题；确认后程序从最终文档生成只读 `SegmentRecord` 锚点，题目提取继续复用现有 evidence ID，不再读取窗口输出或旧 Correction Diff。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、SQLite runtime migrations、React 19、TypeScript、TanStack Query、pytest、Vitest。

## Global Constraints

- 不修改或提交 `docs/my_idea.md`。
- 当前工作区包含同一特性的未提交改动；保留这些改动，不做 reset、checkout 或整树覆盖。
- 在用户明确要求前不创建提交。
- 新运行不得创建面向用户的模型 Turn、SourceUnit 或逐字符 Correction 队列；旧记录只做兼容读取。
- `SourceVersion.body` 是不可变原文；`CleanupVersion.document_body` 是整理确认前后的唯一采用稿；下游不得自行选择其他正文。
- 目标窗口必须无缝覆盖原文且彼此不重叠；前后文只能帮助理解，禁止在输出中重复。
- 模型失败只能影响当前窗口；已完成窗口必须可恢复、可重试且不重复调用。
- 每个任务先运行列出的失败测试，再实现，再运行通过测试。
- 每完成一个任务更新 `docs/verification/interview-retrospective.md`、`findings.md` 和 `progress.md` 的增量证据。

---

### Task 1: 建立连续准确转写文档的持久化与兼容边界

**Status:** 已完成并通过定向与全量回归。

**Files:**

- Create: `backend/app/db/migrations/runtime/050_interview_clean_transcript_document.sql`
- Modify: `backend/app/interview_retrospectives/models.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `backend/app/interview_retrospectives/projection.py`
- Test: `backend/tests/test_interview_retrospective_migration.py`
- Test: `backend/tests/test_runtime_migrations.py`
- Test: `backend/tests/test_interview_retrospective_repository.py`
- Test: `backend/tests/test_interview_retrospective_projection.py`

**Interfaces:**

```python
TranscriptIssueKind = Literal["uncertain_term", "speaker", "semantic"]
TranscriptIssueDecision = Literal["pending", "accepted", "kept", "manual"]

@dataclass(frozen=True, slots=True)
class CleanupVersionRecord:
    # existing fields stay unchanged
    document_body: str | None
    document_sha256: str | None

@dataclass(frozen=True, slots=True)
class TranscriptReviewIssueRecord:
    id: str
    cleanup_version_id: str
    ordinal: int
    document_start: int
    document_end: int
    excerpt: str
    suggestion: str | None
    issue_kind: TranscriptIssueKind
    reason: str
    confidence: float
    decision: TranscriptIssueDecision
```

**Steps:**

- [ ] 添加失败迁移测试：050 为 `interview_cleanup_versions` 增加 nullable `document_body`、64 位 `document_sha256`，并创建按 cleanup/ordinal 稳定排序的 `interview_transcript_review_issues`。
- [ ] 添加 repository 失败测试：一次事务写入完整文档和稀疏问题；文档哈希由程序计算；乐观锁冲突不产生半成品。
- [ ] 添加 projection 失败测试：新运行投影 `documentBody`、`documentSha256`、`reviewIssues`；旧运行字段为空时仍返回现有 segments/corrections，不破坏历史读取。
- [ ] 实现迁移、模型映射、repository 写入/读取与 API resource 字段。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_migration.py tests/test_runtime_migrations.py tests/test_interview_retrospective_repository.py tests/test_interview_retrospective_projection.py`

### Task 2: 用非重叠目标窗口替换 SourceUnit/Turn/Diff 模型协议

**Status:** 已完成并通过定向与全量回归。

**Files:**

- Modify: `backend/app/agents/interview_retrospective_contracts.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Rewrite: `backend/app/graphs/interview_retrospective_cleanup.py`
- Test: `backend/tests/test_interview_retrospective_agents.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`

**Interfaces:**

```python
class CleanupUncertainItem(RetrospectiveAgentModel):
    excerpt: str
    possible_value: str | None = None
    issue_kind: Literal["uncertain_term", "speaker", "semantic"]
    reason: str
    confidence: float = Field(ge=0, le=1)

class CleanupWindowOutput(RetrospectiveAgentModel):
    corrected_target: str
    uncertain_items: list[CleanupUncertainItem] = []

@dataclass(frozen=True, slots=True)
class CleanupTargetWindow:
    ordinal: int
    context_start: int
    target_start: int
    target_end: int
    context_end: int
    before_context: str
    target_text: str
    after_context: str
```

**Steps:**

- [ ] 添加失败测试：目标区间从 0 到 source length 连续覆盖、无重叠；自然边界优先；上下文可重叠但不计入目标输出。
- [ ] 添加失败测试：相邻窗口拥有重复上下文时，最终文档只包含每个目标一次；不得再出现 `sourceUnits`、turns、模型 offset 或逐字符 Diff。
- [ ] 添加失败测试：模型返回空正文、明显遗漏目标、大比例新增事实或不唯一 uncertainty excerpt 时，仅当前窗口进入 retryable/需要人工处理，不污染其他窗口。
- [ ] 将模型 Prompt 收窄为“纠正目标区间”：只做 ASR 错字、断句、口头赘词和保守说话人标注；上下文只读；数字、否定、组织、职责和技术术语不确定时保留并上报。
- [ ] 使用约 2,400 字符目标区间、前后各最多 400 字符上下文；Provider 输出上限继续有界，但不再复制整段原文和审计字段。
- [ ] 保留现有超时、截断拆窗、停止和恢复语义，把子窗口也规划成不重叠目标区间。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_agents.py tests/test_interview_retrospective_cleanup.py`

### Task 3: 实现窗口 Map、文档 Reduce 和局部恢复

**Status:** 已完成并通过定向与全量回归。

**Files:**

- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`
- Test: `backend/tests/test_interview_retrospective_service.py`
- Test: `backend/tests/test_interview_retrospective_api.py`

**Behavior:**

```text
pending/retryable window
  -> call model with context + exact target
  -> persist correctedTarget
all target windows completed
  -> sort by target_start
  -> assert gap-free coverage
  -> concatenate correctedTarget once
  -> locate sparse uncertain excerpts in assembled document
  -> persist documentBody + reviewIssues atomically
  -> status=review_pending, stage=waiting_for_review
```

**Steps:**

- [ ] 添加失败测试：刷新或进程重启后只继续未完成窗口，已完成 output_json 不重新调用模型。
- [ ] 添加失败测试：窗口输出顺序打乱仍按 target_start 拼接；缺口、重复目标或 digest 不匹配时不得进入 review_pending。
- [ ] 添加失败测试：一个窗口超时/截断只拆分该目标，之前完成结果保留；重试后文档只拼接一次。
- [ ] 实现 `assemble_clean_document()` 和稀疏 issue 定位；同一 excerpt 在目标正文内不唯一时生成窗口级语义问题，不猜 offset。
- [ ] 新运行完成后不再调用 `replace_segments(... corrections=...)`；只持久化 document artifact。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_cleanup.py tests/test_interview_retrospective_service.py tests/test_interview_retrospective_api.py`

### Task 4: 增加整篇文档编辑、确认门禁和确定性锚点

**Status:** 已完成并通过 API、Service 与分析边界回归。

**Files:**

- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/service.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Test: `backend/tests/test_interview_retrospective_api.py`
- Test: `backend/tests/test_interview_retrospective_cleanup.py`
- Test: `backend/tests/test_interview_retrospective_analysis.py`

**Interfaces:**

```python
class UpdateCleanTranscriptCommand(AgentModel):
    workspace_id: str
    expected_version: int
    document_body: str
    issue_decisions: list[TranscriptIssueDecisionEdit] = []
```

**Steps:**

- [ ] 添加 `PUT /interview-retrospectives/{id}/cleanup/{cleanup_id}/document` 失败测试：整体正文编辑与 issue 决定原子保存，expectedVersion 冲突返回现有 409 语义。
- [ ] 添加确认失败测试：documentBody 为空、仍有 pending issue 或文档哈希不一致时禁止确认；旧 cleanup 没有 documentBody 时继续走历史 segment 门禁。
- [ ] 确认新文档时按自然段和有界长度确定性生成 `SegmentRecord` 锚点；从 `面试官：/候选人：/我：` 前缀保守映射 speaker_role，其余为 unknown。
- [ ] 确认后 `documentBody` 不再可原地修改；后续重新整理创建新 CleanupVersion。
- [ ] 验证 AnalysisRun 和 QuestionExtraction 只读取确认版本生成的锚点，不读取 work item output_json、CorrectionRecord 或 SourceVersion.body。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_api.py tests/test_interview_retrospective_cleanup.py tests/test_interview_retrospective_analysis.py`

### Task 5: 把 Cleanup 页面改成“连续文档 + 稀疏问题”

**Status:** 已完成并通过前端测试、构建与隔离数据浏览器 happy path。

**Files:**

- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Rewrite: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`
- Test: `frontend/src/features/interviewRetrospectives/CleanupWorkbench.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`

**Steps:**

- [ ] 先写失败测试：review_pending 默认显示一份连续整理稿，不显示几十/几百段卡片、Correction 数量或逐项 Diff。
- [ ] 先写失败测试：右侧只列 `uncertain_term/speaker/semantic` 稀疏问题；点击问题定位正文；用户可接受、保留、手工改或直接编辑全文。
- [ ] 先写失败测试：保存正文使用乐观锁；本地未保存内容在 API 失败后保留；存在 pending issue 时确认按钮说明具体阻塞数。
- [ ] running 状态继续展示真实窗口进度、持续时间、停止/恢复和“可离开页面”；已完成窗口只在运行中心查看，不提前生成产品段落列表。
- [ ] legacy cleanup 没有 documentBody 时只显示只读兼容入口和“重新整理为准确文档”，不继续扩展旧核对 UI。
- [ ] Run: `cd frontend && npm test -- --run src/features/interviewRetrospectives/CleanupWorkbench.test.tsx src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`

### Task 6: 将题目提取输入统一到确认后的准确文档锚点

**Status:** 已完成代码与确定性回归；真实 Provider 内容质量仍归 Task 8 验收。

**Files:**

- Modify: `backend/app/graphs/interview_retrospective_question_extraction.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Test: `backend/tests/test_interview_retrospective_question_extraction.py`
- Test: `backend/tests/test_interview_retrospective_analysis.py`

**Steps:**

- [ ] 添加失败测试：同一确认文档无论 Cleanup 原始窗口如何切分，生成完全相同的题目窗口和 evidence anchor。
- [ ] 添加失败测试：候选人单边录音可从回答保守推断问题并标记 `origin=inferred`；明确面试官问题使用 `origin=original`。
- [ ] 删除依赖模型清洗 turn 数量的边界逻辑；题目窗口只基于确认文档锚点和有界字符数规划。
- [ ] 确保重试与去重 stable key 来自规范化问题文本和文档证据，不来自 Cleanup work key。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_question_extraction.py tests/test_interview_retrospective_analysis.py`

### Task 7: 清理历史兼容、隐私删除和可观测语义

**Status:** 部分完成。业务库正文、ReviewIssue 与工作项清除已覆盖；本地 Agent Trace JSONL 的业务清除联动尚未关闭。

**Files:**

- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/app/interview_retrospectives/application.py`
- Modify: `backend/app/interview_retrospectives/projection.py`
- Modify: `frontend/src/features/agentRuns/RunDetailPage.tsx`
- Test: `backend/tests/test_interview_retrospective_source_clear.py`
- Test: `backend/tests/test_interview_retrospective_deletion.py`
- Test: `backend/tests/test_agent_trace_cleanup.py`

**Steps:**

- [ ] 添加失败测试：清除原文同时清除 documentBody、review issue 正文、work item input/output 和 trace 中可恢复正文，但保留哈希、状态和数量。
- [ ] 历史 Segment/Correction 数据继续可读；新运行不得写 CorrectionRecord。
- [ ] 运行中心明确标注内部步骤 `清理文本窗口 i/n` 与 `合并准确文档`，模型响应使用普通代码/JSON 容器，不再把成功背景渲染成巨大色块。
- [ ] Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_source_clear.py tests/test_interview_retrospective_deletion.py tests/test_agent_trace_cleanup.py`

### Task 8: 基线对比、回归和阶段验收

**Status:** 进行中。全量自动回归、production build 与隔离数据浏览器“建议→保存→确认”闭环已通过；真实长样本盲测、完整长流程和异常路径仍待执行。

**Files:**

- Modify: `docs/verification/interview-retrospective.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `task_plan.md`

**Steps:**

- [ ] 固定一份不含隐私的长 ASR 样本；同一 Provider/模型分别运行“直接整理 Prompt”和新 Workflow，保存盲测稿与成本/耗时数据。
- [ ] 验收：新 Workflow 在事实遗漏、错误新增、术语误改、职责拔高、说话人可读性五项不劣于直接 Prompt；若不满足，不得以架构完整替代质量达标。
- [ ] Run backend focused: `cd backend && uv run pytest -q tests/test_interview_retrospective_*.py tests/test_agent_trace_cleanup.py`
- [ ] Run frontend focused: `cd frontend && npm test -- --run src/features/interviewRetrospectives`
- [ ] Run lint/type/build: `cd backend && uv run ruff check app tests && cd ../frontend && npm run build`
- [ ] 浏览器最小 happy path：上传长文本 → 查看真实窗口进度 → 得到连续文档 → 修改/解决稀疏问题 → 确认 → 自动提取题目。
- [ ] 浏览器异常路径：刷新、停止、恢复、单窗口失败、格式错误重试、清除原文。
- [ ] 更新验证文档、学习包风险分类和阶段文档门禁；浏览器验收与基线盲测未完成前不得声明可交付。

## Plan Exit Criteria

- [ ] 产品页面只存在一份权威整理稿，不再让用户处理窗口/段落/Diff 爆炸。
- [ ] 同一输入重复运行时，目标窗口覆盖和拼接正文确定稳定。
- [ ] 题目提取只读取确认后的准确文档锚点。
- [ ] 真实长文本质量至少达到同模型直接整理 Prompt 的基线。
- [ ] 完成定向回归、构建、浏览器 happy path、异常路径和文档门禁。
