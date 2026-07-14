from app.schemas.review import ReviewRoundSettings


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
