from dataclasses import replace
from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.drafts import KnowledgeDraftRecord
from app.knowledge.publication import PublicationRecord
from app.review.errors import PublicationProjectionError
from app.review.models import (
    MasteryEntry,
    MasteryProjection,
    QuestionSnapshot,
    ReviewRoundSettings,
)
from app.review.repository import ReviewRepository
from app.review.selector import QuestionSelector
from app.review.service import (
    ConfirmedMasteryReport,
    ReviewDomainService,
    RoundRuntimeRef,
)


def _snapshot(question_id: str) -> QuestionSnapshot:
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


def _settings(*, mode: str = "random-mixed") -> ReviewRoundSettings:
    return ReviewRoundSettings(
        topics=(),
        difficulties=("medium",),
        mode=mode,
        question_count=1,
        allow_follow_up=True,
        seed=5,
        answer_model_id="model-1",
        reasoning_effort="none",
    )


def _runtime(tmp_path: Path):
    connection = connect_runtime_database(tmp_path)
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="question.curate",
        title="Curation",
        session_id="curation-session",
    )
    product.create_execution(
        "curation-session",
        input={},
        model_bindings={},
        execution_id="curation-execution",
    )
    return connection, product


def _seed_candidate(
    connection,
    repository: ReviewRepository,
    snapshot: QuestionSnapshot,
) -> tuple[KnowledgeDraftRecord, PublicationRecord]:
    suffix = snapshot.question_id
    draft_id = f"draft-{suffix}"
    publication_id = f"publication-{suffix}"
    action_id = f"action-{suffix}"
    batch_id = f"batch-{suffix}"
    repository.create_batch(
        workspace_id="w1",
        session_id="curation-session",
        run_id="curation-execution",
        source_refs=("source-1",),
        batch_id=batch_id,
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) "
        "VALUES (?, 'w1', 'curation-session', 'curation-execution', "
        "'knowledge.publish', '{}', '{}', 'approved', ?)",
        (action_id, f"key-{suffix}"),
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) "
        "VALUES (?, 'w1', 'curation-session', 'curation-execution', "
        "'review', 'question', ?, ?, ?, ?, 'published')",
        (
            draft_id,
            snapshot.document_id,
            snapshot.title,
            f"artifacts/review/drafts/{draft_id}.md",
            snapshot.content_hash,
        ),
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) "
        "VALUES (?, ?, ?, 1, ?, ?, ?, 'completed')",
        (
            publication_id,
            action_id,
            draft_id,
            snapshot.content_hash,
            snapshot.document_id,
            f"10_question_bank/{snapshot.document_id}.md",
        ),
    )
    connection.commit()
    repository.save_candidate(
        batch_id=batch_id,
        question=snapshot,
        draft_id=draft_id,
        status="review_pending",
        candidate_id=f"candidate-{suffix}",
    )
    draft = KnowledgeDraftRecord(
        id=draft_id,
        workspace_id="w1",
        session_id="curation-session",
        run_id="curation-execution",
        agent_type="question_generation",
        domain="review",
        document_type="question",
        document_id=snapshot.document_id,
        title=snapshot.title,
        markdown=f"# {snapshot.title}\n",
        content_path=f"artifacts/review/drafts/{draft_id}.md",
        source_refs=("source-1",),
        relation_refs=(),
        status="published",
        version=1,
        content_hash=snapshot.content_hash,
        created_at="2026-07-14 00:00:00",
        updated_at="2026-07-14 00:00:00",
    )
    publication = PublicationRecord(
        id=publication_id,
        action_id=action_id,
        draft_id=draft_id,
        expected_draft_version=1,
        expected_content_hash=snapshot.content_hash,
        document_id=snapshot.document_id,
        target_path=f"10_question_bank/{snapshot.document_id}.md",
        state="completed",
        result_hash=snapshot.content_hash,
        error_code=None,
        created_at="2026-07-14 00:00:00",
        updated_at="2026-07-14 00:00:00",
        completed_at="2026-07-14 00:00:00",
    )
    return draft, publication


def test_create_round_freezes_selection_and_returns_first_input(
    tmp_path: Path,
) -> None:
    connection, product = _runtime(tmp_path)
    repository = ReviewRepository(connection)
    draft, publication = _seed_candidate(connection, repository, _snapshot("a"))
    service_calls: list[str] = []

    def create_runtime(workspace_id: str, settings: ReviewRoundSettings):
        service_calls.append(workspace_id)
        product.create_session(
            workspace_id=workspace_id,
            kind="review.round",
            title="Review round",
            session_id="round-session",
        )
        product.create_execution(
            "round-session",
            input={},
            model_bindings={"answer_evaluation": settings.answer_model_id},
            execution_id="round-execution",
        )
        return RoundRuntimeRef("round-session", "round-execution")

    service = ReviewDomainService(
        repository=repository,
        selector=QuestionSelector(),
        create_round_runtime=create_runtime,
    )
    service.activate_published_draft(draft, publication)

    result = service.create_round(workspace_id="w1", settings=_settings())

    assert service_calls == ["w1"]
    assert result.round.question_snapshots[0].question_id == "a"
    assert result.input_request.prompt == "Explain a"
    assert result.round.mastery_before.version == 0
    connection.close()


def test_confirmed_recent_reports_drive_weak_point_selection(
    tmp_path: Path,
) -> None:
    connection, product = _runtime(tmp_path)
    repository = ReviewRepository(connection)
    for question_id in ("a", "b"):
        draft, publication = _seed_candidate(
            connection, repository, _snapshot(question_id)
        )
        ReviewDomainService(
            repository=repository,
            selector=QuestionSelector(),
            create_round_runtime=lambda *_: None,
        ).activate_published_draft(draft, publication)

    def create_runtime(workspace_id: str, _settings: ReviewRoundSettings):
        product.create_session(
            workspace_id=workspace_id,
            kind="review.round",
            title="Review round",
            session_id="round-session",
        )
        product.create_execution(
            "round-session",
            input={},
            model_bindings={},
            execution_id="round-execution",
        )
        return RoundRuntimeRef("round-session", "round-execution")

    reports = (
        ConfirmedMasteryReport(
            report_id="report-1",
            entries=(MasteryEntry(subject_id="b", state="weak"),),
        ),
    )
    service = ReviewDomainService(
        repository=repository,
        selector=QuestionSelector(),
        create_round_runtime=create_runtime,
        load_confirmed_mastery_reports=lambda _workspace, limit: reports[:limit],
    )

    result = service.create_round(
        workspace_id="w1", settings=_settings(mode="weak-point")
    )

    assert result.round.question_snapshots[0].question_id == "b"
    assert result.round.mastery_before.evidence_refs == ("report-1",)
    connection.close()


def test_publication_projection_rejects_mismatched_draft_hash(
    tmp_path: Path,
) -> None:
    connection, _product = _runtime(tmp_path)
    repository = ReviewRepository(connection)
    draft, publication = _seed_candidate(connection, repository, _snapshot("a"))
    service = ReviewDomainService(
        repository=repository,
        selector=QuestionSelector(),
        create_round_runtime=lambda *_: None,
    )

    with pytest.raises(PublicationProjectionError):
        service.activate_published_draft(
            replace(draft, content_hash="f" * 64),
            publication,
        )
    connection.close()


def test_published_mastery_proposal_updates_projection_with_cas(
    tmp_path: Path,
) -> None:
    connection, product = _runtime(tmp_path)
    repository = ReviewRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="review.round",
        title="Round",
        session_id="round-session",
    )
    product.create_execution(
        "round-session",
        input={},
        model_bindings={},
        execution_id="round-execution",
    )
    repository.create_round(
        workspace_id="w1",
        session_id="round-session",
        execution_id="round-execution",
        settings=_settings(),
        question_snapshots=(_snapshot("a"),),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-1",
    )
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) "
        "VALUES ('mastery-action', 'w1', 'round-session', 'round-execution', "
        "'knowledge.publish', '{}', '{}', 'approved', 'mastery-key')"
    )
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status) "
        "VALUES ('mastery-draft', 'w1', 'round-session', 'round-execution', "
        "'review', 'mastery_report', 'mastery-doc', 'Mastery', "
        "'artifacts/review/drafts/mastery.md', ?, 'published')",
        ("f" * 64,),
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) "
        "VALUES ('mastery-publication', 'mastery-action', 'mastery-draft', "
        "1, ?, 'mastery-doc', '40_mastery/mastery-doc.md', 'completed')",
        ("f" * 64,),
    )
    connection.commit()
    repository.save_report_proposal(
        draft_id="mastery-draft",
        round_id="round-1",
        report_kind="mastery_report",
        projection=MasteryProjection(
            workspace_id="w1",
            version=1,
            entries=(MasteryEntry(subject_id="a", state="stable"),),
            evidence_refs=("round-1",),
        ),
        expected_mastery_version=0,
    )
    draft = KnowledgeDraftRecord(
        id="mastery-draft",
        workspace_id="w1",
        session_id="round-session",
        run_id="round-execution",
        agent_type="report_summarization",
        domain="review",
        document_type="mastery_report",
        document_id="mastery-doc",
        title="Mastery",
        markdown="# Mastery\n",
        content_path="artifacts/review/drafts/mastery.md",
        source_refs=(),
        relation_refs=("round-1",),
        status="published",
        version=1,
        content_hash="f" * 64,
        created_at="2026-07-14 00:00:00",
        updated_at="2026-07-14 00:00:00",
    )
    publication = PublicationRecord(
        id="mastery-publication",
        action_id="mastery-action",
        draft_id=draft.id,
        expected_draft_version=1,
        expected_content_hash=draft.content_hash,
        document_id=draft.document_id,
        target_path="40_mastery/mastery-doc.md",
        state="completed",
        result_hash="f" * 64,
        error_code=None,
        created_at="2026-07-14 00:00:00",
        updated_at="2026-07-14 00:00:00",
        completed_at="2026-07-14 00:00:00",
    )
    service = ReviewDomainService(
        repository=repository,
        selector=QuestionSelector(),
        create_round_runtime=lambda *_: None,
    )

    service.activate_published_draft(draft, publication)

    assert repository.get_mastery("w1").entries[0].state == "stable"
    connection.close()
