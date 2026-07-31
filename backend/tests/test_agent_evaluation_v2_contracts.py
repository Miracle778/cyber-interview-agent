from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluation.contracts import JudgeDimensionResultV2
from app.evaluation.repository import AgentEvaluationRepository
from app.infrastructure.runtime_database import (
    connect_runtime_database,
)


def test_v2_run_and_dimension_metadata_round_trip(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = AgentEvaluationRepository(connection, "workspace-1")
    try:
        run = repository.create_run(
            eval_run_id="eval-v2",
            execution_id="execution-1",
            eval_pack_id="question-curation.v2",
            eval_pack_version=2,
            trigger="manual",
            frozen_input_hash="a" * 64,
            snapshot_json='{"safe":true}',
            idempotency_key="manual-v2",
            evaluation_contract_version=2,
            task_type="question_curation",
            run_kind="historical_review",
            business_outcome_hash="b" * 64,
            judge_data_scope_json=(
                '{"provider":"openai","categories":["question","sourceExcerpt"]}'
            ),
        )
        dimensions = repository.store_dimension_results(
            run.id,
            (
                {
                    "dimension_id": "source_answer_fidelity",
                    "source": "judge",
                    "status": "scored",
                    "applicability": "not_applicable",
                    "rating": None,
                    "severity": None,
                    "confidence": None,
                    "summary": "原材料没有提供答案。",
                    "evidence_gaps_json": '["sourceAnswer 为空"]',
                },
            ),
        )

        assert run.evaluation_contract_version == 2
        assert run.task_type == "question_curation"
        assert run.run_kind == "historical_review"
        assert run.business_outcome_hash == "b" * 64
        assert 'sourceExcerpt' in run.judge_data_scope_json
        assert dimensions[0].applicability == "not_applicable"
        assert dimensions[0].rating is None
        assert dimensions[0].severity is None
        assert dimensions[0].evidence_gaps_json == '["sourceAnswer 为空"]'
    finally:
        connection.close()


def test_v1_create_call_uses_explicit_v2_compatibility_defaults(tmp_path) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = AgentEvaluationRepository(connection, "workspace-1")
    try:
        run = repository.create_run(
            eval_run_id="eval-v1",
            execution_id="execution-1",
            eval_pack_id="review.v1",
            eval_pack_version=1,
            trigger="manual",
            frozen_input_hash="c" * 64,
            snapshot_json='{"safe":true}',
            idempotency_key="manual-v1",
        )
        assert run.evaluation_contract_version == 1
        assert run.task_type == "legacy"
        assert run.run_kind == "historical_review"
        assert run.business_outcome_hash is None
        assert run.judge_data_scope_json == "{}"
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("applicability", "rating", "severity"),
    (
        ("applicable", None, None),
        ("not_applicable", "meets", "none"),
        ("insufficient_evidence", "needs_review", "medium"),
    ),
)
def test_v2_dimension_rejects_a_quality_rating_when_applicability_disagrees(
    applicability,
    rating,
    severity,
) -> None:
    with pytest.raises(ValidationError):
        JudgeDimensionResultV2(
            dimension_id="source_answer_fidelity",
            applicability=applicability,
            rating=rating,
            severity=severity,
            confidence=0.8 if applicability == "applicable" else None,
            cited_event_hashes=[],
            cited_artifact_hashes=[],
            evidence_gaps=[],
            summary="contract check",
            risks=[],
        )
