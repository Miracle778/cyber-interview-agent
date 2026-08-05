# Workspace 历史复盘检索与总结报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在“面试复盘”内实现 Workspace 级自然语言历史检索、可追溯即时总结和版本化总结报告。

**Architecture:** 固定 Workflow 先把自然语言解析为有界 SearchPlan，再由确定性 Repository 扫描正式题目、固化不可变 Search Set/Result；总结与报告只读取该结果集，并用分批 Map-Reduce 控制长上下文。搜索与报告共享现有复盘分析模型绑定，但使用独立 Agent Execution 名称和只读证据边界。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLite、现有 AgentFactory/ExecutionService、React、TanStack Query、TypeScript、Vitest。

## Global Constraints

- 不修改或提交 `docs/my_idea.md`。
- 不新增外部向量数据库、联网检索或第三方搜索服务。
- 确定性检索在 Provider 不可用时仍可工作。
- 未确认推断题、拒绝/替代题和回收站复盘不得进入语料。
- 总结和报告引用必须属于固定 Search Set。
- 首版不读取画像、简历、岗位原文、完整转写或其他 Workspace。
- 复用现有 `retrospective_analysis` 模型绑定，不新增设置页必填项。
- 保留当前工作区未提交的复盘 Harness、Trace 和页面修改，不覆盖无关差异。

---

### Task 1: Search Set、Result 与 Report 持久化合同

**Files:**
- Create: `backend/app/db/migrations/runtime/052_retrospective_history_search.sql`
- Modify: `backend/app/interview_retrospectives/models.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Test: `backend/tests/test_interview_retrospective_history_repository.py`

**Interfaces:**
- Produces: `RetrospectiveSearchSetRecord`、`RetrospectiveSearchResultRecord`、`RetrospectiveSearchReportRecord`。
- Produces: `create_search_set(...)`、`replace_search_results(...)`、`get_search_set(...)`、`list_search_results(...)`、`create_search_report(...)`、`update_search_report(...)`。

- [ ] **Step 1: 写 migration 与 repository RED 测试**

```python
def test_search_set_freezes_ordered_workspace_results(runtime_db):
    repository = InterviewRetrospectiveRepository(runtime_db)
    search = repository.create_search_set(
        workspace_id="workspace-a",
        query_text="数字签名项目",
        filters={},
        search_plan={"terms": ["数字签名", "PKI"]},
        execution_id=None,
    )
    repository.replace_search_results(search.id, results=[...])
    assert [item.rank for item in repository.list_search_results(search.id)] == [1, 2]
```

- [ ] **Step 2: 运行测试确认缺少表与方法**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_repository.py`

Expected: FAIL，提示 migration 表或 Repository 方法不存在。

- [ ] **Step 3: 实现增量 schema 与 dataclass**

```sql
CREATE TABLE interview_retrospective_search_sets (...);
CREATE TABLE interview_retrospective_search_results (...);
CREATE TABLE interview_retrospective_search_reports (...);
```

Search Result 必须外键绑定 Search Set、Retrospective、Question 和 Analysis；结果保存稳定 `rank`、`score`、`matched_terms_json`、问题/回答/分析短快照和来源元数据。

- [ ] **Step 4: 实现 Repository CRUD 与 Workspace 校验**

写操作统一使用事务；`replace_search_results` 必须先校验每条来源属于 Search Set 的 Workspace，再原子替换并更新命中数。

- [ ] **Step 5: 验证迁移、级联与版本冲突**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_repository.py tests/test_runtime_migrations.py`

Expected: PASS。

### Task 2: 确定性历史复盘检索服务

**Files:**
- Create: `backend/app/interview_retrospectives/history_search.py`
- Modify: `backend/app/interview_retrospectives/repository.py`
- Test: `backend/tests/test_interview_retrospective_history_search.py`

**Interfaces:**
- Consumes: Task 1 的 Search Set/Result Repository。
- Produces: `RetrospectiveSearchFilters`、`RetrospectiveSearchPlan`、`HistoricalSearchService.search(...)`。

- [ ] **Step 1: 写语料过滤与排序 RED 测试**

覆盖：原题、已确认推断题、未确认推断题、拒绝/替代题、active/archived/recycled、跨 Workspace、同分稳定排序。

```python
result = service.search(
    workspace_id="workspace-a",
    query_text="数字签名项目",
    plan=RetrospectiveSearchPlan(terms=("数字签名", "PKI", "HSM")),
    filters=RetrospectiveSearchFilters(),
)
assert [item.question_id for item in result.items] == [expected_question_id]
```

- [ ] **Step 2: 运行 RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_search.py`

- [ ] **Step 3: 实现语料查询与可解释评分**

`history_search.py` 负责规范化中英文、生成中文双字项和英文技术词，并按字段权重评分：题目 8、项目/复盘元数据 6、回答 4、分析 2。通用停用词不计分，显式短语命中追加权重。

- [ ] **Step 4: 固化完整结果集并返回分页投影**

Search Set 保存全部命中结果；API 分页只影响读取，不影响“所有”的总数和后续报告范围。

- [ ] **Step 5: 运行定向回归**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_search.py tests/test_interview_retrospective_repository.py`

Expected: PASS。

### Task 3: 有界 Search Agent、即时总结与报告 Map-Reduce

**Files:**
- Modify: `backend/app/agents/interview_retrospective_contracts.py`
- Modify: `backend/app/agents/prompts/interview_retrospective_prompts.py`
- Modify: `backend/app/agents/interview_retrospective_agents.py`
- Modify: `backend/app/application/graph_factory.py`
- Test: `backend/tests/test_interview_retrospective_history_agents.py`

**Interfaces:**
- Produces: `HistoricalSearchPlanOutput`、`HistoricalSearchBatchSummary`、`HistoricalSearchSummaryOutput`、`HistoricalSearchReportOutput`。
- Produces: `plan_history_search(...)`、`summarize_history_batch(...)`、`reduce_history_summary(...)`、`generate_history_report(...)`。

- [ ] **Step 1: 写严格结构化合同 RED 测试**

```python
plan = HistoricalSearchPlanOutput.model_validate({
    "searchTerms": ["数字签名", "PKI", "HSM"],
    "projectAliases": ["签名云服务"],
})
assert len(plan.search_terms) <= 12
```

并验证模型不能返回 Workspace ID、复盘 ID、任意 SQL、写入动作或未引用题目的报告结论。

- [ ] **Step 2: 运行 RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_agents.py`

- [ ] **Step 3: 增加四个固定 Prompt/Agent Runnable**

Search Plan 只输出搜索词和项目别名；Batch Summary 只引用当前批次题目；Reduce 只读取批次摘要；Report 只读取冻结范围、批次摘要和引用 ID。

- [ ] **Step 4: 增加调用策略**

解析最多 2,048 输出 Token；批次总结 4,096；最终总结和报告各 6,144；全部 `max_retries=0`，应用层只对瞬时 Provider 错误恢复当前阶段。

- [ ] **Step 5: 验证上下文边界与 Trace 名称**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_agents.py tests/test_interview_retrospective_agents.py`

Expected: PASS。

### Task 4: Application Workflow 与 Execution 恢复

**Files:**
- Create: `backend/app/interview_retrospectives/history_application.py`
- Modify: `backend/app/application/workspace_runtime.py`
- Modify: `backend/app/observability/registry.py`
- Test: `backend/tests/test_interview_retrospective_history_application.py`

**Interfaces:**
- Consumes: Task 1–3。
- Produces: `start_search(...)`、`get_search(...)`、`summarize_search(...)`、`create_report(...)`、`get_report(...)`、`list_reports(...)`、`update_report(...)`。

- [ ] **Step 1: 写无 Provider 搜索、Provider 总结和失败恢复 RED 测试**

验证解析失败回退原始查询、搜索完成后即时可读、总结失败不破坏结果集、报告批次失败可恢复、引用越界失败。

- [ ] **Step 2: 运行 RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_application.py`

- [ ] **Step 3: 实现固定工作流**

```text
search: prepare execution → optional parse → deterministic search → freeze set
summary: prepare execution → batch map → citation validation → reduce
report: prepare execution → batch map/reuse → report reduce → persist version
```

Search 使用 Workspace 私有 system Session；每次总结和报告创建独立 Execution，运行中心显示真实状态。

- [ ] **Step 4: 实现长结果集批次与恢复**

每批最多 12 题、正文预算最多 24,000 字符；已完成批次写入 Search Set/Report progress JSON，恢复只运行未完成批次。

- [ ] **Step 5: 运行应用与 Execution 回归**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_application.py tests/test_review_timeline.py`

Expected: PASS。

### Task 5: Workspace Search/Report API

**Files:**
- Modify: `backend/app/schemas/interview_retrospectives.py`
- Modify: `backend/app/api/routes_interview_retrospectives.py`
- Test: `backend/tests/test_interview_retrospective_history_api.py`

**Interfaces:**
- Produces endpoints:
  - `POST /api/interview-retrospective-searches`
  - `GET /api/interview-retrospective-searches/{search_id}`
  - `GET /api/interview-retrospective-searches/{search_id}/results`
  - `POST /api/interview-retrospective-searches/{search_id}/summary`
  - `POST /api/interview-retrospective-searches/{search_id}/reports`
  - `GET /api/interview-retrospective-search-reports`
  - `GET/PUT /api/interview-retrospective-search-reports/{report_id}`

- [ ] **Step 1: 写 Workspace 隔离、分页和幂等 RED 测试**

- [ ] **Step 2: 运行 RED**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_api.py`

- [ ] **Step 3: 增加 camelCase Schema 与路由**

所有命令使用 `Idempotency-Key`；列表使用 `cursor/limit`，默认 20、最大 100；不存在和跨 Workspace 都返回 404。

- [ ] **Step 4: 验证 Provider 缺失和来源删除错误投影**

确定性搜索不得返回模型未配置错误；总结/报告返回稳定业务错误码，不暴露 Provider 或 SQLite 原文。

- [ ] **Step 5: 运行 API 与 schema 回归**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_api.py tests/test_interview_retrospective_api.py`

Expected: PASS。

### Task 6: 历史检索与报告前端闭环

**Files:**
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveHistorySearch.tsx`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveSearchResults.tsx`
- Create: `frontend/src/features/interviewRetrospectives/RetrospectiveSearchReport.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.tsx`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveTypes.ts`
- Modify: `frontend/src/features/interviewRetrospectives/retrospectiveApi.ts`
- Modify: `frontend/src/features/interviewRetrospectives/interviewRetrospectives.css`
- Test: `frontend/src/features/interviewRetrospectives/RetrospectiveHistorySearch.test.tsx`
- Test: `frontend/src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`

**Interfaces:**
- Consumes: Task 5 API。
- Produces: `复盘记录 / 历史检索`页签、分组结果、题目详情、即时总结、报告创建和报告记录。

- [ ] **Step 1: 写入口、搜索、结果分组和报告 RED 测试**

验证 Provider 未配置时搜索仍工作、总结按钮明确禁用原因、结果可定位具体题目、报告创建后进入报告页。

- [ ] **Step 2: 运行 RED**

Run: `cd frontend && npm test -- --run src/features/interviewRetrospectives/RetrospectiveHistorySearch.test.tsx src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`

- [ ] **Step 3: 实现高保真已确认布局**

桌面使用结果列表 60% + 详情 40%；899px 以下变成单列。筛选统一使用现有自定义 Select；不新增原生浏览器选择框。

- [ ] **Step 4: 实现总结和报告状态**

总结展示运行步骤和引用；报告创建 Drawer 选择范围/侧重点，报告页面支持正文编辑、来源附录和返回搜索结果。

- [ ] **Step 5: 运行前端定向门禁**

Run: `cd frontend && npm test -- --run src/features/interviewRetrospectives/RetrospectiveHistorySearch.test.tsx src/features/interviewRetrospectives/InterviewRetrospectivePage.test.tsx`

Run: `cd frontend && npx tsc --noEmit && npm run build`

Expected: PASS；只允许既有大 chunk 警告。

### Task 7: 隐私联动、浏览器验收与阶段文档

**Files:**
- Modify: `backend/app/interview_retrospectives/repository.py`
- Modify: `backend/tests/test_interview_retrospective_privacy.py`
- Modify: `docs/verification/interview-retrospective-agent.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: Task 1–6 完整闭环。
- Produces: 清除原文/永久删除联动、最终验证证据和用户验收指南。

- [ ] **Step 1: 增加原文清除与来源删除 RED 测试**

验证 Search Result 回答摘录被清除、Report 显示来源不可用、跨 Workspace 数据不受影响。

- [ ] **Step 2: 实现清除联动并运行隐私回归**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_privacy.py tests/test_interview_retrospective_history_repository.py`

- [ ] **Step 3: 运行合并定向回归**

Run: `cd backend && uv run pytest -q tests/test_interview_retrospective_history_*.py tests/test_interview_retrospective_api.py tests/test_interview_retrospective_chat.py`

Run: `cd frontend && npm test -- --run src/features/interviewRetrospectives`

- [ ] **Step 4: 5175 端口浏览器验收**

覆盖：进入历史检索、自然语言搜索、筛选、分组结果、查看题目、即时总结、生成报告、编辑报告、刷新恢复、返回来源、1024px 和移动端布局。

- [ ] **Step 5: 更新验证与当前状态文档**

明确产品成熟度：词法检索 + Agent 别名扩展，不宣称向量语义召回；报告只基于冻结 Search Set。

## Self-Review

- Spec coverage：数据、Agent、确定性检索、总结、报告、隐私、删除、恢复、前端和浏览器验收均有对应 Task。
- Placeholder scan：计划不含 TBD/TODO/“类似 Task N”等占位表述。
- Type consistency：Search Set/Result/Report 从 Task 1 贯穿 Application、API 和前端；所有总结与报告入口均使用 `search_id`，不使用聊天上下文正文作为事实源。
