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
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('run-2', 'session-1', 'running')"
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


def test_fail_requeue_and_reattach_preserve_completed_items(
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
