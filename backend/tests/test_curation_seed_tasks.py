from hashlib import sha256
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
        "VALUES ('execution-1', 'session-1', 'completed')"
    )
    connection.commit()
    repo = ReviewRepository(connection)
    repo.create_batch(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id=None,
        source_refs=("source-1",),
        batch_id="batch-1",
    )
    yield repo
    connection.close()


def _plan(
    repository: ReviewRepository,
    *,
    ordinal: int = 0,
    question_text: str = "什么是 MVCC？",
    input_digest: str = "b" * 64,
):
    work_item = repository.plan_curation_work_item(
        batch_id="batch-1",
        stage="discovery",
        unit_index=ordinal,
        input_digest=chr(ord("a") + ordinal) * 64,
        source_refs=(f"source-1#section-{ordinal}",),
    )
    return repository.plan_curation_seed_task(
        batch_id="batch-1",
        discovery_work_item_id=work_item.id,
        seed_ordinal=ordinal,
        question_text=question_text,
        primary_source_ref=f"source-1#section-{ordinal}",
        source_refs=(f"source-1#section-{ordinal}",),
        input_digest=input_digest,
    )


def _candidate(label: str = "one") -> dict[str, object]:
    return {
        "title": label,
        "question_text": f"question-{label}",
        "reference_answer": f"answer-{label}",
        "topics": ["database"],
        "difficulty": "medium",
        "key_points": ["visibility"],
        "follow_ups": [],
        "source_refs": ["source-1#section-0"],
    }


def test_seed_key_is_stable_and_unique_inside_batch(
    repository: ReviewRepository,
) -> None:
    first = _plan(repository, ordinal=0)
    second = _plan(repository, ordinal=1)

    assert first.seed_key == sha256(
        f"batch-1{first.discovery_work_item_id}0source-1#section-0".encode()
    ).hexdigest()
    assert _plan(repository, ordinal=0).seed_key == first.seed_key
    assert second.seed_key != first.seed_key


def test_repeated_planning_rejects_changed_immutable_input(
    repository: ReviewRepository,
) -> None:
    original = _plan(repository)

    assert _plan(repository) == original
    with pytest.raises(ReviewConflictError, match="seed task input changed"):
        _plan(repository, question_text="changed")
    with pytest.raises(ReviewConflictError, match="seed task input changed"):
        _plan(repository, input_digest="c" * 64)


def test_automatic_claims_are_bounded_and_interrupted_requires_resume(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)

    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=3
    )[0]
    assert (running.status, running.automatic_attempt_count, running.version) == (
        "running",
        1,
        task.version + 1,
    )
    assert repository.interrupt_running_curation_seed_tasks(
        "batch-1", error_code="curation_interrupted"
    ) == 1
    interrupted = repository.get_curation_seed_task(task.id)
    assert (interrupted.status, interrupted.automatic_attempt_count) == (
        "interrupted",
        1,
    )
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=("interrupted",), limit=3
    ) == ()

    assert repository.resume_interrupted_curation_seed_tasks("batch-1") == 1
    resumed = repository.get_curation_seed_task(task.id)
    assert (resumed.status, resumed.automatic_attempt_count) == ("pending", 1)
    second = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=3
    )[0]
    assert second.automatic_attempt_count == 2
    repository.interrupt_running_curation_seed_tasks(
        "batch-1", error_code="curation_interrupted"
    )
    assert repository.resume_interrupted_curation_seed_tasks("batch-1") == 1
    exhausted = repository.get_curation_seed_task(task.id)
    assert (exhausted.status, exhausted.automatic_attempt_count) == ("skipped", 2)
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=3
    ) == ()


def test_batch_resume_requeues_interrupted_seed_before_scheduler_claim(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)
    repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )
    repository.interrupt_running_curation_seed_tasks(
        "batch-1", error_code="curation_interrupted"
    )
    execution_input = (
        '{"batchId":"batch-1","batch_id":"batch-1",'
        '"sourceRefs":["source-1"],"source_refs":["source-1"],'
        '"source_excerpts":["source-1:file.md\\noriginal"]}'
    )
    repository._connection.execute(
        "UPDATE agent_runs SET status = 'interrupted', input_json = ? "
        "WHERE id = 'execution-1'",
        (execution_input,),
    )
    repository._connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('execution-2', 'session-1', 'running', ?)",
        (execution_input,),
    )
    repository._connection.execute(
        "UPDATE review_question_batches SET run_id = 'execution-1', "
        "status = 'interrupted' WHERE id = 'batch-1'"
    )
    repository._connection.commit()

    batch = repository.get_batch("batch-1")
    statements: list[str] = []
    repository._connection.set_trace_callback(statements.append)
    try:
        repository.resume_curation_batch(
            batch.id,
            execution_id="execution-2",
            idempotency_key="resume-seeds-1",
            expected_version=batch.version,
            reason="interrupted",
        )
    finally:
        repository._connection.set_trace_callback(None)

    resumed = repository.get_curation_seed_task(task.id)
    assert (resumed.status, resumed.automatic_attempt_count) == ("pending", 1)
    seed_update = next(
        statement
        for statement in statements
        if statement.startswith("UPDATE review_curation_seed_tasks SET status")
    )
    assert "WHERE id =" in seed_update
    assert "version =" in seed_update
    assert "status =" in seed_update


def test_manual_interruption_resumes_as_skipped_not_automatic_work(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)
    automatic = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]
    skipped = repository.skip_curation_seed_task(
        task.id,
        expected_version=automatic.version,
        error_code="candidate_incomplete",
        normalization_issues=("missing_answer",),
    )
    receipt, _created = repository.begin_curation_seed_retry(
        task.id,
        expected_version=skipped.version,
        idempotency_key="manual-interruption-1",
        request_digest="f" * 64,
        execution_id="execution-1",
    )
    manual = repository.claim_manual_curation_seed_retry(
        receipt.id, expected_seed_version=skipped.version
    )

    assert repository.interrupt_running_curation_seed_tasks(
        "batch-1", error_code="curation_interrupted"
    ) == 1
    assert repository.get_curation_seed_retry_receipt(
        receipt.id
    ).result_status == "interrupted"
    assert repository.resume_interrupted_curation_seed_tasks("batch-1") == 1
    resumed = repository.get_curation_seed_task(task.id)
    assert (
        resumed.status,
        resumed.automatic_attempt_count,
        resumed.manual_attempt_count,
    ) == ("skipped", manual.automatic_attempt_count, 1)
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending", "retryable"), limit=1
    ) == ()


def test_bulk_interrupt_and_resume_use_row_version_and_status_cas(
    repository: ReviewRepository,
) -> None:
    first = _plan(repository, ordinal=0)
    second = _plan(repository, ordinal=1)
    repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=2
    )
    statements: list[str] = []
    repository._connection.set_trace_callback(statements.append)
    try:
        assert repository.interrupt_running_curation_seed_tasks(
            "batch-1", error_code="curation_interrupted"
        ) == 2
        assert repository.resume_interrupted_curation_seed_tasks("batch-1") == 2
    finally:
        repository._connection.set_trace_callback(None)

    seed_updates = [
        statement
        for statement in statements
        if statement.startswith("UPDATE review_curation_seed_tasks SET status")
    ]
    assert len(seed_updates) == 4
    assert all("WHERE id =" in statement for statement in seed_updates)
    assert all("version =" in statement for statement in seed_updates)
    assert all("status =" in statement for statement in seed_updates)
    assert repository.get_curation_seed_task(first.id).status == "pending"
    assert repository.get_curation_seed_task(second.id).status == "pending"


def test_bulk_interrupt_cas_mismatch_rolls_back_every_seed(
    repository: ReviewRepository,
) -> None:
    first = _plan(repository, ordinal=0)
    second = _plan(repository, ordinal=1)
    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=2
    )
    repository._connection.execute(
        "CREATE TEMP TRIGGER mutate_second_seed_version "
        "AFTER UPDATE OF status ON review_curation_seed_tasks "
        f"WHEN NEW.id = '{first.id}' AND NEW.status = 'interrupted' "
        "BEGIN UPDATE review_curation_seed_tasks SET version = version + 1 "
        f"WHERE id = '{second.id}'; END"
    )

    with pytest.raises(ReviewConflictError, match="interruption changed"):
        repository.interrupt_running_curation_seed_tasks(
            "batch-1", error_code="curation_interrupted"
        )

    after = repository.list_curation_seed_tasks("batch-1")
    assert [(task.status, task.version) for task in after] == [
        (task.status, task.version) for task in running
    ]


def test_retryable_is_claimed_once_and_second_content_failure_must_skip(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)
    first = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]
    retryable = repository.mark_curation_seed_retryable(
        task.id,
        expected_version=first.version,
        error_code="candidate_incomplete",
        normalization_issues=("missing_answer",),
    )
    second = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("retryable",), limit=1
    )[0]

    assert (retryable.status, second.automatic_attempt_count) == ("retryable", 2)
    with pytest.raises(ReviewConflictError, match="automatic retry limit"):
        repository.mark_curation_seed_retryable(
            task.id,
            expected_version=second.version,
            error_code="candidate_incomplete",
            normalization_issues=("missing_answer",),
        )
    skipped = repository.skip_curation_seed_task(
        task.id,
        expected_version=second.version,
        error_code="candidate_incomplete",
        normalization_issues=("missing_answer",),
    )
    assert skipped.status == "skipped"
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=("skipped",), limit=1
    ) == ()


@pytest.mark.parametrize("terminal_status", ["completed", "degraded"])
def test_completed_output_and_quality_are_immutable(
    repository: ReviewRepository, terminal_status: str
) -> None:
    task = _plan(repository)
    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]
    completed = repository.complete_curation_seed_task(
        task.id,
        expected_version=running.version,
        status=terminal_status,
        candidate=_candidate(),
        answer_basis="mixed",
        material_support="partial",
        needs_review=True,
        normalization_issues=("title_defaulted",),
    )

    with pytest.raises(ReviewConflictError):
        repository.complete_curation_seed_task(
            task.id,
            expected_version=completed.version,
            status=terminal_status,
            candidate=_candidate("changed"),
            answer_basis="source",
            material_support="sufficient",
            needs_review=False,
            normalization_issues=(),
        )
    assert repository.get_curation_seed_task(task.id) == completed
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=(terminal_status,), limit=1
    ) == ()


def test_manual_retry_receipt_is_idempotent_and_counts_separately(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)
    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]
    skipped = repository.skip_curation_seed_task(
        task.id,
        expected_version=running.version,
        error_code="candidate_incomplete",
        normalization_issues=("missing_answer",),
    )

    receipt, created = repository.begin_curation_seed_retry(
        task.id,
        expected_version=skipped.version,
        idempotency_key="retry-seed-1",
        request_digest="d" * 64,
        execution_id="execution-1",
    )
    assert created is True
    assert repository.begin_curation_seed_retry(
        task.id,
        expected_version=skipped.version,
        idempotency_key="retry-seed-1",
        request_digest="d" * 64,
        execution_id="execution-2",
    ) == (receipt, False)
    assert receipt.execution_id == "execution-1"
    with pytest.raises(ReviewConflictError, match="idempotency key changed"):
        repository.begin_curation_seed_retry(
            task.id,
            expected_version=skipped.version,
            idempotency_key="retry-seed-1",
            request_digest="e" * 64,
            execution_id="execution-1",
        )

    manual = repository.claim_manual_curation_seed_retry(
        receipt.id, expected_seed_version=skipped.version
    )
    assert (manual.status, manual.automatic_attempt_count, manual.manual_attempt_count) == (
        "running",
        1,
        1,
    )
    assert repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending", "retryable"), limit=1
    ) == ()


def test_stale_expected_version_raises_conflict(repository: ReviewRepository) -> None:
    task = _plan(repository)
    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]

    with pytest.raises(ReviewConflictError, match="version changed"):
        repository.skip_curation_seed_task(
            task.id,
            expected_version=task.version,
            error_code="candidate_incomplete",
            normalization_issues=(),
        )
    assert repository.get_curation_seed_task(task.id) == running


def test_provider_exception_text_is_never_exposed_as_error_code(
    repository: ReviewRepository,
) -> None:
    task = _plan(repository)
    running = repository.claim_curation_seed_tasks(
        "batch-1", statuses=("pending",), limit=1
    )[0]
    with pytest.raises(ValueError, match="stable and bounded"):
        repository.mark_curation_seed_retryable(
            task.id,
            expected_version=running.version,
            error_code="ProviderError: secret response body",
            normalization_issues=(),
        )

    repository._connection.execute(
        "UPDATE review_curation_seed_tasks SET last_error_code = ? WHERE id = ?",
        ("ProviderError: secret response body", task.id),
    )
    repository._connection.commit()
    assert (
        repository.get_curation_seed_task(task.id).last_error_code
        == "curation_provider_error"
    )
