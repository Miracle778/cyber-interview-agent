from __future__ import annotations

import json

from app.evaluation.repository import AgentEvaluationRepository
from app.evaluation.trends import EvaluationTrendService
from test_agent_trace_retention import _service


def _eval(repository, *, eval_id: str, version: int, score: int):
    record = repository.create_run(
        eval_run_id=eval_id,
        execution_id="run-1",
        eval_pack_id="review.v1",
        eval_pack_version=version,
        trigger="manual",
        frozen_input_hash=str(version) * 64,
        snapshot_json=json.dumps(
            {
                "versions": {"prompt": f"p{version}", "schema": "s1"},
                "tool_versions": {"lookup": "1"},
            }
        ),
        idempotency_key=f"request-{eval_id}",
        judge_provider_model_id="model-1",
    )
    repository.store_dimension_results(
        record.id,
        (
            {
                "dimension_id": "correctness",
                "source": "judge",
                "status": "scored",
                "score": score,
                "confidence": 0.8,
                "summary": "证据支持",
            },
            {
                "dimension_id": "trace_complete",
                "source": "deterministic",
                "status": "passed" if score > 50 else "inconclusive",
                "summary": "规则结果",
            },
        ),
    )
    return repository.complete_run(
        record.id,
        deterministic_result_json='{"status":"passed"}',
        judge_result_json=(
            '{"humanReviewRequired":' + ("false" if score > 50 else "true") + "}"
        ),
        status="completed",
    )


def test_trends_keep_pack_versions_separate_and_support_filters(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    repository = AgentEvaluationRepository(connection, "workspace-1")
    try:
        _eval(repository, eval_id="eval-v1", version=1, score=80)
        _eval(repository, eval_id="eval-v2", version=2, score=40)
        service = EvaluationTrendService(connection, "workspace-1")
        points = service.query()
        version_one = service.query(eval_pack_version=1)
        assert {(point.eval_pack_version, point.prompt_version) for point in points} == {
            (1, "p1"),
            (2, "p2"),
        }
        assert len(version_one) == 1
        assert version_one[0].average_judge_score == 80
        assert version_one[0].human_review_rate == 0
        assert version_one[0].success_rate == 1
        assert "cost" not in str(points).casefold()
    finally:
        connection.close()


def test_v2_trends_use_ratings_feedback_and_user_decisions_without_score(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    repository = AgentEvaluationRepository(connection, "workspace-1")
    try:
        record = repository.create_run(
            eval_run_id="eval-v2-rating",
            execution_id="run-1",
            eval_pack_id="review-round.v2",
            eval_pack_version=2,
            trigger="manual",
            frozen_input_hash="f" * 64,
            snapshot_json=json.dumps({
                "businessOutcome": {
                    "items": [
                        {"userDecision": {"status": "rejected"}},
                        {"userDecision": {"status": "accepted"}},
                    ]
                }
            }),
            idempotency_key="v2-rating",
            judge_provider_model_id="model-1",
            evaluation_contract_version=2,
            task_type="review_round",
        )
        repository.store_dimension_results(record.id, (
            {
                "dimension_id": "feedback_quality",
                "source": "judge",
                "status": "scored",
                "applicability": "applicable",
                "rating": "needs_review",
                "severity": "medium",
                "confidence": .8,
                "summary": "建议复核",
            },
            {
                "dimension_id": "review.progression_guard",
                "source": "deterministic",
                "status": "failed",
                "applicability": "applicable",
                "rating": "severe",
                "severity": "high",
                "confidence": 1,
                "summary": "越权推进",
            },
        ))
        repository.add_feedback(
            eval_run_id=record.id,
            feedback_id="feedback-v2",
            verdict="accurate",
            dimension_id=None,
            reason="人工确认一致",
        )
        repository.complete_run(
            record.id,
            deterministic_result_json='{"status":"failed"}',
            judge_result_json='{"humanReviewRequired":true}',
            status="completed",
        )

        point = EvaluationTrendService(connection, "workspace-1").query(
            eval_pack_id="review-round.v2"
        )[0]
        assert point.evaluation_contract_version == 2
        assert point.average_judge_score is None
        assert point.needs_review_rate == 1
        assert point.severe_rate == 0
        assert point.deterministic_issue_rate == 1
        assert point.judge_human_agreement_rate == 1
        assert point.user_edit_reject_rate == .5
    finally:
        connection.close()
