from app.schemas.review import QuestionBatchResource, ReviewRoundSettings
from pydantic import ValidationError
import pytest


def test_review_round_settings_accept_model_and_reasoning_snapshot() -> None:
    settings = ReviewRoundSettings.model_validate(
        {
            "selectedTopics": ["database"],
            "difficulties": ["medium", "hard"],
            "questionCount": 10,
            "mode": "weak-point",
            "allowFollowUp": True,
            "seed": 17,
            "answerModelId": "model-1",
            "reasoningEffort": "medium",
        }
    )

    assert settings.answer_model_id == "model-1"
    assert settings.reasoning_effort == "medium"
    assert settings.difficulties == ["medium", "hard"]
    assert settings.model_dump(by_alias=True)["allowFollowUp"] is True


def test_review_round_settings_accept_job_target_scope() -> None:
    settings = ReviewRoundSettings.model_validate(
        {
            "selectedTopics": [],
            "difficulties": ["medium"],
            "questionCount": 5,
            "mode": "random-mixed",
            "answerModelId": "model-1",
            "questionScope": "job_target",
            "sourceJobTargetId": "target-1",
            "scopeLabel": "后端开发岗",
        }
    )

    assert settings.question_scope == "job_target"
    assert settings.source_job_target_id == "target-1"
    assert settings.scope_label == "后端开发岗"


@pytest.mark.parametrize(
    "payload",
    [
        {"questionScope": "job_target"},
        {"questionScope": "project"},
        {"questionScope": "ordinary", "sourceJobTargetId": "target-1"},
    ],
)
def test_review_round_settings_reject_invalid_scope(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ReviewRoundSettings.model_validate(
            {
                "selectedTopics": [],
                "difficulties": ["medium"],
                "questionCount": 5,
                "mode": "random-mixed",
                "answerModelId": "model-1",
                **payload,
            }
        )


def test_question_batch_resource_projects_durable_control_fields() -> None:
    resource = QuestionBatchResource.model_validate(
        {
            "id": "batch-1",
            "workspace_id": "w1",
            "session_id": "s1",
            "origin_session_id": "s1",
            "run_id": "r1",
            "source_refs": ["source-1"],
            "rewrite_of_batch_id": None,
            "status": "generating",
            "version": 2,
            "control_intent": "pause",
            "concurrency_limit": 3,
            "candidate_count": 0,
            "pending_count": 0,
            "candidates": [],
            "created_at": "2026-07-22T00:00:00Z",
            "updated_at": "2026-07-22T00:00:01Z",
        }
    )

    assert resource.model_dump(by_alias=True) == {
        "id": "batch-1",
        "workspaceId": "w1",
        "sessionId": "s1",
        "originSessionId": "s1",
        "runId": "r1",
        "sourceRefs": ["source-1"],
        "rewriteOfBatchId": None,
        "status": "generating",
        "version": 2,
        "controlIntent": "pause",
        "concurrencyLimit": 3,
        "candidateCount": 0,
        "pendingCount": 0,
        "candidates": [],
        "createdAt": "2026-07-22T00:00:00Z",
        "updatedAt": "2026-07-22T00:00:01Z",
    }
