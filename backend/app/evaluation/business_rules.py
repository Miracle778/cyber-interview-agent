from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.evaluation.outcomes import BusinessOutcomeProjection


@dataclass(frozen=True, slots=True)
class BusinessRuleResult:
    rule_id: str
    status: str
    severity: str
    summary: str
    evidence_refs: tuple[str, ...]
    evidence_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BusinessRuleEvaluation:
    status: str
    blocking: bool
    rules: tuple[BusinessRuleResult, ...]


@dataclass(frozen=True, slots=True)
class RuleCalibrationCase:
    case_id: str
    outcome: BusinessOutcomeProjection
    expected_failures: frozenset[str]


@dataclass(frozen=True, slots=True)
class RuleCalibrationReport:
    case_count: int
    false_positive_count: int
    false_negative_count: int
    false_positive_rate: float
    false_negative_rate: float
    blocking_recommended: bool


def evaluate_common_business_rules(
    outcome: BusinessOutcomeProjection,
    *,
    connection: sqlite3.Connection,
    workspace_id: str,
) -> BusinessRuleEvaluation:
    connection.row_factory = sqlite3.Row
    rules = (
        _workspace_and_identity(outcome, connection, workspace_id),
        _unique_terminal_writes(outcome),
        _count_conservation(outcome),
        _source_provenance(outcome),
        _source_version_integrity(outcome),
        _unprovable_rule(
            "runtime.late_result_protection",
            "任务结束后结果保护需要状态转换历史或写入回执；最终快照不能单独证明。",
        ),
        _unprovable_rule(
            "runtime.tool_write_boundary",
            "Tool 与写入边界需要能力声明、审计记录和 Receipt；最小结果视图未携带这些证据。",
        ),
        _unprovable_rule(
            "runtime.receipt_event_consistency",
            "业务终态与 Receipt/Event 一致性需要领域 Receipt 和事件投影证据。",
        ),
    )
    status = (
        "failed"
        if any(item.status == "failed" for item in rules)
        else "inconclusive"
        if any(item.status == "inconclusive" for item in rules)
        else "passed"
    )
    return BusinessRuleEvaluation(status=status, blocking=False, rules=rules)


def evaluate_business_rules(
    outcome: BusinessOutcomeProjection,
    *,
    connection: sqlite3.Connection,
    workspace_id: str,
) -> BusinessRuleEvaluation:
    common = evaluate_common_business_rules(
        outcome,
        connection=connection,
        workspace_id=workspace_id,
    )
    rules = common.rules + _task_rules(outcome)
    status = (
        "failed"
        if any(item.status == "failed" for item in rules)
        else "inconclusive"
        if any(item.status == "inconclusive" for item in rules)
        else "passed"
    )
    return BusinessRuleEvaluation(status=status, blocking=False, rules=rules)


def calibrate_business_rules(
    cases: tuple[RuleCalibrationCase, ...],
    *,
    connection: sqlite3.Connection,
    workspace_id: str,
) -> RuleCalibrationReport:
    false_positive = 0
    false_negative = 0
    expected_total = 0
    possible_negative_total = 0
    for case in cases:
        result = evaluate_common_business_rules(
            case.outcome,
            connection=connection,
            workspace_id=workspace_id,
        )
        actual = frozenset(
            item.rule_id for item in result.rules if item.status == "failed"
        )
        false_positive += len(actual - case.expected_failures)
        false_negative += len(case.expected_failures - actual)
        expected_total += len(case.expected_failures)
        possible_negative_total += max(1, len(result.rules) - len(case.expected_failures))
    return RuleCalibrationReport(
        case_count=len(cases),
        false_positive_count=false_positive,
        false_negative_count=false_negative,
        false_positive_rate=false_positive / max(1, possible_negative_total),
        false_negative_rate=false_negative / max(1, expected_total),
        # Phase 2 explicitly keeps all rules advisory. A future gate requires a new ADR.
        blocking_recommended=False,
    )


def _workspace_and_identity(
    outcome: BusinessOutcomeProjection,
    connection: sqlite3.Connection,
    workspace_id: str,
) -> BusinessRuleResult:
    evidence = (f"agent_run:{outcome.identity.execution_id}",)
    if outcome.identity.workspace_id != workspace_id:
        return _failed(
            "runtime.workspace_ownership",
            "业务结果声明的 Workspace 与评估 Workspace 不一致。",
            evidence,
        )
    row = connection.execute(
        "SELECT run.id, run.session_id, run.status, session.workspace_id, "
        "session.graph_id FROM agent_runs run JOIN agent_sessions session "
        "ON session.id = run.session_id WHERE run.id = ?",
        (outcome.identity.execution_id,),
    ).fetchone()
    if row is None:
        return _inconclusive(
            "runtime.workspace_ownership",
            "找不到来源 Execution，无法核对资源归属。",
            evidence,
            ("missing_agent_run",),
        )
    mismatches = []
    if row["workspace_id"] != workspace_id:
        mismatches.append("workspace")
    if row["session_id"] != outcome.identity.session_id:
        mismatches.append("session")
    if row["graph_id"] != outcome.identity.graph_id:
        mismatches.append("graph")
    if row["status"] != outcome.execution_status:
        mismatches.append("execution_status")
    if mismatches:
        return _failed(
            "runtime.workspace_ownership",
            "业务结果身份与领域 Execution 不一致：" + "、".join(mismatches),
            evidence,
        )
    return _passed(
        "runtime.workspace_ownership",
        "Workspace、Session、Graph 和 Execution 终态与领域行一致。",
        evidence,
    )


def _unique_terminal_writes(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    item_ids = [item.item_id for item in outcome.items]
    unit_ids = [item.unit_id for item in outcome.units]
    duplicates = _duplicates(item_ids) | _duplicates(unit_ids)
    evidence = (f"outcome:{outcome.outcome_hash}",)
    if duplicates:
        return _failed(
            "runtime.idempotent_terminal_writes",
            "业务结果含重复稳定 ID：" + "、".join(sorted(duplicates)),
            evidence,
        )
    return _passed(
        "runtime.idempotent_terminal_writes",
        "结果项和工作单元稳定 ID 唯一；本次投影未发现重复终态写入。",
        evidence,
    )


def _count_conservation(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = []
    for name, counters in outcome.unit_counters.items():
        observed = counters.completed + counters.failed + counters.skipped + counters.pending
        if observed != counters.total:
            invalid.append(f"{name}:{observed}!={counters.total}")
    evidence = tuple(
        f"counter:{name}" for name in sorted(outcome.unit_counters)
    ) or (f"outcome:{outcome.outcome_hash}",)
    if invalid:
        return _failed(
            "runtime.count_conservation",
            "完成、失败、跳过和待处理数量不守恒：" + "；".join(invalid),
            evidence,
        )
    return _passed(
        "runtime.count_conservation",
        "全部公开计数满足 total = completed + failed + skipped + pending。",
        evidence,
    )


def _source_provenance(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    missing = []
    refs = []
    for item in outcome.items:
        for provenance in item.provenance:
            refs.extend(provenance.source_refs)
            refs.extend(provenance.evidence_refs)
            if provenance.support_type in {"direct", "normalized"} and not (
                provenance.source_refs or provenance.evidence_refs
            ):
                missing.append(f"{item.item_id}:{provenance.field_path}")
    evidence = tuple(f"source:{item}" for item in sorted(set(refs)))
    if missing:
        return _failed(
            "runtime.source_provenance",
            "声称直接或规范化来源的字段缺少来源引用：" + "、".join(missing),
            evidence or (f"outcome:{outcome.outcome_hash}",),
        )
    return _passed(
        "runtime.source_provenance",
        "直接来源与规范化字段均保留了来源引用。",
        evidence or (f"outcome:{outcome.outcome_hash}",),
    )


def _source_version_integrity(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    refs = {
        source
        for item in outcome.items
        for provenance in item.provenance
        for source in (*provenance.source_refs, *provenance.evidence_refs)
    }
    if not refs:
        return _inconclusive(
            "runtime.source_version_integrity",
            "没有可反查的来源引用。",
            (f"outcome:{outcome.outcome_hash}",),
            ("missing_source_refs",),
        )
    # Generic outcome refs are opaque by design. Domain adapters in Phase 3 add
    # version/hash/locator checks when the owning tables expose those facts.
    return _inconclusive(
        "runtime.source_version_integrity",
        "已有来源引用，但公共投影不足以证明版本、hash 与 locator 全部有效。",
        tuple(f"source:{item}" for item in sorted(refs)),
        ("domain_source_validation_required",),
    )


def _task_rules(outcome: BusinessOutcomeProjection) -> tuple[BusinessRuleResult, ...]:
    if outcome.task_type in {"question_curation", "question_revision"}:
        return (_question_answer_boundary(outcome), _question_zero_result(outcome))
    if outcome.task_type in {"review_round", "review_single"}:
        return (_review_progression_guard(outcome),)
    if outcome.task_type == "review_discussion":
        return (
            _unprovable_rule(
                "review.discussion_progress_isolation",
                "缺少讨论前后的正式复习进度快照，无法证明讨论没有推进题号。",
            ),
        )
    if outcome.task_type == "profile_ingest":
        return (_profile_ingest_evidence(outcome),)
    if outcome.task_type == "profile_assessment":
        return (
            _unprovable_rule(
                "profile.assessment_missing_semantics",
                "缺失、未记录与未评估的语义需要结构化 assessment scope 才能确定。",
            ),
        )
    if outcome.task_type == "profile_assistant":
        return (_profile_tool_budget(outcome),)
    if outcome.task_type == "profile_write_boundary":
        return (_profile_write_receipts(outcome), _profile_expected_versions(outcome))
    if outcome.task_type == "job_requirement_analysis":
        return (_job_source_locators(outcome), _job_inference_boundary(outcome))
    if outcome.task_type == "project_deep_dive_coaching":
        return (_project_gap_lifecycle(outcome),)
    if outcome.task_type == "project_question_generation":
        return (_project_question_catalog_links(outcome),)
    if outcome.task_type == "interview_retrospective":
        return (
            _retrospective_inferred_question_confirmation(outcome),
            _retrospective_analysis_grounding(outcome),
            _retrospective_discussion_result_isolation(outcome),
            _retrospective_history_source_coverage(outcome),
        )
    return ()


def _question_answer_boundary(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = []
    for item in outcome.items:
        basis = item.content.get("answer_basis")
        source = item.content.get("source_answer")
        supplemental = item.content.get("supplemental_answer")
        if basis == "mixed" and not (source and supplemental):
            invalid.append(item.item_id)
        elif basis == "source" and not source:
            invalid.append(item.item_id)
        elif basis == "model" and not supplemental:
            invalid.append(item.item_id)
    evidence = tuple(f"outcome-item:{item.item_id}" for item in outcome.items)
    if invalid:
        return _failed(
            "question.answer_provenance_separation",
            "答案来源声明与独立字段不一致：" + "、".join(invalid),
            evidence,
        )
    return _passed(
        "question.answer_provenance_separation",
        "原资料答案与 AI 补充按字段独立保存。",
        evidence or (f"outcome:{outcome.outcome_hash}",),
    )


def _question_zero_result(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    if outcome.items:
        return _passed(
            "question.zero_result_classification",
            "本次存在候选题，不适用零结果原因检查。",
            (f"outcome:{outcome.outcome_hash}",),
        )
    return _inconclusive(
        "question.zero_result_classification",
        "本次没有候选题，但结果投影未保存“确实无题、待人工复核或处理失败”的结构化原因。",
        (f"outcome:{outcome.outcome_hash}",),
        ("zero_result_reason_not_projected",),
    )


def _review_progression_guard(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    current_index = outcome.input.requested_scope.get("currentIndex")
    if not isinstance(current_index, int):
        return _inconclusive(
            "review.progression_guard",
            "缺少复习轮次 currentIndex，无法核对推进守卫。",
            (f"outcome:{outcome.outcome_hash}",),
            ("review_current_index_not_projected",),
        )
    completed = sum(
        bool(item.content.get("skipped"))
        or item.content.get("result_kind") in {
            "independent_mastery", "assisted_mastery", "revealed", "skipped"
        }
        for item in outcome.items
    )
    if current_index > completed:
        return _failed(
            "review.progression_guard",
            f"轮次已推进到 {current_index}，但只有 {completed} 道题满足通过或显式跳过条件。",
            tuple(f"review-attempt:{item.item_id}" for item in outcome.items),
        )
    return _passed(
        "review.progression_guard",
        "题号推进未越过已通过或显式跳过的题目数量。",
        tuple(f"review-attempt:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _profile_ingest_evidence(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [
        item.item_id
        for item in outcome.items
        if not any(provenance.evidence_refs for provenance in item.provenance)
    ]
    if invalid:
        return _failed(
            "profile.proposal_evidence",
            "画像建议缺少字段级 Evidence：" + "、".join(invalid),
            tuple(f"profile-proposal:{item}" for item in invalid),
        )
    return _passed(
        "profile.proposal_evidence",
        "画像建议均保留字段级 Evidence 引用。",
        tuple(f"profile-proposal:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _profile_tool_budget(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    tools = [unit.unit_type.removeprefix("tool:") for unit in outcome.units if unit.unit_type.startswith("tool:")]
    overused = sorted({name for name in tools if tools.count(name) > 2})
    if len(tools) > 6 or overused:
        detail = f"总调用 {len(tools)} 次"
        if overused:
            detail += "；重复超限：" + "、".join(overused)
        return _failed(
            "profile.tool_budget",
            detail,
            tuple(f"tool-audit:{unit.unit_id}" for unit in outcome.units),
        )
    return _passed(
        "profile.tool_budget",
        f"Tool 调用总数 {len(tools)}，未超过每轮与单工具预算。",
        tuple(f"tool-audit:{unit.unit_id}" for unit in outcome.units)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _profile_write_receipts(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [
        item.item_id for item in outcome.items
        if item.status == "completed" and not item.content.get("receipt_id")
    ]
    if invalid:
        return _failed(
            "profile.write_receipt_integrity",
            "已完成的画像写入项缺少 Receipt：" + "、".join(invalid),
            tuple(f"action-plan-item:{item}" for item in invalid),
        )
    return _passed(
        "profile.write_receipt_integrity",
        "已完成的画像写入项均关联稳定 Receipt。",
        tuple(f"action-plan-item:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _profile_expected_versions(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    guarded_operations = {"propose_claim_update", "propose_claim_reject"}
    invalid = [
        item.item_id for item in outcome.items
        if item.content.get("operation") in guarded_operations
        and item.content.get("expected_version") is None
    ]
    if invalid:
        return _failed(
            "profile.write_version_guard",
            "更新或拒绝现有 Claim 时缺少 expected version：" + "、".join(invalid),
            tuple(f"action-plan-item:{item}" for item in invalid),
        )
    return _passed(
        "profile.write_version_guard",
        "现有 Claim 的变更均携带 expected version。",
        tuple(f"action-plan-item:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _job_source_locators(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [item.item_id for item in outcome.items if item.content.get("locator_valid") is False]
    unknown = [item.item_id for item in outcome.items if item.content.get("locator_valid") is None]
    if invalid:
        return _failed(
            "job.source_locator_integrity",
            "岗位要求的原文 quote 与版本 offset 不一致：" + "、".join(invalid),
            tuple(f"job-requirement:{item}" for item in invalid),
        )
    if unknown:
        return _inconclusive(
            "job.source_locator_integrity",
            "部分岗位要求缺少可反查的正文或 offset。",
            tuple(f"job-requirement:{item}" for item in unknown),
            ("job_source_locator_missing",),
        )
    return _passed(
        "job.source_locator_integrity",
        "岗位要求 quote 与对应文档版本 offset 一致。",
        tuple(f"job-requirement:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _job_inference_boundary(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [
        item.item_id for item in outcome.items
        if item.content.get("inferred") is True
        and item.provenance
        and any(p.support_type != "inferred" for p in item.provenance)
    ]
    if invalid:
        return _failed(
            "job.inference_boundary",
            "推断准备建议被标记成显式岗位要求来源：" + "、".join(invalid),
            tuple(f"job-requirement:{item}" for item in invalid),
        )
    return _passed(
        "job.inference_boundary",
        "显式岗位要求与系统推断使用不同来源类型。",
        tuple(f"job-requirement:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _project_gap_lifecycle(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [
        item.item_id for item in outcome.items
        if item.item_type == "project_gap"
        and item.status == "resolved"
        and not item.content.get("resolution_ref")
    ]
    if invalid:
        return _failed(
            "project.gap_lifecycle",
            "已解决 Gap 缺少 resolution ref：" + "、".join(invalid),
            tuple(f"project-gap:{item}" for item in invalid),
        )
    return _passed(
        "project.gap_lifecycle",
        "已解决 Gap 均保留解决依据。",
        tuple(f"project-gap:{item.item_id}" for item in outcome.items if item.item_type == "project_gap")
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _project_question_catalog_links(outcome: BusinessOutcomeProjection) -> BusinessRuleResult:
    invalid = [
        item.item_id for item in outcome.items
        if item.status == "confirmed" and not item.content.get("review_candidate_id")
    ]
    if invalid:
        return _failed(
            "project.question_catalog_link",
            "已确认项目题没有关联题库候选：" + "、".join(invalid),
            tuple(f"project-question:{item}" for item in invalid),
        )
    return _passed(
        "project.question_catalog_link",
        "已确认项目题均可追溯到题库候选。",
        tuple(f"project-question:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _retrospective_inferred_question_confirmation(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    invalid = [
        item.item_id
        for item in outcome.items
        if item.item_type == "retrospective_question"
        and item.content.get("inferred") is True
        and item.user_decision.status == "pending"
    ]
    if invalid:
        return _failed(
            "retrospective.inferred_question_confirmation",
            "推断题尚未经过用户确认：" + "、".join(invalid),
            tuple(f"retrospective-question:{item}" for item in invalid),
        )
    return _passed(
        "retrospective.inferred_question_confirmation",
        "推断题均已确认，或本次没有推断题。",
        tuple(f"retrospective-question:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _retrospective_analysis_grounding(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    if outcome.input.requested_scope.get("mode") != "analysis":
        return _passed(
            "retrospective.analysis_grounding",
            "本次不是逐题分析运行，不适用分析依据检查。",
            (f"outcome:{outcome.outcome_hash}",),
        )
    invalid = [
        item.item_id
        for item in outcome.items
        if item.item_type == "retrospective_question"
        and not str(item.content.get("evidence") or "").strip()
    ]
    if invalid:
        return _failed(
            "retrospective.analysis_grounding",
            "逐题分析缺少可核对的回答证据：" + "、".join(invalid),
            tuple(f"retrospective-question:{item}" for item in invalid),
        )
    return _passed(
        "retrospective.analysis_grounding",
        "逐题分析均保留了可核对的回答证据。",
        tuple(f"retrospective-question:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _retrospective_discussion_result_isolation(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    if outcome.input.requested_scope.get("mode") != "discussion":
        return _passed(
            "retrospective.discussion_result_isolation",
            "本次不是复盘讨论运行，不适用讨论结果隔离检查。",
            (f"outcome:{outcome.outcome_hash}",),
        )
    invalid = [
        item.item_id
        for item in outcome.items
        if item.item_type != "discussion_message"
    ]
    if invalid:
        return _failed(
            "retrospective.discussion_result_isolation",
            "讨论运行写入了正式复盘结果项：" + "、".join(invalid),
            tuple(f"outcome-item:{item}" for item in invalid),
        )
    return _passed(
        "retrospective.discussion_result_isolation",
        "讨论运行只投影消息，没有改写正式逐题分析。",
        tuple(f"message:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _retrospective_history_source_coverage(
    outcome: BusinessOutcomeProjection,
) -> BusinessRuleResult:
    if outcome.input.requested_scope.get("mode") != "history":
        return _passed(
            "retrospective.history_source_coverage",
            "本次不是历史检索运行，不适用检索来源检查。",
            (f"outcome:{outcome.outcome_hash}",),
        )
    invalid = []
    for item in outcome.items:
        refs = {
            ref
            for provenance in item.provenance
            for ref in provenance.source_refs
        }
        if not any(ref.startswith("retrospective:") for ref in refs) or not any(
            ref.startswith("search-result:") for ref in refs
        ):
            invalid.append(item.item_id)
    if invalid:
        return _failed(
            "retrospective.history_source_coverage",
            "历史检索命中缺少场次或命中结果引用：" + "、".join(invalid),
            tuple(f"history-match:{item}" for item in invalid),
        )
    return _passed(
        "retrospective.history_source_coverage",
        "历史检索命中均保留了场次和结果引用。",
        tuple(f"history-match:{item.item_id}" for item in outcome.items)
        or (f"outcome:{outcome.outcome_hash}",),
    )


def _unprovable_rule(rule_id: str, summary: str) -> BusinessRuleResult:
    return _inconclusive(rule_id, summary, (), ("required_evidence_not_projected",))


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _passed(rule_id: str, summary: str, evidence: tuple[str, ...]) -> BusinessRuleResult:
    return BusinessRuleResult(rule_id, "passed", "none", summary, evidence)


def _failed(rule_id: str, summary: str, evidence: tuple[str, ...]) -> BusinessRuleResult:
    return BusinessRuleResult(rule_id, "failed", "high", summary, evidence)


def _inconclusive(
    rule_id: str,
    summary: str,
    evidence: tuple[str, ...],
    gaps: tuple[str, ...],
) -> BusinessRuleResult:
    return BusinessRuleResult(
        rule_id,
        "inconclusive",
        "medium",
        summary,
        evidence,
        gaps,
    )
