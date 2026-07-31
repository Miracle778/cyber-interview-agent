from app.evaluation.quality_gates import (
    QualityGatePolicy,
    evaluate_regression_quality_gate,
)


def _comparison(status: str):
    return {
        "candidate": {
            "rules": [
                {
                    "rule_id": "runtime.count_conservation",
                    "status": status,
                }
            ]
        },
        # A semantic Judge preference is deliberately irrelevant to the gate.
        "pairwise": {"winner": "candidate", "confidence": 1},
    }


def test_gate_is_disabled_by_default_and_has_no_implicit_rules() -> None:
    disabled = evaluate_regression_quality_gate(
        policy=QualityGatePolicy(),
        deterministic_comparison=_comparison("failed"),
    )
    uncalibrated = evaluate_regression_quality_gate(
        policy=QualityGatePolicy(enabled=True),
        deterministic_comparison=_comparison("failed"),
    )

    assert disabled.status == "disabled"
    assert disabled.blocking is False
    assert uncalibrated.status == "not_calibrated"
    assert uncalibrated.blocking is False


def test_only_validated_deterministic_failure_can_block() -> None:
    policy = QualityGatePolicy(
        enabled=True,
        validated_rule_ids=frozenset({"runtime.count_conservation"}),
    )

    blocked = evaluate_regression_quality_gate(
        policy=policy,
        deterministic_comparison=_comparison("failed"),
    )
    passed = evaluate_regression_quality_gate(
        policy=policy,
        deterministic_comparison=_comparison("passed"),
    )

    assert blocked.status == "blocked"
    assert blocked.blocking is True
    assert blocked.failed_rule_ids == ("runtime.count_conservation",)
    assert passed.status == "passed"
    assert passed.blocking is False


def test_infrastructure_or_missing_rule_evidence_never_blocks() -> None:
    policy = QualityGatePolicy(
        enabled=True,
        validated_rule_ids=frozenset({"runtime.count_conservation"}),
    )
    infrastructure = evaluate_regression_quality_gate(
        policy=policy,
        deterministic_comparison=_comparison("failed"),
        infrastructure_failures=({"code": "network_timeout"},),
    )
    missing = evaluate_regression_quality_gate(
        policy=policy,
        deterministic_comparison={"candidate": {"rules": []}},
    )

    assert infrastructure.status == "inconclusive"
    assert infrastructure.blocking is False
    assert missing.status == "inconclusive"
    assert missing.blocking is False
