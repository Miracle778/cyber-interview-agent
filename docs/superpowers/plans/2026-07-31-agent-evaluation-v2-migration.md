# Agent Evaluation v2 Migration Plan

**Status:** Phase 1–3 completed; Phase 4 execution-before snapshots, two isolated business reruns and blind pairwise comparison are implemented; Phase 5 trends and a default-off deterministic-only gate boundary are implemented. Real Provider browser calibration and final stage gates remain.

**Goal:** Preserve v1 history while moving evaluation from Trace-centric scoring to outcome-centric, task-specific quality evidence and then adding real candidate-version regression.

**Architecture:** Additive migration only. v1 remains immutable and is labeled historical review. v2 introduces business outcome adapters, applicability-aware results, minimal Judge views, verified deterministic rules, task-level Eval Packs, and finally an isolated regression runner that executes both baseline and candidate business Agents.

## Non-negotiable constraints

- Do not modify or delete v1 evaluation rows, packs, feedback, or cases.
- Do not compare v1 numeric scores with v2 ratings.
- Do not call historical re-judging a business Agent regression.
- Do not send a full private snapshot to an external Judge by default.
- Do not enable blocking rules during the initial v2 migration.
- Judge failure must remain isolated from business execution.
- Real regression must use a disposable Workspace or rollback-safe evaluation transaction.
- Use targeted tests per vertical slice; full backend/frontend regression only after cross-layer integration and before final acceptance.

## Phase 0: Correct product claims and freeze the decision

Deliverables:

- [x] Add the v2 boundary ADR.
- [x] Add the v2 design specification.
- [x] Add this staged migration plan.
- [x] Update the 2026-07-29 spec, ADR and Slice 3 plan with a v1 maturity notice and links to v2.
- [x] Update README wording: current feature is historical result review; real Agent regression is planned.
- [x] Replace the README quality diagram with a current-vs-target explanation; keep the old image as historical design material.
- [x] Update `task_plan.md`, `findings.md`, and `progress.md`.

Exit condition: repository documentation no longer claims the existing code reruns a candidate business Agent or has production blocking rules.

## Phase 1: v2 foundation and coexistence

### Task 1: Add additive schemas

**Status:** Completed 2026-08-01.

Introduce:

- `evaluation_contract_version`;
- dimension applicability, rating, severity and evidence gaps;
- Pack task type and business outcome hash;
- Judge provider/data-scope manifest;
- explicit `historical_review` and `agent_regression` run kinds.

Keep all v1 fields readable. New code writes v2 rows only for v2 Packs.

Implemented as runtime migration 041 plus additive repository/API contracts. Current v1 service calls are explicitly labeled `historical_review` and persist their actual `legacy_full_snapshot` Judge data scope; no existing rows were rewritten.

### Task 2: Build `BusinessOutcomeProjection`

**Status:** Common contract and first question-curation adapter completed 2026-08-01; remaining business adapters stay in their Phase 3 slices.

- Define the common projection contract.
- Add one adapter interface per business goal.
- Read terminal domain state, Receipt, source/version links and user decision.
- Prove later domain edits do not mutate a completed evaluation projection.
- Keep raw Trace as an explanatory reference, not the primary result.

The first adapter resolves a question-curation Execution to its persisted batch, work items, seed tasks, candidates, source semantics and user decisions. It records the current merged-answer provenance gap instead of inventing source/supplemental separation.

### Task 3: Add applicability-aware evaluation

**Status:** Completed 2026-08-01.

- Code decides obvious `not_applicable` and `insufficient_evidence` cases.
- Judge contract permits nullable rating and explicit evidence gaps.
- UI replaces total score with anchored labels, severity and confidence.
- Existing v1 results display under an “初版质检” badge.

### Task 4: Add minimal `EvaluationView`

**Status:** Completed 2026-08-01 for the first question-curation v2 Pack; the same privacy contract is now the required template for Phase 3 task Packs.

- Each Pack declares required fields and redaction policy.
- Persist a privacy manifest with Judge provider/model and data categories.
- Contract tests prove secrets, local paths and unrelated private fields are absent.
- Full private Trace requires explicit advanced-diagnostics authorization.

Exit condition: one fixture Pack can evaluate a business outcome using v2 contracts without changing v1 behavior.

## Phase 2: True deterministic rule engine

### Task 5: Rename v1 checks

**Status:** Completed 2026-08-01. API keeps immutable v1 rows; UI now names the legacy checks “评估证据完整性检查” and does not expose the unused blocking field.

- UI/API call existing checks “评估证据完整性检查”.
- Do not surface their `blocking` field.
- Preserve historical records unchanged.

### Task 6: Implement common Runtime invariants

**Status:** Completed 2026-08-01 as an advisory rule engine. Rules cite domain Execution rows, outcome hashes, counters and source refs. Evidence not present in the projection is reported as inconclusive instead of guessed.

Start with read-only rules for:

- workspace ownership;
- source/version/hash/locator validity;
- state transition legality;
- idempotent terminal writes;
- count conservation;
- no late-result overwrite;
- Tool and write-boundary compliance.

Each rule must cite domain rows, Receipts or immutable hashes, not merely event-type presence.

### Task 7: Calibrate before blocking

**Status:** Initial deterministic calibration harness and labeled positive/negative/ambiguous fixtures completed 2026-08-01. All v2.0 rules remain advisory; no automatic blocking switch exists.

- Build labeled positive, negative and ambiguous cases.
- Record false positive/negative rates.
- Keep all rules advisory in v2.0.
- Any future blocking upgrade requires a separate ADR and rollout switch.

Exit condition: rules can detect known invariant violations without relying on Judge and without blocking business traffic.

## Phase 3: Migrate task Packs by business value

**Implementation status (2026-08-01):** 12 个 v2 Pack 已注册；题目、复习、画像、JD 与项目任务均有最小 Outcome Adapter/Judge View。题目答案按 `source_answer` / `supplemental_answer` 独立持久化和展示；复习推进、画像写入回执/版本、JD offset、项目 Gap/题库关联等可证明事实已接入 advisory Rule。无法由最终快照证明的讨论隔离、迟到结果与“未记录≠不存在”等边界明确返回证据不足，不由 Judge 猜测。所有规则仍不阻断业务。

Implement one vertical slice at a time, including adapter, rules, Judge view, API, UI and a small real-case set.

### Slice A: Question curation and revision

- Preserve source/supplemental answers separately.
- Replace fake general coverage with material-type-aware checks.
- Separate duplicate recall from duplicate decisions.
- Model zero-result and partial-success states explicitly.

### Slice B: Review round, single evaluation and discussion

- Evaluate per-key-point business decisions.
- Move progression guard to deterministic rules.
- Separate follow-up decision from follow-up wording.
- Ensure discussion cannot advance review state.

### Slice C: Profile ingest, assessment, assistant and write boundary

- Field-level provenance and conflict relation.
- Explicit assessment scope and missing-data semantics.
- Tool necessity/usefulness checks for assistant turns.
- Pure deterministic Proposal/HITL/Receipt boundary checks.

### Slice D: Job requirement analysis

- Clause classification before requirement extraction.
- Atomic logical groups and AND/OR preservation.
- Deterministic source offsets and version links.
- Separate inferred preparation advice from explicit job gates.

### Slice E: Project coaching and project question generation

- Evaluate information gain against a real gap.
- Separate user facts, current answer, inference and generic advice.
- Persist gap lifecycle and generated-question references.
- Do not force fixed question categories.

Exit condition per slice: representative real inputs, an evidence-insufficient case, an N/A case, a severe error case, and one Judge–human disagreement are all visible in the product.

## Phase 4: Real Agent regression

### Task 8: Versioned EvalCase

**Status:** Implemented 2026-08-01. New explicitly enabled runs freeze runtime DB, conversation checkpoints and local artifacts immediately before Graph execution. Historical runs without that capture remain non-runnable archives.

Freeze sanitized task input, required domain snapshot, expected invariants, privacy manifest and source execution. Record Graph, Prompt, model, reasoning, Tool, Schema, context, code, Pack and Judge versions.

### Task 9: Isolated business runner

**Status:** Implemented 2026-08-01. Source model bindings and current bindings run through the product Workspace Runtime in separate temporary roots; production writes are excluded and infrastructure failures are classified separately.

- Restore each case into a disposable evaluation Workspace.
- Run baseline and candidate business Agents independently.
- Prevent writes to the user’s production Workspace.
- Capture new business outcome projections and execution traces.
- Classify network timeout, Provider limit, database lock and other infrastructure failures separately.

### Task 10: Pairwise comparison

**Status:** Completed and accepted 2026-08-01. A/B order is deterministic-randomized per run and remapped only after the no-Tool Judge returns. Deterministic Runtime integration covers question curation and conversation; final acceptance additionally ran one sanitized real-Provider case of each kind through both sandboxes and the pairwise Judge.

- Judge receives anonymized A/B outcomes in random order.
- Run deterministic rules before the Judge.
- Default to one run; high-risk or unstable cases may run three times.
- Preserve ties, uncertainty and human overrides.

### Task 11: Product terminology and UX

**Status:** Completed and browser-accepted 2026-08-01. The UI separates history-only cases from private local runnable cases, requires explicit confirmation, only offers rerun for restorable cases, and shows friendly status, source/current implementation versions, blind-review conclusion, sandbox isolation and infrastructure failures.

- Existing action: “重新质检历史结果”.
- New action: “使用当前 Agent 版本运行回归案例”.
- Show whether the business result was regenerated.
- Show exact baseline/candidate versions and infrastructure failures.

Exit condition: one real question-curation case and one conversational Agent case rerun baseline/candidate code in isolation and produce comparable outcome evidence.

**Exit evidence:** Completed. Real cases `bf931f31-3f13-437b-9b75-f70dccf55ff8` and `211e40e5-5c9b-4d4e-8934-554fe63c49b5` both produced regenerated baseline/candidate Outcome hashes, pairwise results, empty infrastructure failures and `productionWrites=false`.

## Phase 5: Trends and optional quality gates

**Implementation status (2026-08-01):** Compatible Pack/contract/run-kind grouping and v2 review/severe, Judge-human agreement, user edit/reject, infrastructure, latency and Token metrics are implemented. The gate evaluator accepts only explicitly validated deterministic rule IDs, is disabled by default, ignores Judge scores/preferences, and becomes inconclusive on infrastructure or evidence gaps. No rule is approved for blocking yet, so scheduled sampling and CI/release blocking remain intentionally disabled pending real-case calibration and a separate ADR.

- Compare only the same task Pack and compatible contract versions.
- Trend deterministic failure, review/severe rates, Judge–human agreement, user edit/reject, latency and Token.
- Add scheduled sampling only after manual case quality is stable.
- Consider CI or release gates only for validated deterministic invariants.
- Never use a single cross-Agent leaderboard score.

## Verification strategy

For each phase:

1. run only new contract/unit tests and affected API/component tests;
2. use sanitized fixtures for routine tests;
3. use a minimal number of real Provider calls for representative semantic paths;
4. update the incremental verification guide;
5. run `git diff --check` and inspect migration compatibility;
6. perform one browser happy path per vertical slice;
7. perform a complete browser acceptance only before v2 stage closure.

## Stage closure checklist

- [x] 后端完整回归：1005 passed。
- [x] 前端完整回归：68 files / 333 passed；TypeScript 与 production build 通过。
- [x] 真实 Provider：题目整理与深入讨论各一条，均完成 v2 Judge 和隔离 A/B 回归。
- [x] 浏览器验收：设置、质量报告、回归版本/隔离依据与趋势页面通过。
- [x] 文档门禁：verification、learning ownership pack 与本计划保持一致。

## Product maturity language

- After Phase 0: “当前能力边界已如实说明”.
- After Phase 1: “质量结果支持适用性、分级结论和隐私最小化”.
- After Phase 2: “具备基于业务结果的确定性不变量检查”.
- After each Phase 3 slice: “该业务目标具备 v2 任务级评估”.
- Only after Phase 4: “可以用冻结真实案例验证 Agent 候选版本改动”.
- Only after calibrated Phase 5 gates: “部分确定性不变量可作为发布门禁”.
