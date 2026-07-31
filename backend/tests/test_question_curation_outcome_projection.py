from __future__ import annotations

from app.evaluation.outcome_adapters.question_curation import (
    QuestionCurationOutcomeAdapter,
)
from app.evaluation.views import build_question_curation_evaluation_view
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.models import QuestionSnapshot
from app.review.repository import ReviewRepository


def _snapshot() -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id="question-1",
        document_id="document-1",
        content_hash="a" * 64,
        title="Redis 为什么快",
        question_text="Redis 为什么快？",
        reference_answer="原文要点\n\n模型补充",
        topics=("Redis",),
        difficulty="medium",
        key_points=("内存访问",),
        follow_ups=(),
    )


def _seed_question_curation(connection) -> ReviewRepository:
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'question.curate', 3, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('execution-1', 'session-1', 'completed', "
        "'{\"batchId\":\"batch-1\",\"sourceRefs\":[\"source-1\"]}')"
    )
    connection.commit()
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="workspace-1",
        session_id="session-1",
        source_refs=("source-1",),
    )
    repository.create_batch(
        workspace_id="workspace-1",
        session_id="session-1",
        run_id="execution-1",
        source_refs=("source-1",),
        status="review_pending",
        batch_id="batch-1",
    )
    work_item = repository.plan_curation_work_item(
        batch_id="batch-1",
        stage="discovery",
        unit_index=0,
        input_digest="b" * 64,
        source_refs=("source-1#section-1",),
    )
    repository.start_curation_work_item(work_item.id)
    repository.complete_curation_work_item(
        work_item.id,
        output={
            "seeds": [
                {
                    "question_text": "Redis 为什么快？",
                    "source_ref": "source-1#section-1",
                }
            ]
        },
    )
    candidate = repository.save_candidate(
        batch_id="batch-1",
        question=_snapshot(),
        draft_id=None,
        source_refs=("source-1#section-1",),
        status="review_pending",
        candidate_id="candidate-1",
    )
    connection.execute(
        "UPDATE review_question_candidates SET answer_basis = 'mixed', "
        "material_support = 'partial', needs_review = 1, "
        "normalization_issues_json = '[\"supplemental_answer_present\"]' "
        "WHERE id = ?",
        (candidate.id,),
    )
    connection.commit()
    return repository


def test_question_curation_projection_uses_final_domain_state_not_trace(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_question_curation(connection)
        projection = QuestionCurationOutcomeAdapter(
            connection, "workspace-1"
        ).build("execution-1")

        assert projection.task_type == "question_curation"
        assert projection.identity.domain_refs == {"batchId": "batch-1"}
        assert projection.execution_status == "completed"
        assert projection.terminal_state == "review_pending"
        assert projection.unit_counters["workItems"].completed == 1
        assert projection.unit_counters["candidates"].total == 1
        assert projection.items[0].user_decision.status == "pending"
        assert {
            item.support_type
            for item in projection.items[0].provenance
            if item.field_path == "content.referenceAnswer"
        } == {"direct", "inferred"}
        assert "source_supplemental_answer_not_separated" in projection.evidence_gaps
        assert len(projection.outcome_hash) == 64
    finally:
        connection.close()


def test_question_curation_projection_hash_changes_after_user_confirmation(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_question_curation(connection)
        adapter = QuestionCurationOutcomeAdapter(connection, "workspace-1")
        before = adapter.build("execution-1")

        connection.execute(
            "UPDATE review_question_candidates SET confirmation_status = 'confirmed', "
            "confirmation_version = 1, confirmed_at = CURRENT_TIMESTAMP "
            "WHERE id = 'candidate-1'"
        )
        connection.commit()
        after = adapter.build("execution-1")

        assert before.outcome_hash != after.outcome_hash
        assert after.items[0].user_decision.status == "accepted"
        assert after.items[0].user_decision.version == 1
    finally:
        connection.close()


def test_question_curation_judge_view_is_minimal_and_applicability_aware(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _seed_question_curation(connection)
        projection = QuestionCurationOutcomeAdapter(
            connection, "workspace-1"
        ).build("execution-1")

        view = build_question_curation_evaluation_view(projection)
        serialized = view.model_dump_json(by_alias=True)
        applicability = {
            item.dimension_id: item.applicability
            for item in view.dimensions
        }

        assert view.task_type == "question_curation"
        assert view.business_outcome_hash == projection.outcome_hash
        assert view.data_categories == (
            "taskIdentity",
            "curationCounters",
            "candidateContent",
            "fieldProvenance",
            "userDecision",
            "evidenceGaps",
        )
        assert applicability["source_answer_fidelity"] == "insufficient_evidence"
        assert applicability["duplicate_handling"] == "insufficient_evidence"
        assert applicability["zero_result_reasoning"] == "not_applicable"
        assert "workspacePath" not in serialized
        assert "storageRef" not in serialized
        assert "traceEvents" not in serialized
        assert "source-1#section-1" in serialized
    finally:
        connection.close()
