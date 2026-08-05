from __future__ import annotations

import json

import pytest

from app.evaluation.outcome_adapters.domain import create_sqlite_outcome_adapter
from app.evaluation.registry import get_eval_pack
from app.evaluation.views import build_task_evaluation_view
from app.infrastructure.runtime_database import connect_runtime_database


TASK_GRAPHS = (
    ("review_round", "review.round", "review-round.v2"),
    ("review_single", "review.single", "review-single.v2"),
    ("review_discussion", "review.discussion", "review-discussion.v2"),
    ("profile_ingest", "profile.ingest", "profile-ingest.v2"),
    ("profile_assessment", "profile.assess", "profile-assessment.v2"),
    ("profile_assistant", "profile.manage", "profile-assistant.v2"),
    ("profile_write_boundary", "profile.manage", "profile-write-boundary.v2"),
    ("job_requirement_analysis", "job.analysis", "job-requirement-analysis.v2"),
    ("project_deep_dive_coaching", "project.deep_dive", "project-deep-dive-coaching.v2"),
    ("project_question_generation", "project.deep_dive", "project-question-generation.v2"),
)


def _execution(connection, graph_id: str) -> None:
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', ?, 1, 'Test')",
        (graph_id,),
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('execution-1', 'session-1', 'completed', '{}')"
    )
    connection.commit()


@pytest.mark.parametrize(("task_type", "graph_id", "pack_id"), TASK_GRAPHS)
def test_each_v2_task_has_an_outcome_adapter_and_minimal_view(
    tmp_path,
    task_type,
    graph_id,
    pack_id,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _execution(connection, graph_id)
        outcome = create_sqlite_outcome_adapter(
            task_type, connection, "workspace-1"
        ).build("execution-1")
        view = build_task_evaluation_view(outcome, get_eval_pack(pack_id))
        serialized = view.model_dump_json()

        assert outcome.task_type == task_type
        assert outcome.identity.graph_id == graph_id
        assert view.business_outcome_hash == outcome.outcome_hash
        assert {item.dimension_id for item in view.dimensions} == {
            item.id for item in get_eval_pack(pack_id).dimensions
        }
        assert "storageRef" not in serialized
        assert "workspacePath" not in serialized
        assert "traceEventBodies" not in serialized
    finally:
        connection.close()


def test_job_adapter_preserves_requirement_version_and_validates_quote_offsets(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    try:
        _execution(connection, "job.analysis")
        body = "岗位职责：负责 Redis 性能优化。"
        start = body.index("Redis")
        end = start + len("Redis 性能优化")
        connection.execute(
            "INSERT INTO job_targets "
            "(id, workspace_id, role_name, seniority) "
            "VALUES ('target-1', 'workspace-1', 'Agent 工程师', 'P5')"
        )
        connection.execute(
            "INSERT INTO job_document_versions "
            "(id, job_target_id, ordinal, source_kind, body, content_hash, is_current) "
            "VALUES ('document-1', 'target-1', 1, 'jd_text', ?, ?, 1)",
            (body, "a" * 64),
        )
        connection.execute(
            "INSERT INTO job_analysis_runs "
            "(id, job_target_id, document_version_id, execution_id, "
            "profile_version, input_digest, status, stage) "
            "VALUES ('analysis-1', 'target-1', 'document-1', 'execution-1', "
            "1, ?, 'review_pending', 'waiting_for_review')",
            ("b" * 64,),
        )
        connection.execute(
            "INSERT INTO job_requirements "
            "(id, job_target_id, document_version_id, stable_key, "
            "requirement_type, priority, text, source_quote, source_start, "
            "source_end, inferred) VALUES "
            "('requirement-1', 'target-1', 'document-1', 'redis', "
            "'skill', 'must_have', 'Redis 性能优化', ?, ?, ?, 0)",
            (body[start:end], start, end),
        )
        connection.commit()

        outcome = create_sqlite_outcome_adapter(
            "job_requirement_analysis", connection, "workspace-1"
        ).build("execution-1")

        assert outcome.identity.domain_refs["documentVersionId"] == "document-1"
        assert outcome.items[0].content["locator_valid"] is True
        assert outcome.items[0].provenance[0].support_type == "normalized"
        assert "job-document:document-1" in outcome.items[0].provenance[0].source_refs[0]
    finally:
        connection.close()
