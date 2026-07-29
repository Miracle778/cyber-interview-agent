import pytest
from langchain.agents.structured_output import OutputToolBinding, ToolStrategy
from pydantic import ValidationError

from app.agents.prompts.review_round_prompts import (
    REVIEW_ROUND_EVALUATION_PROMPT,
)
from app.agents.review_round_contracts import RoundAnswerEvaluation


def _completed_evaluation_payload() -> dict[str, object]:
    return {
        "covered_key_points": [
            "Checkpoint 负责运行恢复",
            "领域表拥有业务真相",
            "消息只是交互投影",
        ],
        "partial_key_points": [],
        "missing_key_points": [],
        "follow_up_required": False,
        "follow_up_prompt": "三个关键点已全部覆盖。如果想进一步深入，可以思考……",
        "score": "good",
        "evidence": "三个必答点均已覆盖。",
        "mastery_suggestion": "stable",
    }


def test_tool_strategy_normalizes_extra_prompt_when_follow_up_is_not_required() -> None:
    strategy = ToolStrategy(RoundAnswerEvaluation)
    binding = OutputToolBinding.from_schema_spec(strategy.schema_specs[0])

    evaluation = binding.parse(_completed_evaluation_payload())

    assert isinstance(evaluation, RoundAnswerEvaluation)
    assert evaluation.follow_up_required is False
    assert evaluation.follow_up_prompt is None


def test_required_follow_up_still_rejects_blank_prompt() -> None:
    payload = _completed_evaluation_payload()
    payload.update(
        follow_up_required=True,
        follow_up_prompt=" \n ",
        missing_key_points=["领域表拥有业务真相"],
    )

    with pytest.raises(
        ValidationError,
        match="follow_up_prompt is required when follow_up_required is true",
    ):
        RoundAnswerEvaluation.model_validate(payload)


def test_evaluation_prompt_requires_the_canonical_follow_up_pairing() -> None:
    system = REVIEW_ROUND_EVALUATION_PROMPT.system

    assert "仍有待完善关键点" in system
    assert "follow_up_required=true" in system
    assert "follow_up_prompt 非空" in system
    assert "没有待完善关键点" in system
    assert "follow_up_required=false" in system
    assert "follow_up_prompt=null" in system
    assert "延伸学习建议" in system
