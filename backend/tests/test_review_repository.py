from dataclasses import replace
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.review.errors import InputAlreadyResolvedError, ReviewConflictError
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionSnapshot,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository


def _snapshot(question_id: str = "a") -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id=question_id,
        document_id=f"doc-{question_id}",
        content_hash=question_id[0] * 64,
        title=f"Question {question_id}",
        question_text=f"Explain {question_id}",
        reference_answer=f"Answer {question_id}",
        topics=("database",),
        difficulty="medium",
        key_points=("point",),
        follow_ups=("why",),
    )


def _settings(count: int = 1) -> ReviewRoundSettings:
    return ReviewRoundSettings(
        topics=(),
        difficulties=("medium",),
        mode="random-mixed",
        question_count=count,
        allow_follow_up=True,
        seed=7,
        answer_model_id="model-1",
        reasoning_effort="none",
    )


def _mastery(version: int = 0) -> MasteryProjection:
    return MasteryProjection(
        workspace_id="w1",
        version=version,
        entries=(),
        evidence_refs=(),
    )


def _connection(tmp_path: Path):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s1', 'w1', 'review.round', 1, 'Round')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r1', 's1', 'running')"
    )
    connection.commit()
    return connection


def _seed_publication(connection) -> None:
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) "
        "VALUES ('action-1', 'w1', 's1', 'r1', 'knowledge.publish', '{}', "
        "'{}', 'approved', 'action-key')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) "
        "VALUES ('draft-a', 'w1', 's1', 'r1', 'review', 'question', "
        "'doc-a', 'Question a', 'artifacts/review/drafts/a.md', ?, 'published')",
        ("a" * 64,),
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) "
        "VALUES ('publication-a', 'action-1', 'draft-a', 1, ?, 'doc-a', "
        "'10_question_bank/doc-a.md', 'completed')",
        ("a" * 64,),
    )
    connection.commit()


def test_batch_candidate_and_catalog_activation_are_idempotent(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    _seed_publication(connection)
    repository = ReviewRepository(connection)
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-1",
    )
    candidate = repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot(),
        draft_id="draft-a",
        status="review_pending",
        candidate_id="candidate-a",
    )

    first = repository.activate_question(
        candidate_id=candidate.id,
        workspace_id="w1",
        document_id="doc-a",
        draft_id="draft-a",
        publication_id="publication-a",
        content_hash="a" * 64,
    )
    second = repository.activate_question(
        candidate_id=candidate.id,
        workspace_id="w1",
        document_id="doc-a",
        draft_id="draft-a",
        publication_id="publication-a",
        content_hash="a" * 64,
    )

    assert first == second
    assert first.snapshot.question_id == "a"
    assert repository.get_candidate(candidate.id).status == "published"
    assert repository.list_active_questions("w1") == (first,)
    connection.close()


def test_round_persists_frozen_question_snapshots(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    round_record = repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=_settings(),
        question_snapshots=(_snapshot(),),
        mastery_before=_mastery(),
        round_id="round-1",
    )

    changed = replace(_snapshot(), question_text="Changed later")
    assert changed.question_text == "Changed later"
    assert repository.get_round(round_record.id).question_snapshots[
        0
    ].question_text == "Explain a"
    connection.close()


def test_input_resolution_is_idempotent_for_the_same_key(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=_settings(),
        question_snapshots=(_snapshot(),),
        mastery_before=_mastery(),
        round_id="round-1",
    )
    request = repository.create_input_request(
        round_id="round-1",
        ordinal=1,
        kind="answer",
        prompt="Explain a",
        request_id="input-1",
    )

    first = repository.resolve_input(
        request.id,
        idempotency_key="answer-key",
        value="My answer",
        receipt={"accepted": True},
        receipt_id="receipt-1",
    )
    second = repository.resolve_input(
        request.id,
        idempotency_key="answer-key",
        value="My answer",
        receipt={"accepted": True},
        receipt_id="ignored",
    )

    assert first == second
    assert repository.get_input_request(request.id).status == "resolved"
    with pytest.raises(InputAlreadyResolvedError):
        repository.resolve_input(
            request.id,
            idempotency_key="different-key",
            value="Another answer",
            receipt={"accepted": True},
        )
    connection.close()


def test_attempt_advance_and_cancel_use_compare_and_set(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=_settings(),
        question_snapshots=(_snapshot(),),
        mastery_before=_mastery(),
        round_id="round-1",
    )

    attempt_id = repository.save_attempt(
        round_id="round-1",
        ordinal=1,
        question_snapshot=_snapshot(),
        answer="answer",
        evaluation={"score": "partial"},
        mastery_suggestion="partial",
        attempt_id="attempt-1",
    )
    advanced = repository.advance_round(
        "round-1",
        expected_version=1,
        current_index=1,
        status="report_pending",
    )

    assert attempt_id == "attempt-1"
    assert advanced.current_index == 1
    assert advanced.status == "report_pending"
    with pytest.raises(ReviewConflictError):
        repository.advance_round(
            "round-1",
            expected_version=1,
            current_index=1,
            status="completed",
        )
    assert repository.cancel_round("round-1").status == "cancelled"
    assert repository.cancel_round("round-1").status == "cancelled"
    connection.close()


def test_mastery_projection_requires_expected_version(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    current = repository.get_mastery("w1")
    proposal = MasteryProjection(
        workspace_id="w1",
        version=1,
        entries=(MasteryEntry(subject_id="a", state="weak"),),
        evidence_refs=("report-1",),
    )

    updated = repository.update_mastery(proposal, expected_version=current.version)

    assert updated.version == 1
    assert updated.entries[0].state == "weak"
    with pytest.raises(ReviewConflictError):
        repository.update_mastery(proposal, expected_version=0)
    connection.close()
