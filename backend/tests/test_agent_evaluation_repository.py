from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.evaluation.repository import (
    AgentEvaluationRepository,
    EvaluationIdempotencyConflictError,
    ImmutableEvaluationError,
)
from app.infrastructure.runtime_database import connect_runtime_database


def _repository(tmp_path, workspace_id: str = "workspace-1"):
    connection = connect_runtime_database(tmp_path)
    return connection, AgentEvaluationRepository(connection, workspace_id)


def test_eval_run_idempotency_and_completed_snapshot_hash_are_immutable(
    tmp_path,
) -> None:
    connection, repository = _repository(tmp_path)
    try:
        created = repository.create_run(
            eval_run_id="eval-1",
            execution_id="execution-1",
            eval_pack_id="review.v1",
            eval_pack_version=1,
            trigger="manual",
            frozen_input_hash="a" * 64,
            snapshot_json='{"safe":true}',
            idempotency_key="manual-1",
        )
        replay = repository.create_run(
            eval_run_id="eval-other",
            execution_id="execution-1",
            eval_pack_id="review.v1",
            eval_pack_version=1,
            trigger="manual",
            frozen_input_hash="a" * 64,
            snapshot_json='{"safe":true}',
            idempotency_key="manual-1",
        )
        assert replay.id == created.id == "eval-1"

        repository.complete_run(
            "eval-1",
            deterministic_result_json='{"status":"passed"}',
            judge_result_json=None,
            status="completed",
        )
        with pytest.raises(ImmutableEvaluationError):
            repository.complete_run(
                "eval-1",
                deterministic_result_json='{"status":"changed"}',
                judge_result_json=None,
                status="completed",
            )
        with pytest.raises(EvaluationIdempotencyConflictError):
            repository.create_run(
                eval_run_id="eval-conflict",
                execution_id="execution-1",
                eval_pack_id="review.v1",
                eval_pack_version=1,
                trigger="manual",
                frozen_input_hash="b" * 64,
                snapshot_json='{"safe":true}',
                idempotency_key="manual-1",
            )
    finally:
        connection.close()


def test_workspace_isolation_feedback_versions_and_case_privacy(tmp_path) -> None:
    connection, repository = _repository(tmp_path)
    try:
        repository.create_run(
            eval_run_id="eval-1",
            execution_id="execution-1",
            eval_pack_id="review.v1",
            eval_pack_version=1,
            trigger="manual",
            frozen_input_hash="a" * 64,
            snapshot_json='{"safe":true}',
            idempotency_key="manual-1",
        )
        first = repository.add_feedback(
            eval_run_id="eval-1",
            feedback_id="feedback-1",
            verdict="incorrect",
            dimension_id="key_point_coverage",
            reason="证据引用不完整",
        )
        second = repository.add_feedback(
            eval_run_id="eval-1",
            feedback_id="feedback-2",
            verdict="accurate",
            dimension_id=None,
            reason=None,
        )
        assert [first.version, second.version] == [1, 2]

        case = repository.create_regression_case(
            case_id="case-1",
            source_eval_run_id="eval-1",
            execution_id="execution-1",
            eval_pack_id="review.v1",
            eval_pack_version=1,
            snapshot_hash="c" * 64,
            snapshot_json='{"metadataOnly":true}',
            expected_invariants_json='["status-stable"]',
            contains_private_bodies=False,
            redaction_summary="正文未保存",
        )
        assert case.contains_private_bodies is False
        assert case.case_contract_version == 1
        assert "private" not in case.snapshot_json.casefold()

        regression = repository.create_regression_run(
            run_id="regression-1",
            case_id=case.id,
            case_version=case.version,
            baseline_implementation_id="baseline@1",
            candidate_implementation_id="candidate@2",
            idempotency_key="case-1-run-1",
        )
        assert regression.status == "pending"
        assert repository.create_regression_run(
            run_id="ignored",
            case_id=case.id,
            case_version=case.version,
            baseline_implementation_id="baseline@1",
            candidate_implementation_id="candidate@2",
            idempotency_key="case-1-run-1",
        ).id == regression.id
        repository.mark_regression_running(regression.id)
        completed = repository.complete_regression_run(
            regression.id,
            status="completed",
            baseline_execution_id="baseline-execution",
            candidate_execution_id="candidate-execution",
            baseline_outcome_hash="d" * 64,
            candidate_outcome_hash="e" * 64,
            isolation_manifest_json='{"productionWrites":false}',
        )
        assert completed.status == "completed"
        assert completed.baseline_outcome_hash == "d" * 64
        with pytest.raises(ImmutableEvaluationError):
            repository.complete_regression_run(completed.id, status="failed")

        other = AgentEvaluationRepository(connection, "workspace-2")
        assert other.get_run("eval-1") is None
        assert other.list_feedback("eval-1") == ()
        assert other.list_regression_cases() == ()
    finally:
        connection.close()


def test_daily_cap_reservation_is_atomic_across_connections(tmp_path) -> None:
    first_connection, first = _repository(tmp_path)
    second_connection = connect_runtime_database(tmp_path)
    second = AgentEvaluationRepository(second_connection, "workspace-1")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda repository: repository.reserve_daily_slot(
                        "2026-07-30", cap=1
                    ),
                    (first, second),
                )
            )
        assert sorted(results) == [False, True]
        assert first.daily_count("2026-07-30") == 1
    finally:
        first_connection.close()
        second_connection.close()
