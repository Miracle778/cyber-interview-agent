from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


GateStatus = Literal[
    "disabled",
    "not_calibrated",
    "inconclusive",
    "passed",
    "blocked",
]


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    enabled: bool = False
    validated_rule_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class QualityGateDecision:
    status: GateStatus
    blocking: bool
    evaluated_rule_ids: tuple[str, ...]
    failed_rule_ids: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    summary: str


def evaluate_regression_quality_gate(
    *,
    policy: QualityGatePolicy,
    deterministic_comparison: Mapping[str, object] | None,
    infrastructure_failures: tuple[Mapping[str, object], ...] = (),
) -> QualityGateDecision:
    """Evaluate only pre-approved deterministic invariants.

    Pairwise Judge output, semantic ratings, user feedback, latency, and token
    metrics are intentionally not accepted by this boundary.
    """

    if not policy.enabled:
        return QualityGateDecision(
            status="disabled",
            blocking=False,
            evaluated_rule_ids=(),
            failed_rule_ids=(),
            evidence_gaps=(),
            summary="自动质量门禁未启用；回归结果仅供人工评估。",
        )
    validated = tuple(sorted(policy.validated_rule_ids))
    if not validated:
        return QualityGateDecision(
            status="not_calibrated",
            blocking=False,
            evaluated_rule_ids=(),
            failed_rule_ids=(),
            evidence_gaps=("no_validated_deterministic_rules",),
            summary="尚无完成真实案例校准和架构审批的确定性规则。",
        )
    if infrastructure_failures:
        return QualityGateDecision(
            status="inconclusive",
            blocking=False,
            evaluated_rule_ids=validated,
            failed_rule_ids=(),
            evidence_gaps=("regression_infrastructure_failure",),
            summary="回归运行存在基础设施失败，不能据此判断候选版本质量。",
        )
    candidate = _mapping(
        None if deterministic_comparison is None else deterministic_comparison.get("candidate")
    )
    raw_rules = candidate.get("rules")
    if not isinstance(raw_rules, (list, tuple)):
        return QualityGateDecision(
            status="inconclusive",
            blocking=False,
            evaluated_rule_ids=validated,
            failed_rule_ids=(),
            evidence_gaps=("candidate_deterministic_rules_missing",),
            summary="候选结果缺少确定性规则证据，不能执行门禁。",
        )
    indexed = {
        str(item.get("rule_id") or item.get("ruleId")): item
        for item in raw_rules
        if isinstance(item, Mapping)
    }
    missing = tuple(rule_id for rule_id in validated if rule_id not in indexed)
    inconclusive = tuple(
        rule_id
        for rule_id in validated
        if rule_id in indexed and indexed[rule_id].get("status") == "inconclusive"
    )
    if missing or inconclusive:
        return QualityGateDecision(
            status="inconclusive",
            blocking=False,
            evaluated_rule_ids=validated,
            failed_rule_ids=(),
            evidence_gaps=tuple(
                [*(f"missing:{item}" for item in missing),
                 *(f"inconclusive:{item}" for item in inconclusive)]
            ),
            summary="部分已批准规则缺少可判定证据，门禁保持不阻断。",
        )
    failed = tuple(
        rule_id
        for rule_id in validated
        if indexed[rule_id].get("status") == "failed"
    )
    if failed:
        return QualityGateDecision(
            status="blocked",
            blocking=True,
            evaluated_rule_ids=validated,
            failed_rule_ids=failed,
            evidence_gaps=(),
            summary="候选版本违反已校准并批准的确定性业务不变量。",
        )
    return QualityGateDecision(
        status="passed",
        blocking=False,
        evaluated_rule_ids=validated,
        failed_rule_ids=(),
        evidence_gaps=(),
        summary="候选版本通过全部已校准并批准的确定性业务不变量。",
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
