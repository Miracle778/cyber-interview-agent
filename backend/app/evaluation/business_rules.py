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
            "迟到结果保护需要状态转换历史或 Receipt；最终快照不能单独证明。",
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
