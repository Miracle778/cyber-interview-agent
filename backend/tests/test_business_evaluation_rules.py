from __future__ import annotations

from app.evaluation.business_rules import (
    RuleCalibrationCase,
    calibrate_business_rules,
    evaluate_common_business_rules,
)
from app.evaluation.outcomes import (
    BusinessOutcomePayload,
    OutcomeCounters,
    OutcomeIdentity,
    OutcomeInput,
    OutcomeItem,
    OutcomeProvenance,
    OutcomeUnit,
    OutcomeUserDecision,
    freeze_business_outcome,
)
from app.infrastructure.runtime_database import connect_runtime_database


def _outcome(*, total=1, completed=1, provenance=True):
    return freeze_business_outcome(
        BusinessOutcomePayload(
            task_type="question_curation",
            identity=OutcomeIdentity(
                workspace_id="workspace-1",
                session_id="session-1",
                execution_id="execution-1",
                graph_id="question.curate",
                domain_refs={"batchId": "batch-1"},
            ),
            input=OutcomeInput(
                source_refs=("source-1",),
                input_hash="a" * 64,
                requested_scope={"batchId": "batch-1"},
            ),
            execution_status="completed",
            terminal_state="review_pending",
            items=(
                OutcomeItem(
                    item_id="candidate-1",
                    item_type="question_candidate",
                    status="review_pending",
                    content={"question_text": "Redis 为什么快？"},
                    provenance=(
                        OutcomeProvenance(
                            field_path="content.questionText",
                            support_type="normalized",
                            source_refs=("source-1",) if provenance else (),
                        ),
                    ),
                    user_decision=OutcomeUserDecision(status="pending"),
                ),
            ),
            units=(
                OutcomeUnit(
                    unit_id="work-1",
                    unit_type="curation_discovery_work_item",
                    status="completed",
                ),
            ),
            unit_counters={
                "workItems": OutcomeCounters(
                    total=total,
                    completed=completed,
                    failed=0,
                    skipped=0,
                    pending=0,
                )
            },
        )
    )


def _connection(tmp_path):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'question.curate', 3, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('execution-1', 'session-1', 'completed', '{}')"
    )
    connection.commit()
    return connection


def test_business_rules_cite_domain_facts_and_keep_unprovable_rules_advisory(
    tmp_path,
) -> None:
    connection = _connection(tmp_path)
    try:
        result = evaluate_common_business_rules(
            _outcome(), connection=connection, workspace_id="workspace-1"
        )
        by_id = {item.rule_id: item for item in result.rules}

        assert by_id["runtime.workspace_ownership"].status == "passed"
        assert "agent_run:execution-1" in by_id[
            "runtime.workspace_ownership"
        ].evidence_refs
        assert by_id["runtime.count_conservation"].status == "passed"
        assert by_id["runtime.source_provenance"].status == "passed"
        assert by_id["runtime.late_result_protection"].status == "inconclusive"
        assert result.blocking is False
    finally:
        connection.close()


def test_business_rules_detect_count_and_source_invariant_violations(tmp_path) -> None:
    connection = _connection(tmp_path)
    try:
        count_result = evaluate_common_business_rules(
            _outcome(total=2, completed=1),
            connection=connection,
            workspace_id="workspace-1",
        )
        source_result = evaluate_common_business_rules(
            _outcome(provenance=False),
            connection=connection,
            workspace_id="workspace-1",
        )
        assert next(
            item for item in count_result.rules
            if item.rule_id == "runtime.count_conservation"
        ).status == "failed"
        assert next(
            item for item in source_result.rules
            if item.rule_id == "runtime.source_provenance"
        ).status == "failed"
    finally:
        connection.close()


def test_rule_calibration_reports_false_positive_and_negative_rates(tmp_path) -> None:
    connection = _connection(tmp_path)
    try:
        report = calibrate_business_rules(
            (
                RuleCalibrationCase(
                    case_id="positive",
                    outcome=_outcome(),
                    expected_failures=frozenset(),
                ),
                RuleCalibrationCase(
                    case_id="count-negative",
                    outcome=_outcome(total=2, completed=1),
                    expected_failures=frozenset({"runtime.count_conservation"}),
                ),
                RuleCalibrationCase(
                    case_id="ambiguous-source",
                    outcome=_outcome(provenance=False),
                    expected_failures=frozenset({"runtime.source_provenance"}),
                ),
            ),
            connection=connection,
            workspace_id="workspace-1",
        )
        assert report.case_count == 3
        assert report.false_positive_rate == 0
        assert report.false_negative_rate == 0
        assert report.blocking_recommended is False
    finally:
        connection.close()
