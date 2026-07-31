from __future__ import annotations

from app.evaluation.business_rules import (
    RuleCalibrationCase,
    calibrate_business_rules,
    evaluate_business_rules,
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


def test_task_rules_detect_known_business_invariant_violations(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    cases = (
        (
            "question_curation", "question.curate",
            {"answer_basis": "mixed", "source_answer": None, "supplemental_answer": None},
            "question.answer_provenance_separation",
        ),
        (
            "review_round", "review.round",
            {"result_kind": None, "skipped": False},
            "review.progression_guard",
        ),
        (
            "job_requirement_analysis", "job.analysis",
            {"locator_valid": False, "inferred": False},
            "job.source_locator_integrity",
        ),
        (
            "profile_write_boundary", "profile.manage",
            {"operation": "propose_claim_update", "expected_version": None, "receipt_id": None},
            "profile.write_receipt_integrity",
        ),
        (
            "project_deep_dive_coaching", "project.deep_dive",
            {"resolution_ref": None},
            "project.gap_lifecycle",
        ),
        (
            "project_question_generation", "project.deep_dive",
            {"review_candidate_id": None},
            "project.question_catalog_link",
        ),
    )
    try:
        for index, (task_type, graph_id, content, expected_rule) in enumerate(cases):
            session_id = f"session-task-{index}"
            execution_id = f"execution-task-{index}"
            connection.execute(
                "INSERT INTO agent_sessions "
                "(id, workspace_id, graph_id, graph_version, title) "
                "VALUES (?, 'workspace-1', ?, 1, 'Task rule')",
                (session_id, graph_id),
            )
            connection.execute(
                "INSERT INTO agent_runs (id, session_id, status, input_json) "
                "VALUES (?, ?, 'completed', '{}')",
                (execution_id, session_id),
            )
            status = (
                "completed" if task_type == "profile_write_boundary"
                else "resolved" if task_type == "project_deep_dive_coaching"
                else "confirmed" if task_type == "project_question_generation"
                else "pending"
            )
            requested_scope = {"currentIndex": 1} if task_type == "review_round" else {}
            item_type = "project_gap" if task_type == "project_deep_dive_coaching" else "item"
            outcome = freeze_business_outcome(
                BusinessOutcomePayload(
                    task_type=task_type,
                    identity=OutcomeIdentity(
                        workspace_id="workspace-1",
                        session_id=session_id,
                        execution_id=execution_id,
                        graph_id=graph_id,
                        domain_refs={},
                    ),
                    input=OutcomeInput(
                        source_refs=("source-1",),
                        input_hash="a" * 64,
                        requested_scope=requested_scope,
                    ),
                    execution_status="completed",
                    terminal_state="completed",
                    items=(
                        OutcomeItem(
                            item_id=f"item-{index}",
                            item_type=item_type,
                            status=status,
                            content=content,
                            provenance=(
                                OutcomeProvenance(
                                    field_path="content.value",
                                    support_type="normalized",
                                    source_refs=("source-1",),
                                ),
                            ),
                            user_decision=OutcomeUserDecision(status="pending"),
                        ),
                    ),
                    units=(),
                    unit_counters={
                        "items": OutcomeCounters(
                            total=1, completed=0, failed=0, skipped=0, pending=1
                        )
                    },
                )
            )
            result = evaluate_business_rules(
                outcome, connection=connection, workspace_id="workspace-1"
            )
            by_id = {item.rule_id: item for item in result.rules}
            assert by_id[expected_rule].status == "failed"
            assert result.blocking is False
    finally:
        connection.close()
