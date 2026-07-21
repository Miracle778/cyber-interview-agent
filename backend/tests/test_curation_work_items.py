from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.review.errors import ReviewConflictError
from app.review.repository import ReviewRepository


@pytest.fixture
def repository(tmp_path: Path) -> ReviewRepository:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'question.curate', 1, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('run-2', 'session-1', 'running', "
        "'{\"batchId\":\"batch-1\",\"batch_id\":\"batch-1\"}')"
    )
    connection.commit()
    yield ReviewRepository(connection)
    connection.close()


@pytest.fixture
def batch(repository: ReviewRepository):
    return repository.create_batch(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id=None,
        source_refs=("source-1",),
        batch_id="batch-1",
    )


def test_plan_is_idempotent_for_same_digest_and_rejects_changed_input(
    repository: ReviewRepository, batch
) -> None:
    first = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("s1#section-0001",),
    )

    assert repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("s1#section-0001",),
    ) == first
    with pytest.raises(ReviewConflictError, match="curation work item input changed"):
        repository.plan_curation_work_item(
            batch_id=batch.id,
            stage="discovery",
            unit_index=0,
            input_digest="b" * 64,
            source_refs=("s1#section-0001",),
        )


def test_completed_item_cannot_be_restarted_or_overwritten(
    repository: ReviewRepository, batch
) -> None:
    item = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("s1#section-0001",),
    )
    running = repository.start_curation_work_item(item.id)
    completed = repository.complete_curation_work_item(
        running.id,
        output={
            "seeds": [
                {"question_text": "什么是 MVCC？", "source_ref": "s1#section-0001"}
            ]
        },
    )

    assert completed.attempt_count == 1
    assert repository.start_curation_work_item(completed.id) == completed
    with pytest.raises(ReviewConflictError):
        repository.complete_curation_work_item(completed.id, output={"seeds": []})


def test_fail_requeue_and_legacy_reattach_use_durable_resume_history(
    repository: ReviewRepository, batch
) -> None:
    completed = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("s1#section-0001",),
    )
    failed = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=1,
        input_digest="b" * 64,
        source_refs=("s1#section-0002",),
    )
    repository.complete_curation_work_item(
        repository.start_curation_work_item(completed.id).id,
        output={"seeds": []},
    )
    repository.fail_curation_work_item(
        repository.start_curation_work_item(failed.id).id,
        error_code="provider_timeout",
    )
    repository.update_batch_status(batch.id, "failed")

    retried = repository.reattach_batch_run(batch.id, "run-2")
    items = repository.list_curation_work_items(batch.id, stage="discovery")

    assert retried.run_id == "run-2"
    assert retried.status == "generating"
    assert retried.version == 3
    assert [
        tuple(row)
        for row in repository._connection.execute(
            "SELECT operation, execution_id, result_status "
            "FROM review_curation_control_receipts WHERE batch_id = ?",
            (batch.id,),
        ).fetchall()
    ] == [("resume", "run-2", "generating")]
    assert [
        tuple(row)
        for row in repository._connection.execute(
            "SELECT execution_id, ordinal, reason "
            "FROM review_curation_batch_attempts WHERE batch_id = ?",
            (batch.id,),
        ).fetchall()
    ] == [("run-2", 1, "failed")]
    assert [(item.status, item.attempt_count, item.last_error_code) for item in items] == [
        ("completed", 1, None),
        ("failed", 1, "provider_timeout"),
    ]


def test_running_items_are_requeued_with_stable_interruption_code(
    repository: ReviewRepository, batch
) -> None:
    item = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="enrichment",
        unit_index=0,
        input_digest="c" * 64,
        source_refs=("s1#section-0001",),
    )
    repository.start_curation_work_item(item.id)

    assert repository.requeue_running_curation_work_items(batch.id) == 1
    requeued = repository.list_curation_work_items(batch.id)[0]
    assert (requeued.status, requeued.last_error_code) == (
        "failed",
        "curation_interrupted",
    )


def test_pause_control_is_idempotent_and_advances_version_twice(
    repository: ReviewRepository, batch
) -> None:
    receipt = repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-request-0001",
        expected_version=batch.version,
    )

    assert repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-request-0001",
        expected_version=batch.version,
    ) == receipt
    paused = repository.finalize_batch_control(receipt.id)

    assert paused.status == "paused"
    assert paused.control_intent is None
    assert paused.version == batch.version + 2


def test_batch_control_rejects_changed_payload_and_stale_version(
    repository: ReviewRepository, batch
) -> None:
    repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="control-request-0001",
        expected_version=batch.version,
    )

    with pytest.raises(ReviewConflictError, match="control request changed"):
        repository.request_batch_control(
            batch.id,
            operation="terminate",
            idempotency_key="control-request-0001",
            expected_version=batch.version,
        )
    with pytest.raises(ReviewConflictError, match="question batch version changed"):
        repository.request_batch_control(
            batch.id,
            operation="terminate",
            idempotency_key="terminate-request-0001",
            expected_version=batch.version,
        )


def test_pause_control_intent_wins_over_late_failure(
    repository: ReviewRepository, batch
) -> None:
    receipt = repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-race-0001",
        expected_version=batch.version,
    )

    raced = repository.update_batch_status(
        batch.id, "failed", expected_run_id="run-2"
    )

    assert raced.status == "generating"
    assert raced.control_intent == "pause"
    assert raced.version == batch.version + 1
    paused = repository.finalize_batch_control(receipt.id)
    assert paused.status == "paused"
    assert paused.control_intent is None


def test_terminated_batch_is_absorbing_for_late_completion_and_failure(
    repository: ReviewRepository, batch
) -> None:
    receipt = repository.request_batch_control(
        batch.id,
        operation="terminate",
        idempotency_key="terminate-race-0001",
        expected_version=batch.version,
    )
    terminated = repository.finalize_batch_control(receipt.id)

    assert repository.update_batch_status(
        batch.id, "completed", expected_run_id="run-2"
    ) == terminated
    assert repository.update_batch_status(
        batch.id, "failed", expected_run_id="run-2"
    ) == terminated


def test_terminated_batch_cannot_resume(
    repository: ReviewRepository, batch
) -> None:
    receipt = repository.request_batch_control(
        batch.id,
        operation="terminate",
        idempotency_key="terminate-request-0001",
        expected_version=batch.version,
    )
    terminated = repository.finalize_batch_control(receipt.id)

    with pytest.raises(ReviewConflictError, match="question batch cannot be resumed"):
        repository.resume_curation_batch(
            terminated.id,
            execution_id="run-2",
            idempotency_key="resume-request-0001",
            expected_version=terminated.version,
            reason="paused",
        )


def test_resume_reuses_batch_and_records_idempotent_receipt(
    repository: ReviewRepository, batch
) -> None:
    repository.update_batch_status(batch.id, "failed")
    failed = repository.get_batch(batch.id)

    resumed = repository.resume_curation_batch(
        batch.id,
        execution_id="run-2",
        idempotency_key="resume-request-0001",
        expected_version=failed.version,
        reason="failed",
    )

    assert resumed.id == batch.id
    assert resumed.run_id == "run-2"
    assert resumed.status == "generating"
    assert resumed.version == failed.version + 1
    assert repository.resume_curation_batch(
        batch.id,
        execution_id="run-2",
        idempotency_key="resume-request-0001",
        expected_version=failed.version,
        reason="failed",
    ) == resumed


def test_resume_rejects_execution_owned_by_another_curation_session(
    repository: ReviewRepository, batch
) -> None:
    repository.update_batch_status(batch.id, "failed")
    failed = repository.get_batch(batch.id)
    repository._connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-2', 'workspace-1', 'question.curate', 1, 'Other')"
    )
    repository._connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('run-3', 'session-2', 'running', "
        "'{\"batchId\":\"batch-1\"}')"
    )
    repository._connection.commit()

    with pytest.raises(ReviewConflictError, match="does not belong to question batch"):
        repository.resume_curation_batch(
            batch.id,
            execution_id="run-3",
            idempotency_key="resume-unrelated-0001",
            expected_version=failed.version,
            reason="failed",
        )


def test_attempt_rejects_execution_without_immutable_batch_input(
    repository: ReviewRepository, batch
) -> None:
    repository._connection.execute(
        "UPDATE agent_runs SET input_json = '{\"batchId\":\"other-batch\"}' "
        "WHERE id = 'run-2'"
    )
    repository._connection.commit()

    with pytest.raises(ReviewConflictError, match="does not belong to question batch"):
        repository.record_curation_attempt(batch.id, "run-2", reason="initial")
    assert repository.curation_batch_timing(batch.id).cumulative_elapsed_ms == 0


def test_unrelated_active_execution_cannot_enter_attempt_history(
    repository: ReviewRepository, batch
) -> None:
    repository.record_curation_attempt(batch.id, "run-2", reason="initial")
    repository._connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-2', 'workspace-1', 'question.curate', 1, 'Other')"
    )
    repository._connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('run-3', 'session-2', 'running')"
    )
    repository._connection.commit()

    with pytest.raises(ReviewConflictError, match="does not belong to question batch"):
        repository.record_curation_attempt(batch.id, "run-3", reason="paused")


def test_legacy_reattach_cannot_reopen_completed_or_terminated_batch(
    repository: ReviewRepository, batch
) -> None:
    repository.update_batch_status(batch.id, "completed")
    completed = repository.get_batch(batch.id)

    with pytest.raises(ReviewConflictError, match="cannot be retried"):
        repository.reattach_batch_run(batch.id, "run-2")
    assert repository.get_batch(batch.id) == completed

    other = repository.create_batch(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id=None,
        source_refs=("source-1",),
        batch_id="batch-terminated",
    )
    receipt = repository.request_batch_control(
        other.id,
        operation="terminate",
        idempotency_key="terminate-legacy-0001",
        expected_version=other.version,
    )
    terminated = repository.finalize_batch_control(receipt.id)
    with pytest.raises(ReviewConflictError, match="cannot be retried"):
        repository.reattach_batch_run(other.id, "run-2")
    assert repository.get_batch(other.id) == terminated


def test_batch_timing_sums_execution_intervals_without_paused_gaps(
    repository: ReviewRepository, batch
) -> None:
    repository._connection.execute(
        "UPDATE agent_runs SET status = 'completed', "
        "started_at = '2026-07-22 00:00:00', finished_at = '2026-07-22 00:00:10' "
        "WHERE id = 'run-2'"
    )
    repository._connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, started_at, finished_at) VALUES "
        "('run-3', 'session-1', 'completed', '{\"batchId\":\"batch-1\"}', "
        "'2026-07-22 00:01:00', '2026-07-22 00:01:20')"
    )
    repository._connection.commit()
    repository.record_curation_attempt(batch.id, "run-2", reason="initial")
    repository.record_curation_attempt(batch.id, "run-3", reason="paused")

    timing = repository.curation_batch_timing(batch.id)

    assert timing.current_elapsed_ms == 20_000
    assert timing.cumulative_elapsed_ms == 30_000


def test_interrupted_work_item_restarts_but_completed_output_stays_immutable(
    repository: ReviewRepository, batch
) -> None:
    interrupted = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=("s1#section-0001",),
        processor_kind="model",
    )
    completed = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=1,
        input_digest="b" * 64,
        source_refs=("s1#section-0002",),
        processor_kind="deterministic",
    )
    repository.start_curation_work_item(interrupted.id)
    completed = repository.complete_curation_work_item(
        repository.start_curation_work_item(completed.id).id,
        output={"seeds": []},
    )

    assert repository.interrupt_running_curation_work_items(
        batch.id, error_code="curation_paused"
    ) == 1
    restarted = repository.start_curation_work_item(interrupted.id)

    assert (restarted.status, restarted.attempt_count) == ("running", 2)
    assert repository.start_curation_work_item(completed.id) == completed
    with pytest.raises(ReviewConflictError, match="output changed"):
        repository.complete_curation_work_item(
            completed.id,
            output={
                "seeds": [
                    {
                        "question_text": "What changed?",
                        "source_ref": "s1#section-0002",
                    }
                ]
            },
        )
