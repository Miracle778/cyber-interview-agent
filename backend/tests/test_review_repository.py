import asyncio
import json
import sqlite3
import threading
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.db.connection import connect_index
from app.hitl.models import CreatePendingAction
from app.hitl.repository import PendingActionRepository
from app.knowledge.drafts import (
    DraftNotEditableError,
    DraftVersionChangedError,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.publication import PublicationService
from app.review.errors import InputAlreadyResolvedError, ReviewConflictError
from app.review.coverage import KeyPointCoverage
from app.review.models import (
    CurationSummary,
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


def _connection(tmp_path: Path, *, graph_id: str = "review.round"):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s1', 'w1', ?, 1, 'Round')",
        (graph_id,),
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


def _finalization_candidate(
    *,
    candidate_id: str = "candidate-final",
    draft_id: str = "draft-final",
    run_id: str = "r1",
    document_id: str | None = None,
    question_id: str = "final",
    revision_candidate_id: str | None = None,
    expected_revision_draft_id: str | None = None,
    expected_revision_draft_version: int | None = None,
    expected_revision_draft_hash: str | None = None,
) -> dict[str, object]:
    resolved_document_id = document_id or f"doc-{draft_id}"
    result: dict[str, object] = {
        "candidate_id": candidate_id,
        "draft_id": draft_id,
        "draft": {
            "workspace_id": "w1",
            "session_id": "s1",
            "run_id": run_id,
            "agent_type": "review.question_curation",
            "domain": "review",
            "document_type": "question",
            "document_id": resolved_document_id,
            "title": f"Question {draft_id}",
            "content_path": f"artifacts/review/drafts/{draft_id}.md",
            "source_refs": ("source-1#fragment-1",),
            "relation_refs": ("database",),
            "content_hash": "d" * 64,
        },
        "question": replace(
            _snapshot(question_id),
            document_id=resolved_document_id,
            content_hash="d" * 64,
        ),
        "source_refs": ("source-1#fragment-1",),
        "correction_note": "",
        "duplicate_of_question_id": None,
        "source_links": (
            {
                "link_id": f"link-{candidate_id}",
                "question_id": question_id,
                "source_id": "source-1",
                "evidence_ref": "source-1#fragment-1",
                "merge_reason": "generated_from_source",
            },
        ),
    }
    if revision_candidate_id is not None:
        result.update(
            {
                "revision_candidate_id": revision_candidate_id,
                "expected_revision_draft_id": expected_revision_draft_id,
                "expected_revision_draft_version": (
                    expected_revision_draft_version
                ),
                "expected_revision_draft_hash": expected_revision_draft_hash,
            }
        )
    return result


def _seed_question_draft(
    connection,
    draft_id: str,
    *,
    run_id: str = "r1",
    document_id: str = "doc-base",
    content_hash: str = "b" * 64,
    version: int = 1,
) -> None:
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, domain, document_type, "
        "document_id, title, content_path, content_hash, status, version) "
        "VALUES (?, 'w1', 's1', ?, 'review', 'question', ?, 'Base', ?, ?, "
        "'review_pending', ?)",
        (
            draft_id,
            run_id,
            document_id,
            f"artifacts/review/drafts/{draft_id}.md",
            content_hash,
            version,
        ),
    )
    connection.commit()


def _register_staging(
    connection,
    *,
    batch_id: str,
    execution_id: str,
    candidates: tuple[dict[str, object], ...],
    write_artifacts: bool = True,
) -> None:
    database_path = Path(
        connection.execute("PRAGMA database_list").fetchone()[2]
    )
    workspace_root = database_path.parents[1]
    for item in candidates:
        draft = item["draft"]
        assert isinstance(draft, dict)
        if write_artifacts:
            content = f"# staged {item['draft_id']}\n".encode()
            digest = sha256(content).hexdigest()
            draft["content_hash"] = digest
            question = item["question"]
            assert isinstance(question, QuestionSnapshot)
            item["question"] = replace(question, content_hash=digest)
            path = workspace_root / str(draft["content_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        connection.execute(
            "INSERT INTO review_curation_staged_drafts "
            "(draft_id, batch_id, execution_id, content_path, content_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item["draft_id"],
                batch_id,
                execution_id,
                draft["content_path"],
                draft["content_hash"],
            ),
        )
    connection.commit()


def _validated_repository(
    tmp_path: Path, connection
) -> ReviewRepository:
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    return ReviewRepository(
        connection,
        validate_curation_artifact=drafts.validate_curation_artifact,
    )


def _finalized_question_revision(tmp_path: Path):
    connection = _connection(tmp_path, graph_id="question.revise")
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    origin = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-origin-revision-decision",
    )
    _seed_question_draft(connection, "draft-base-revision-decision")
    repository.save_candidate(
        batch_id=origin.id,
        question=replace(
            _snapshot("base"),
            document_id="doc-base",
            content_hash="b" * 64,
        ),
        draft_id="draft-base-revision-decision",
        source_refs=("source-1#fragment-1",),
        status="review_pending",
        candidate_id="candidate-revision-decision",
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r2', 's1', 'running')"
    )
    connection.commit()
    rewrite = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r2",
        source_refs=("source-1",),
        rewrite_of_batch_id=origin.id,
        batch_id="batch-rewrite-decision",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=rewrite.id,
    )
    repository.claim_curation_finalization(rewrite.id, "r2")
    revision = _finalization_candidate(
        candidate_id="candidate-revision-decision",
        draft_id="draft-revision-decision",
        run_id="r2",
        document_id="doc-base",
        question_id="base",
        revision_candidate_id="candidate-revision-decision",
        expected_revision_draft_id="draft-base-revision-decision",
        expected_revision_draft_version=1,
        expected_revision_draft_hash="b" * 64,
    )
    revision["draft"] = {
        **revision["draft"],  # type: ignore[arg-type]
        "version": 2,
    }
    _register_staging(
        connection,
        batch_id=rewrite.id,
        execution_id="r2",
        candidates=(revision,),
    )
    persisted = repository.finalize_curation_candidates(
        rewrite.id,
        "r2",
        candidates=(revision,),
    )[0]
    return connection, repository, origin, rewrite, persisted


def _seed_completed_publication_for_draft(
    connection,
    *,
    draft_id: str,
    publication_id: str,
    document_id: str,
    content_hash: str,
    expected_version: int,
) -> None:
    action_id = f"action-{publication_id}"
    connection.execute(
        "INSERT INTO pending_actions "
        "(id, workspace_id, session_id, run_id, action_type, payload_json, "
        "preview_json, status, idempotency_key) "
        "VALUES (?, 'w1', 's1', 'r2', 'knowledge.publish', '{}', '{}', "
        "'approved', ?)",
        (action_id, f"key-{publication_id}"),
    )
    connection.execute(
        "INSERT INTO publication_runs "
        "(id, action_id, draft_id, expected_draft_version, "
        "expected_content_hash, document_id, target_path, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'completed')",
        (
            publication_id,
            action_id,
            draft_id,
            expected_version,
            content_hash,
            document_id,
            f"10_question_bank/{document_id}.md",
        ),
    )
    connection.execute(
        "UPDATE knowledge_drafts SET status = 'published' WHERE id = ?",
        (draft_id,),
    )
    connection.commit()


def test_curation_context_round_trips_with_compare_and_swap(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )

    initial = repository.get_or_create_curation_context("s1")
    saved = repository.replace_curation_context(
        "s1",
        expected_version=initial.version,
        focused_candidate_ids=("candidate-6",),
        last_intent="inspect",
        last_result_candidate_ids=("candidate-6",),
        dialogue_summary={
            "text": "用户正在查看第 6 题",
            "resourceRefs": ["candidate:candidate-6"],
            "decisions": [],
            "openItems": ["等待用户确认"],
        },
        summarized_through_message_id="message-8",
    )

    assert saved.version == 1
    assert saved.focused_candidate_ids == ("candidate-6",)
    assert saved.last_intent == "inspect"
    assert saved.dialogue_summary["resourceRefs"] == [
        "candidate:candidate-6"
    ]
    assert saved.summarized_through_message_id == "message-8"
    assert repository.get_or_create_curation_context("s1") == saved

    with pytest.raises(
        ReviewConflictError, match="curation context version changed"
    ):
        repository.replace_curation_context(
            "s1",
            expected_version=initial.version,
            focused_candidate_ids=(),
            last_intent=None,
            last_result_candidate_ids=(),
            dialogue_summary={},
            summarized_through_message_id=None,
        )
    connection.close()


def test_curation_command_receipt_can_be_found_before_interpretation(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )

    assert (
        repository.find_curation_command_receipt(
            session_id="s1",
            idempotency_key="command-1",
            text="发布第 1 题",
            summary_version=0,
        )
        is None
    )
    created, is_new = repository.begin_curation_command(
        session_id="s1",
        idempotency_key="command-1",
        text="发布第 1 题",
        summary_version=0,
        command={"kind": "confirm", "candidateIds": ["candidate-1"]},
    )

    assert is_new is True
    assert repository.find_curation_command_receipt(
        session_id="s1",
        idempotency_key="command-1",
        text="发布第 1 题",
        summary_version=0,
    ) == created
    with pytest.raises(
        ReviewConflictError, match="curation command idempotency key changed"
    ):
        repository.find_curation_command_receipt(
            session_id="s1",
            idempotency_key="command-1",
            text="拒绝第 1 题",
            summary_version=0,
        )
    connection.close()


def test_curation_command_links_execution_and_tracks_lifecycle(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    receipt, created = repository.begin_curation_command(
        session_id="s1",
        idempotency_key="command-async-1",
        text="给出建议",
        summary_version=0,
        command={"kind": "pending", "candidateIds": []},
    )

    attached = repository.attach_curation_command_execution(
        receipt.id, "r1"
    )
    running = repository.transition_curation_command_lifecycle(
        receipt.id, expected=("accepted",), target="running"
    )

    assert created is True
    assert attached.execution_id == "r1"
    assert running.lifecycle_status == "running"
    connection.close()


def test_bulk_publication_persists_item_progress_and_retries_only_failures(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
    )
    repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("a"),
        draft_id=None,
        candidate_id="candidate-a",
    )
    repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("b"),
        draft_id=None,
        candidate_id="candidate-b",
    )
    operation, created = repository.create_bulk_publication(
        session_id="s1",
        summary_version=1,
        idempotency_key="bulk-operation-1",
        candidate_ids=("candidate-a", "candidate-b"),
        operation_id="bulk-1",
    )
    repository.attach_bulk_publication_execution(operation.id, "r1")
    repository.transition_bulk_publication(
        operation.id, expected=("accepted",), target="running"
    )
    first, second = repository.list_bulk_publication_items(operation.id)
    repository.transition_bulk_publication_item(
        first.id, expected=("pending",), target="running"
    )
    repository.transition_bulk_publication_item(
        first.id, expected=("running",), target="completed"
    )
    repository.transition_bulk_publication_item(
        second.id, expected=("pending",), target="running"
    )
    repository.transition_bulk_publication_item(
        second.id,
        expected=("running",),
        target="failed",
        error_code="publication_failed",
    )
    partial = repository.complete_bulk_publication_from_items(operation.id)

    assert created is True
    assert partial.status == "partial_failure"
    assert first.idempotency_key == "bulk-publish:bulk-1:candidate-a"
    connection.execute(
        "UPDATE agent_runs SET status = 'completed' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r2', 's1', 'running')"
    )
    connection.commit()
    retried, is_new_retry = repository.requeue_bulk_publication(
        operation.id,
        execution_id="r2",
        idempotency_key="bulk-retry-1",
    )
    retried_items = repository.list_bulk_publication_items(operation.id)

    assert is_new_retry is True
    assert retried.retry_count == 1
    assert [item.status for item in retried_items] == ["completed", "pending"]
    assert retried_items[0].idempotency_key == first.idempotency_key
    connection.close()


def test_latest_bulk_publication_is_scoped_to_the_curation_session(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s2', 'w1', 'question.curation', 1, 'Other')"
    )
    connection.commit()
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s2",
        source_refs=("source-2",),
    )
    first, _ = repository.create_bulk_publication(
        session_id="s1",
        summary_version=1,
        idempotency_key="bulk-1",
        candidate_ids=(),
    )
    second, _ = repository.create_bulk_publication(
        session_id="s1",
        summary_version=2,
        idempotency_key="bulk-2",
        candidate_ids=(),
    )
    repository.create_bulk_publication(
        session_id="s2",
        summary_version=1,
        idempotency_key="bulk-other",
        candidate_ids=(),
    )

    assert repository.get_latest_bulk_publication("s1").id == second.id
    assert repository.get_latest_bulk_publication("missing") is None
    assert first.id != second.id
    connection.close()


def test_bulk_publication_reconciliation_requeues_terminal_running_item(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
    )
    repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("a"),
        draft_id=None,
        candidate_id="candidate-a",
    )
    operation, _created = repository.create_bulk_publication(
        session_id="s1",
        summary_version=1,
        idempotency_key="bulk-operation-interrupted",
        candidate_ids=("candidate-a",),
        operation_id="bulk-interrupted",
    )
    repository.attach_bulk_publication_execution(operation.id, "r1")
    repository.transition_bulk_publication(
        operation.id, expected=("accepted",), target="running"
    )
    item = repository.list_bulk_publication_items(operation.id)[0]
    repository.transition_bulk_publication_item(
        item.id, expected=("pending",), target="running"
    )
    repository.transition_bulk_publication(
        operation.id, expected=("running",), target="cancelled"
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'cancelled' WHERE id = 'r1'"
    )
    connection.commit()

    reconciled = repository.reconcile_bulk_publication(operation.id)

    assert reconciled.status == "cancelled"
    assert repository.list_bulk_publication_items(operation.id)[0].status == (
        "pending"
    )
    connection.close()


def test_batch_candidate_and_catalog_activation_are_idempotent(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    _seed_publication(connection)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-1",
    )
    repository.update_curation_progress(
        "s1",
        stage="waiting_for_command",
        completed_units=1,
        total_units=1,
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
    published_candidate = repository.get_candidate(candidate.id)
    assert published_candidate.status == "published"
    assert published_candidate.confirmation_status == "confirmed"
    assert published_candidate.confirmation_version == 1
    assert published_candidate.confirmed_at is not None
    assert repository.list_active_questions("w1") == (first,)
    assert repository.get_batch(batch.id).status == "completed"
    assert repository.get_batch(batch.id).version == batch.version + 1
    assert repository.get_curation_session("s1").stage == "completed"
    connection.close()


def test_curation_batch_completes_only_after_last_candidate_is_rejected(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-1",
    )
    repository.update_curation_progress(
        "s1",
        stage="waiting_for_command",
        completed_units=2,
        total_units=2,
    )
    first = repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("a"),
        draft_id=None,
        status="review_pending",
        candidate_id="candidate-a",
    )
    second = repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("b"),
        draft_id=None,
        status="review_pending",
        candidate_id="candidate-b",
    )

    repository.update_candidate_status(first.id, status="rejected")

    assert repository.get_batch(batch.id).status == "review_pending"
    assert repository.get_batch(batch.id).version == batch.version
    assert (
        repository.get_curation_session("s1").stage
        == "waiting_for_command"
    )

    repository.update_candidate_status(second.id, status="rejected")

    assert repository.get_batch(batch.id).status == "completed"
    assert repository.get_batch(batch.id).version == batch.version + 1
    assert repository.get_curation_session("s1").stage == "completed"
    connection.close()


def test_formal_candidate_rejection_completes_curation_batch(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    _seed_question_draft(connection, "draft-a")
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-1",
    )
    repository.update_curation_progress(
        "s1",
        stage="waiting_for_command",
        completed_units=1,
        total_units=1,
    )
    repository.save_candidate(
        batch_id=batch.id,
        question=_snapshot("a"),
        draft_id="draft-a",
        status="review_pending",
        candidate_id="candidate-a",
    )

    rejected = repository.reject_candidate_for_draft(
        "draft-a",
        reason="用户拒绝",
        rejected_at="2026-07-22T12:00:00+08:00",
        action_id="action-reject-a",
    )

    assert rejected is not None
    assert rejected.status == "rejected"
    assert repository.get_batch(batch.id).status == "completed"
    assert repository.get_curation_session("s1").stage == "completed"
    connection.close()


def test_concurrent_last_candidate_decisions_complete_batch_once(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1",),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-1",
    )
    repository.update_curation_progress(
        "s1",
        stage="waiting_for_command",
        completed_units=2,
        total_units=2,
    )
    for suffix in ("a", "b"):
        repository.save_candidate(
            batch_id=batch.id,
            question=_snapshot(suffix),
            draft_id=None,
            status="review_pending",
            candidate_id=f"candidate-{suffix}",
        )

    first_connection = connect_runtime_database(tmp_path)
    second_connection = connect_runtime_database(tmp_path)
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def reject(candidate_id: str, worker_connection) -> None:
        try:
            barrier.wait()
            ReviewRepository(worker_connection).update_candidate_status(
                candidate_id,
                status="rejected",
            )
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    first_thread = threading.Thread(
        target=reject,
        args=("candidate-a", first_connection),
    )
    second_thread = threading.Thread(
        target=reject,
        args=("candidate-b", second_connection),
    )
    first_thread.start()
    second_thread.start()
    barrier.wait()
    first_thread.join()
    second_thread.join()

    assert errors == []
    completed = repository.get_batch(batch.id)
    assert completed.status == "completed"
    assert completed.version == batch.version + 1
    assert repository.get_curation_session("s1").stage == "completed"

    repository.update_candidate_status("candidate-a", status="rejected")

    assert repository.get_batch(batch.id).version == completed.version
    first_connection.close()
    second_connection.close()
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


def test_round_list_projects_session_archive_state(tmp_path: Path) -> None:
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
    connection.execute(
        "UPDATE agent_sessions SET deleted_at = '2026-07-19 10:00:00' WHERE id = 's1'"
    )
    connection.commit()

    rounds = repository.list_rounds("w1")

    assert len(rounds) == 1
    assert rounds[0].archived_at == "2026-07-19 10:00:00"
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


def test_curation_session_progress_summary_and_source_links_are_durable(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    session = repository.create_curation_session(
        workspace_id="w1",
        session_id="s1",
        source_refs=("source-1", "source-2"),
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=session.source_refs,
        batch_id="batch-curation",
    )

    progressing = repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=2,
        total_units=5,
        active_batch_id=batch.id,
    )
    summarized = repository.replace_curation_summary(
        "s1",
        expected_version=0,
        summary=CurationSummary(
            items=(
                {
                    "ordinal": 1,
                    "candidateId": "candidate-a",
                    "recommendation": "recommend_confirm",
                },
            )
        ),
    )
    first_link = repository.upsert_question_source_link(
        question_id="a",
        source_id="source-1",
        batch_id=batch.id,
        session_id="s1",
        evidence_ref="source-1#fragment-1",
        merge_reason="generated_from_source",
    )
    second_link = repository.upsert_question_source_link(
        question_id="a",
        source_id="source-1",
        batch_id=batch.id,
        session_id="s1",
        evidence_ref="source-1#fragment-1",
        merge_reason="generated_from_source",
    )

    assert progressing.stage == "generating"
    assert (progressing.completed_units, progressing.total_units) == (2, 5)
    assert summarized.summary_version == 1
    assert summarized.summary.items[0]["candidateId"] == "candidate-a"
    assert first_link == second_link
    assert repository.list_question_source_links("a") == (first_link,)
    assert repository.list_curation_sessions("w1")[0].session_id == "s1"
    connection.close()


def test_candidate_source_filter_matches_section_references(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-source-filter",
    )
    connection.execute(
        "INSERT INTO review_question_candidates "
        "(id, batch_id, question_json, source_refs_json, status) "
        "VALUES (?, ?, ?, ?, 'review_pending')",
        (
            "candidate-source-filter",
            batch.id,
            json.dumps(asdict(_snapshot("a"))),
            json.dumps(["source-1#section-0001"]),
        ),
    )
    connection.commit()

    matches = repository.list_candidates("w1", source_id="source-1")
    assert [item.id for item in matches] == ["candidate-source-filter"]
    assert repository.list_candidates("w1", source_id="source-2") == ()
    connection.close()


def test_curation_finalization_is_exactly_once_for_same_owner(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-final",
    )
    first_claim = repository.claim_curation_finalization(batch.id, "r1")
    replayed_claim = repository.claim_curation_finalization(batch.id, "r1")
    candidates = (_finalization_candidate(),)
    _register_staging(
        connection,
        batch_id=batch.id,
        execution_id="r1",
        candidates=candidates,
    )
    first = repository.finalize_curation_candidates(
        batch.id,
        "r1",
        candidates=candidates,
    )
    replayed = repository.finalize_curation_candidates(
        batch.id,
        "r1",
        candidates=candidates,
    )

    assert first_claim == replayed_claim
    assert first == replayed
    assert tuple(candidate.id for candidate in first) == ("candidate-final",)
    assert repository.get_batch(batch.id).status == "review_pending"
    curation = repository.get_curation_session("s1")
    assert curation.stage == "waiting_for_command"
    assert curation.summary_version == 1
    assert curation.summary.items[0]["candidateId"] == "candidate-final"
    assert connection.execute(
        "SELECT status FROM knowledge_drafts WHERE id = 'draft-final'"
    ).fetchone()[0] == "review_pending"
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_candidates WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_source_links WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 1
    connection.close()


def test_empty_curation_finalization_completes_without_human_review(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-empty-final",
    )
    repository.claim_curation_finalization(batch.id, "r1")

    assert repository.finalize_curation_candidates(
        batch.id,
        "r1",
        candidates=(),
    ) == ()
    assert repository.get_batch(batch.id).status == "completed"
    curation = repository.get_curation_session("s1")
    assert curation.stage == "completed"
    assert curation.summary.items == ()
    assert curation.summary_version == 1
    connection.close()


def test_preparing_finalization_claim_revalidates_control_state(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-claim-control",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    repository.claim_curation_finalization(batch.id, "r1")
    repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-after-claim",
        expected_version=batch.version,
    )

    with pytest.raises(ReviewConflictError):
        repository.claim_curation_finalization(batch.id, "r1")

    connection.close()


def test_only_active_session_batch_can_finalize(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-old-active",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    repository.claim_curation_finalization(batch.id, "r1")
    connection.execute(
        "INSERT INTO review_question_batches "
        "(id, workspace_id, session_id, origin_session_id, run_id, "
        "source_refs_json, status) VALUES "
        "('batch-new-active', 'w1', 's1', 's1', 'r1', '[\"source-1\"]', "
        "'generating')"
    )
    connection.execute(
        "UPDATE review_curation_sessions SET active_batch_id = 'batch-new-active' "
        "WHERE session_id = 's1'"
    )
    connection.commit()

    with pytest.raises(ReviewConflictError):
        repository.finalize_curation_candidates(
            batch.id,
            "r1",
            candidates=(_finalization_candidate(),),
        )

    assert repository.get_curation_session("s1").active_batch_id == (
        "batch-new-active"
    )
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE run_id = 'r1'"
    ).fetchone()[0] == 0
    connection.close()


def test_new_batch_is_rejected_while_session_batch_is_active(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    first = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-first",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=first.id,
    )

    with pytest.raises(ReviewConflictError):
        repository.create_batch(
            workspace_id="w1",
            session_id="s1",
            run_id="r1",
            source_refs=("source-1",),
            batch_id="batch-second",
        )

    assert repository.get_curation_session("s1").active_batch_id == first.id
    connection.close()


def test_revision_finalization_requires_immutable_base_draft(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    origin = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-origin",
    )
    _seed_question_draft(connection, "draft-base")
    repository.save_candidate(
        batch_id=origin.id,
        question=replace(
            _snapshot("base"),
            document_id="doc-base",
            content_hash="b" * 64,
        ),
        draft_id="draft-base",
        source_refs=("source-1#fragment-1",),
        status="review_pending",
        candidate_id="candidate-base",
    )
    connection.execute(
        "UPDATE review_question_batches SET status = 'completed' WHERE id = ?",
        (origin.id,),
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r2', 's1', 'running')"
    )
    connection.commit()
    rewrite = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r2",
        source_refs=("source-1",),
        rewrite_of_batch_id=origin.id,
        batch_id="batch-rewrite",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=rewrite.id,
    )
    repository.claim_curation_finalization(rewrite.id, "r2")
    _seed_question_draft(
        connection,
        "draft-competing",
        run_id="r2",
        document_id="doc-base",
        content_hash="c" * 64,
        version=2,
    )
    connection.execute(
        "UPDATE review_question_candidates SET draft_id = 'draft-competing' "
        "WHERE id = 'candidate-base'"
    )
    connection.commit()
    revision = _finalization_candidate(
        candidate_id="candidate-base",
        draft_id="draft-revision",
        run_id="r2",
        document_id="doc-base",
        question_id="base",
        revision_candidate_id="candidate-base",
        expected_revision_draft_id="draft-base",
        expected_revision_draft_version=1,
        expected_revision_draft_hash="b" * 64,
    )
    _register_staging(
        connection,
        batch_id=rewrite.id,
        execution_id="r2",
        candidates=(revision,),
    )

    with pytest.raises(ReviewConflictError):
        repository.finalize_curation_candidates(
            rewrite.id, "r2", candidates=(revision,)
        )

    assert repository.get_candidate("candidate-base").draft_id == (
        "draft-competing"
    )
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE id = 'draft-revision'"
    ).fetchone()[0] == 0
    connection.close()


def test_successful_revision_retires_prior_draft(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    origin = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-origin-retire",
    )
    _seed_question_draft(connection, "draft-base-retire")
    repository.save_candidate(
        batch_id=origin.id,
        question=replace(
            _snapshot("base"),
            document_id="doc-base",
            content_hash="b" * 64,
        ),
        draft_id="draft-base-retire",
        source_refs=("source-1#fragment-1",),
        status="review_pending",
        candidate_id="candidate-retire",
    )
    connection.execute(
        "UPDATE review_question_batches SET status = 'completed' WHERE id = ?",
        (origin.id,),
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r2', 's1', 'running')"
    )
    connection.commit()
    rewrite = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r2",
        source_refs=("source-1",),
        rewrite_of_batch_id=origin.id,
        batch_id="batch-rewrite-retire",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=rewrite.id,
    )
    repository.claim_curation_finalization(rewrite.id, "r2")
    revision = _finalization_candidate(
        candidate_id="candidate-retire",
        draft_id="draft-revision-retire",
        run_id="r2",
        document_id="doc-base",
        question_id="base",
        revision_candidate_id="candidate-retire",
        expected_revision_draft_id="draft-base-retire",
        expected_revision_draft_version=1,
        expected_revision_draft_hash="b" * 64,
    )
    revision["draft"] = {
        **revision["draft"],  # type: ignore[arg-type]
        "version": 2,
    }
    _register_staging(
        connection,
        batch_id=rewrite.id,
        execution_id="r2",
        candidates=(revision,),
    )

    persisted = repository.finalize_curation_candidates(
        rewrite.id, "r2", candidates=(revision,)
    )

    assert persisted[0].draft_id == "draft-revision-retire"
    assert tuple(connection.execute(
        "SELECT status, version FROM knowledge_drafts "
        "WHERE id = 'draft-base-retire'"
    ).fetchone()) == ("superseded", 2)
    assert tuple(connection.execute(
        "SELECT status, version FROM knowledge_drafts "
        "WHERE id = 'draft-revision-retire'"
    ).fetchone()) == ("review_pending", 2)
    connection.close()


def test_revision_publication_completes_only_the_rewrite_batch(
    tmp_path: Path,
) -> None:
    connection, repository, origin, rewrite, candidate = (
        _finalized_question_revision(tmp_path)
    )
    assert candidate.draft_id is not None
    _seed_completed_publication_for_draft(
        connection,
        draft_id=candidate.draft_id,
        publication_id="publication-revision-decision",
        document_id=candidate.question.document_id,
        content_hash=candidate.question.content_hash,
        expected_version=2,
    )

    first = repository.activate_question(
        candidate_id=candidate.id,
        workspace_id="w1",
        document_id=candidate.question.document_id,
        draft_id=candidate.draft_id,
        publication_id="publication-revision-decision",
        content_hash=candidate.question.content_hash,
    )
    completed = repository.get_batch(rewrite.id)
    second = repository.activate_question(
        candidate_id=candidate.id,
        workspace_id="w1",
        document_id=candidate.question.document_id,
        draft_id=candidate.draft_id,
        publication_id="publication-revision-decision",
        content_hash=candidate.question.content_hash,
    )

    assert first == second
    assert candidate.batch_id == origin.id
    assert repository.get_batch(origin.id).status == "review_pending"
    assert repository.get_batch(origin.id).version == origin.version
    assert completed.status == "completed"
    assert completed.version == rewrite.version + 2
    assert repository.get_batch(rewrite.id).version == completed.version
    assert repository.get_curation_session("s1").stage == "completed"
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_catalog "
        "WHERE publication_id = 'publication-revision-decision'"
    ).fetchone()[0] == 1
    assert [
        tuple(row)
        for row in connection.execute(
            "SELECT batch_id, candidate_id, draft_id "
            "FROM review_curation_batch_candidates "
            "WHERE candidate_id = ? ORDER BY batch_id",
            (candidate.id,),
        )
    ] == [
        (
            origin.id,
            candidate.id,
            "draft-base-revision-decision",
        ),
        (rewrite.id, candidate.id, candidate.draft_id),
    ]
    connection.close()


def test_revision_rejection_completes_rewrite_batch_after_restart(
    tmp_path: Path,
) -> None:
    connection, _repository, origin, rewrite, candidate = (
        _finalized_question_revision(tmp_path)
    )
    assert candidate.draft_id is not None
    connection.close()

    restarted_connection = connect_runtime_database(tmp_path)
    restarted = ReviewRepository(restarted_connection)
    rejected = restarted.reject_candidate_for_draft(
        candidate.draft_id,
        reason="用户拒绝修订结果",
        rejected_at="2026-07-22T12:30:00+08:00",
        action_id="reject-revision-after-restart",
    )

    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.batch_id == origin.id
    assert restarted.get_batch(origin.id).status == "review_pending"
    assert restarted.get_batch(origin.id).version == origin.version
    assert restarted.get_batch(rewrite.id).status == "completed"
    assert restarted.get_batch(rewrite.id).version == rewrite.version + 2
    assert restarted.get_curation_session("s1").stage == "completed"
    restarted_connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ("publication", "revision"))
async def test_publication_and_revision_race_has_one_durable_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winner: str,
) -> None:
    connection = _connection(tmp_path)
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    revision_transaction_open = threading.Event()
    release_revision_transaction = threading.Event()

    def validate_artifact(*args):
        drafts.validate_curation_artifact(*args)
        if winner == "revision":
            revision_transaction_open.set()
            if not release_revision_transaction.wait(timeout=5):
                raise TimeoutError("revision race barrier timed out")

    repository = ReviewRepository(
        connection,
        validate_curation_artifact=validate_artifact,
    )
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    origin = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-origin-publication-claim",
    )
    base_content = b"# publication claim base\n"
    base_hash = sha256(base_content).hexdigest()
    base_path = (
        tmp_path
        / "artifacts/review/drafts/draft-base-publication-claim.md"
    )
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_bytes(base_content)
    _seed_question_draft(
        connection,
        "draft-base-publication-claim",
        content_hash=base_hash,
    )
    repository.save_candidate(
        batch_id=origin.id,
        question=replace(
            _snapshot("base"),
            document_id="doc-base",
            content_hash=base_hash,
        ),
        draft_id="draft-base-publication-claim",
        source_refs=("source-1#fragment-1",),
        status="review_pending",
        candidate_id="candidate-publication-claim",
    )
    draft = await KnowledgeDraftService(
        tmp_path, workspace_id="w1"
    ).get("draft-base-publication-claim")
    actions = PendingActionRepository(tmp_path)
    pending = await actions.create(CreatePendingAction(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        action_type="knowledge.publish",
        payload={
            "draftId": draft.id,
            "draftVersion": draft.version,
            "contentHash": draft.content_hash,
            "title": draft.title,
            "markdown": draft.markdown,
        },
        preview={"title": draft.title, "markdown": draft.markdown},
        editable_fields=("title", "markdown"),
        idempotency_key="action-publication-claim",
    ))
    await actions.resolve(
        pending.id,
        expected_version=1,
        status="approved",
        resolution_key="approve-publication-claim",
        decision={"decision": "approved"},
    )
    action = await actions.get(pending.id)
    connection.execute(
        "UPDATE review_question_batches SET status = 'completed' WHERE id = ?",
        (origin.id,),
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('r2', 's1', 'running')"
    )
    connection.commit()
    rewrite = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r2",
        source_refs=("source-1",),
        rewrite_of_batch_id=origin.id,
        batch_id="batch-rewrite-publication-claim",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=rewrite.id,
    )
    repository.claim_curation_finalization(rewrite.id, "r2")
    revision = _finalization_candidate(
        candidate_id="candidate-publication-claim",
        draft_id="draft-revision-publication-claim",
        run_id="r2",
        document_id="doc-base",
        question_id="base",
        revision_candidate_id="candidate-publication-claim",
        expected_revision_draft_id="draft-base-publication-claim",
        expected_revision_draft_version=1,
        expected_revision_draft_hash=base_hash,
    )
    revision["draft"] = {
        **revision["draft"],  # type: ignore[arg-type]
        "version": 2,
    }
    _register_staging(
        connection,
        batch_id=rewrite.id,
        execution_id="r2",
        candidates=(revision,),
    )

    service = PublicationService(tmp_path, workspace_id="w1")
    if winner == "publication":
        original_prepare = service._repository.prepare
        claim_committed = asyncio.Event()
        release_file_write = asyncio.Event()

        async def prepare_then_wait(*args, **kwargs):
            publication = await original_prepare(*args, **kwargs)
            claim_committed.set()
            await release_file_write.wait()
            return publication

        monkeypatch.setattr(service._repository, "prepare", prepare_then_wait)
        publishing = asyncio.create_task(service.publish_approved_action(action))
        await claim_committed.wait()
        with pytest.raises(DraftNotEditableError, match="publication claim"):
            await drafts.update(
                draft.id,
                UpdateDraftCommand(
                    expected_version=draft.version,
                    markdown="# must not change after claim\n",
                ),
            )
        with pytest.raises(ReviewConflictError, match="revision base changed"):
            repository.finalize_curation_candidates(
                rewrite.id, "r2", candidates=(revision,)
            )
        release_file_write.set()
        publication = await publishing

        assert repository.get_candidate(
            "candidate-publication-claim"
        ).draft_id == "draft-base-publication-claim"
        assert tuple(connection.execute(
            "SELECT status, version FROM knowledge_drafts "
            "WHERE id = 'draft-base-publication-claim'"
        ).fetchone()) == ("published", 1)
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_drafts "
            "WHERE id = 'draft-revision-publication-claim'"
        ).fetchone()[0] == 0
        assert publication.state == "completed"
        assert (
            tmp_path / "knowledge-vault/10_question_bank/doc-base.md"
        ).is_file()
        index = connect_index(
            tmp_path / "knowledge-vault/.cyber-interview-agent/index.sqlite"
        )
        assert index.execute(
            "SELECT status FROM manifest_documents WHERE id = 'doc-base'"
        ).fetchone()[0] == "ingested"
        index.close()
    else:
        finalizing = asyncio.create_task(asyncio.to_thread(
            repository.finalize_curation_candidates,
            rewrite.id,
            "r2",
            candidates=(revision,),
        ))
        assert await asyncio.to_thread(revision_transaction_open.wait, 5)
        original_prepare = service._repository.prepare
        prepare_started = asyncio.Event()

        async def prepare_after_stale_read(*args, **kwargs):
            prepare_started.set()
            return await original_prepare(*args, **kwargs)

        monkeypatch.setattr(
            service._repository, "prepare", prepare_after_stale_read
        )
        publishing = asyncio.create_task(service.publish_approved_action(action))
        await prepare_started.wait()
        release_revision_transaction.set()
        persisted = await finalizing
        with pytest.raises(DraftVersionChangedError):
            await publishing

        assert persisted[0].draft_id == "draft-revision-publication-claim"
        assert repository.get_candidate(
            "candidate-publication-claim"
        ).draft_id == "draft-revision-publication-claim"
        assert tuple(connection.execute(
            "SELECT status, version FROM knowledge_drafts "
            "WHERE id = 'draft-base-publication-claim'"
        ).fetchone()) == ("superseded", 2)
        assert tuple(connection.execute(
            "SELECT status, version FROM knowledge_drafts "
            "WHERE id = 'draft-revision-publication-claim'"
        ).fetchone()) == ("review_pending", 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM publication_runs "
            "WHERE draft_id = 'draft-base-publication-claim'"
        ).fetchone()[0] == 0
        assert not (tmp_path / "knowledge-vault").exists()
    connection.close()


@pytest.mark.parametrize("artifact_state", ("missing", "tampered"))
def test_curation_finalization_rejects_invalid_staged_artifact_at_commit(
    tmp_path: Path, artifact_state: str
) -> None:
    connection = _connection(tmp_path)
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    repository = ReviewRepository(
        connection,
        validate_curation_artifact=drafts.validate_curation_artifact,
    )
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id=f"batch-{artifact_state}-artifact",
    )
    repository.claim_curation_finalization(batch.id, "r1")
    candidate = _finalization_candidate(
        candidate_id=f"candidate-{artifact_state}",
        draft_id=f"draft-{artifact_state}",
    )
    content = b"# verified artifact\n"
    digest = sha256(content).hexdigest()
    draft = candidate["draft"]
    assert isinstance(draft, dict)
    draft["content_hash"] = digest
    question = candidate["question"]
    assert isinstance(question, QuestionSnapshot)
    candidate["question"] = replace(question, content_hash=digest)
    _register_staging(
        connection,
        batch_id=batch.id,
        execution_id="r1",
        candidates=(candidate,),
        write_artifacts=False,
    )
    if artifact_state == "tampered":
        path = tmp_path / str(draft["content_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tampered")

    with pytest.raises(ReviewConflictError, match="artifact"):
        repository.finalize_curation_candidates(
            batch.id, "r1", candidates=(candidate,)
        )

    assert repository.get_batch(batch.id).status == "generating"
    assert repository.get_curation_session("s1").summary_version == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE id = ?",
        (candidate["draft_id"],),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_candidates WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_source_links WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    connection.close()


def test_curation_finalization_validates_artifact_and_commits(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    repository = ReviewRepository(
        connection,
        validate_curation_artifact=drafts.validate_curation_artifact,
    )
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-valid-artifact",
    )
    repository.claim_curation_finalization(batch.id, "r1")
    candidate = _finalization_candidate(
        candidate_id="candidate-valid-artifact",
        draft_id="draft-valid-artifact",
    )
    content = b"# verified artifact\n"
    digest = sha256(content).hexdigest()
    draft = candidate["draft"]
    assert isinstance(draft, dict)
    draft["content_hash"] = digest
    question = candidate["question"]
    assert isinstance(question, QuestionSnapshot)
    candidate["question"] = replace(question, content_hash=digest)
    _register_staging(
        connection,
        batch_id=batch.id,
        execution_id="r1",
        candidates=(candidate,),
        write_artifacts=False,
    )
    path = tmp_path / str(draft["content_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    persisted = repository.finalize_curation_candidates(
        batch.id, "r1", candidates=(candidate,)
    )

    assert persisted[0].draft_id == "draft-valid-artifact"
    assert repository.get_batch(batch.id).status == "review_pending"
    assert repository.get_curation_session("s1").summary_version == 1
    connection.close()


@pytest.mark.parametrize("operation", ("pause", "terminate"))
def test_curation_finalization_loses_to_control_without_formal_output(
    tmp_path: Path, operation: str
) -> None:
    connection = _connection(tmp_path)
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id=f"batch-{operation}",
    )
    repository.claim_curation_finalization(batch.id, "r1")
    repository.request_batch_control(
        batch.id,
        operation=operation,
        idempotency_key=f"{operation}-before-commit",
        expected_version=batch.version,
    )

    with pytest.raises(ReviewConflictError):
        repository.finalize_curation_candidates(
            batch.id,
            "r1",
            candidates=(_finalization_candidate(),),
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_candidates WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_source_links WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE run_id = 'r1'"
    ).fetchone()[0] == 0
    connection.close()


def test_old_curation_run_cannot_finalize_after_new_owner_claims(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-owner",
    )
    repository.claim_curation_finalization(batch.id, "r1")
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r2', 's1', 'running')"
    )
    connection.execute(
        "UPDATE review_question_batches SET run_id = 'r2', version = version + 1 "
        "WHERE id = ?",
        (batch.id,),
    )
    connection.commit()
    repository.claim_curation_finalization(batch.id, "r2")
    new_candidates = (
        _finalization_candidate(
            candidate_id="candidate-new",
            draft_id="draft-new",
            run_id="r2",
        ),
    )
    _register_staging(
        connection,
        batch_id=batch.id,
        execution_id="r2",
        candidates=new_candidates,
    )

    with pytest.raises(ReviewConflictError):
        repository.finalize_curation_candidates(
            batch.id,
            "r1",
            candidates=(
                _finalization_candidate(
                    candidate_id="candidate-old", draft_id="draft-old"
                ),
            ),
        )
    persisted = repository.finalize_curation_candidates(
        batch.id,
        "r2",
        candidates=new_candidates,
    )

    assert tuple(candidate.id for candidate in persisted) == ("candidate-new",)
    assert repository.get_batch(batch.id).run_id == "r2"
    assert [
        tuple(row)
        for row in connection.execute(
            "SELECT id FROM review_question_candidates WHERE batch_id = ?",
            (batch.id,),
        ).fetchall()
    ] == [("candidate-new",)]
    assert [
        tuple(row)
        for row in connection.execute(
            "SELECT id, status FROM knowledge_drafts ORDER BY id"
        ).fetchall()
    ] == [("draft-new", "review_pending")]
    connection.close()


def test_curation_finalization_rolls_back_every_formal_write(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    repository = _validated_repository(tmp_path, connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-rollback",
    )
    repository.claim_curation_finalization(batch.id, "r1")
    candidates = (
        _finalization_candidate(
            candidate_id="candidate-valid", draft_id="draft-valid"
        ),
        _finalization_candidate(
            candidate_id="candidate-invalid", draft_id="draft-invalid"
        ),
    )
    invalid_draft = candidates[1]["draft"]
    assert isinstance(invalid_draft, dict)
    invalid_draft["title"] = None
    _register_staging(
        connection,
        batch_id=batch.id,
        execution_id="r1",
        candidates=candidates,
    )

    with pytest.raises(sqlite3.IntegrityError):
        repository.finalize_curation_candidates(
            batch.id,
            "r1",
            candidates=candidates,
        )

    assert repository.get_batch(batch.id).status == "generating"
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_candidates WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM review_question_source_links WHERE batch_id = ?",
        (batch.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE run_id = 'r1'"
    ).fetchone()[0] == 0
    connection.close()


def test_accept_review_answer_is_atomic_and_idempotent(tmp_path: Path) -> None:
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
    connection.execute(
        "UPDATE agent_runs SET status = 'waiting_for_input' WHERE id = 'r1'"
    )
    connection.execute(
        "UPDATE agent_sessions SET status = 'waiting_for_input' WHERE id = 's1'"
    )
    connection.commit()

    first = repository.accept_review_answer(
        request_id=request.id,
        expected_version=request.version,
        idempotency_key="answer-key",
        value="My answer",
        receipt_id="receipt-1",
        attempt_id="attempt-1",
        message_id="message-1",
    )
    second = repository.accept_review_answer(
        request_id=request.id,
        expected_version=request.version,
        idempotency_key="answer-key",
        value="My answer",
        receipt_id="ignored",
        attempt_id="ignored",
        message_id="ignored",
    )

    attempt = repository.list_attempts("round-1")[0]
    message = connection.execute(
        "SELECT role, content, message_kind, payload_json "
        "FROM agent_messages WHERE id = 'message-1'"
    ).fetchone()
    reference_messages = connection.execute(
        "SELECT role, content, message_kind, payload_json "
        "FROM agent_messages WHERE session_id = 's1' "
        "AND json_extract(payload_json, '$.intent') = 'post_answer_reference'"
    ).fetchall()
    execution_status = connection.execute(
        "SELECT status FROM agent_runs WHERE id = 'r1'"
    ).fetchone()[0]

    assert first == second
    assert first.attempt_id == "attempt-1"
    assert first.status == "evaluating"
    assert attempt.status == "evaluating"
    assert attempt.answer == "My answer"
    assert tuple(message[:3]) == ("user", "My answer", "review_answer")
    assert "My answer" not in message[3]
    assert len(reference_messages) == 1
    reference = reference_messages[0]
    reference_payload = json.loads(reference["payload_json"])
    assert tuple(reference[:3]) == (
        "assistant",
        "参考答案：Answer a\n\n"
        "这份答案在你提交后自动展示，仅用于答后对照，"
        "不影响本次掌握度评价。",
        "review_prompt",
    )
    assert reference_payload["automaticReference"] is True
    assert reference_payload["affectsMastery"] is False
    assert repository.question_assistance("round-1", 1) == (0, False)
    assert execution_status == "running"
    with pytest.raises(InputAlreadyResolvedError):
        repository.accept_review_answer(
            request_id=request.id,
            expected_version=request.version,
            idempotency_key="answer-key",
            value="Different answer",
        )
    connection.close()


def test_accept_review_answer_rolls_back_when_execution_cannot_resume(
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

    with pytest.raises(ReviewConflictError):
        repository.accept_review_answer(
            request_id=request.id,
            expected_version=request.version,
            idempotency_key="answer-key",
            value="My answer",
        )

    assert repository.get_input_request(request.id).status == "pending"
    assert repository.list_attempts("round-1") == ()
    assert connection.execute(
        "SELECT COUNT(*) FROM agent_messages WHERE session_id = 's1'"
    ).fetchone()[0] == 0
    connection.close()


def test_attempt_evaluation_transitions_store_validated_result(
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
    connection.execute(
        "UPDATE agent_runs SET status = 'waiting_for_input' WHERE id = 'r1'"
    )
    connection.commit()
    receipt = repository.accept_review_answer(
        request_id=request.id,
        expected_version=request.version,
        idempotency_key="answer-key",
        value="My answer",
        attempt_id="attempt-1",
    )

    completed = repository.complete_attempt_evaluation(
        receipt.attempt_id,
        evaluation={"score": "partial", "missing_key_points": ["edge"]},
        mastery_suggestion="partial",
        needs_follow_up=True,
    )

    assert completed.status == "waiting_for_follow_up"
    assert completed.evaluation == {
        "score": "partial",
        "missing_key_points": ["edge"],
    }
    assert completed.mastery_suggestion == "partial"
    assert completed.evaluation_completed_at is not None
    connection.close()


def test_attempt_evaluation_persists_coverage_and_answer_revisions(
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
        round_id="round-coverage",
    )
    request = repository.create_input_request(
        round_id="round-coverage",
        ordinal=1,
        kind="answer",
        prompt="Explain a",
        request_id="input-coverage",
    )
    connection.execute(
        "UPDATE agent_runs SET status = 'waiting_for_input' WHERE id = 'r1'"
    )
    connection.commit()
    receipt = repository.accept_review_answer(
        request_id=request.id,
        expected_version=request.version,
        idempotency_key="coverage-answer-key",
        value="My first answer",
        attempt_id="attempt-coverage",
    )

    completed = repository.complete_attempt_evaluation(
        receipt.attempt_id,
        evaluation={"score": "good"},
        mastery_suggestion="stable",
        needs_follow_up=False,
        coverage=(
            KeyPointCoverage(
                point="point",
                status="covered",
                evidence=("My first answer",),
            ),
        ),
        result_kind="independent_mastery",
        hint_level=0,
    )

    assert completed.coverage[0].status == "covered"
    assert completed.result_kind == "independent_mastery"
    assert completed.answer_revisions == ("My first answer",)
    connection.close()


def test_attempt_evaluation_failure_preserves_answer_and_uses_safe_code(
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
    connection.execute(
        "UPDATE agent_runs SET status = 'waiting_for_input' WHERE id = 'r1'"
    )
    connection.commit()
    receipt = repository.accept_review_answer(
        request_id=request.id,
        expected_version=request.version,
        idempotency_key="answer-key",
        value="My answer",
        attempt_id="attempt-1",
    )

    failed = repository.fail_attempt_evaluation(
        receipt.attempt_id, error_code="structured_output_invalid"
    )

    assert failed.status == "evaluation_failed"
    assert failed.answer == "My answer"
    assert failed.evaluation is None
    assert failed.evaluation_error_code == "structured_output_invalid"
    assert failed.evaluation_completed_at is not None
    connection.close()
