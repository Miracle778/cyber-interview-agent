from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.agents.interview_retrospective_contracts import CleanupOutput
from app.agents.prompts.interview_retrospective_prompts import (
    RETROSPECTIVE_CLEANUP_PROMPT,
    render_cleanup_window,
)


def _segment(**overrides):
    value = {
        "ordinal": 1,
        "speakerRole": "candidate",
        "rawSpeakerLabel": "我",
        "displayName": "候选人",
        "text": "回答",
        "sourceStart": 4,
        "sourceEnd": 6,
        "confidence": 0.9,
        "uncertaintyReason": None,
    }
    value.update(overrides)
    return value


def test_cleanup_output_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CleanupOutput.model_validate(
            {"segments": [{**_segment(), "unexpected": True}]}
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"speakerRole": "assistant"}, "speakerRole"),
        ({"confidence": 1.01}, "confidence"),
        ({"displayName": "名" * 81}, "displayName"),
        ({"text": ""}, "text"),
        ({"sourceStart": 7, "sourceEnd": 6}, "sourceEnd"),
    ],
)
def test_cleanup_output_rejects_invalid_segment_fields(overrides, message) -> None:
    with pytest.raises(ValidationError) as error:
        CleanupOutput.model_validate({"segments": [_segment(**overrides)]})
    assert message in str(error.value)


def test_cleanup_output_requires_ascending_non_overlapping_offsets() -> None:
    with pytest.raises(ValidationError, match="有序且不重叠"):
        CleanupOutput.model_validate(
            {
                "segments": [
                    _segment(sourceStart=10, sourceEnd=14),
                    _segment(ordinal=2, sourceStart=12, sourceEnd=16),
                ]
            }
        )


def test_cleanup_output_checks_current_source_window_ownership() -> None:
    output = CleanupOutput.model_validate(
        {"segments": [_segment(sourceStart=99, sourceEnd=103)]}
    )
    with pytest.raises(ValueError, match="当前文字窗口"):
        output.validate_window(source_start=100, source_end=200)


def test_cleanup_prompt_has_stable_identity_and_input_kind() -> None:
    assert RETROSPECTIVE_CLEANUP_PROMPT.id == "interview_retrospective.cleanup"
    assert RETROSPECTIVE_CLEANUP_PROMPT.version == "2026-08-01"
    transcript = render_cleanup_window(
        source_kind="transcript",
        source_start=0,
        source_end=8,
        body="面试官：你好",
    )
    recollection = render_cleanup_window(
        source_kind="recollection",
        source_start=0,
        source_end=8,
        body="问了缓存",
    )
    assert '"sourceKind": "transcript"' in transcript
    assert '"sourceKind": "recollection"' in recollection
    assert transcript != recollection


def test_cleanup_agent_uses_analysis_role_without_tools() -> None:
    captured = {}
    runnable = object()

    class StubFactory:
        def create(self, spec, **kwargs):
            captured["spec"] = spec
            captured["kwargs"] = kwargs
            return runnable

    agents = InterviewRetrospectiveAgents.create(
        StubFactory(),  # type: ignore[arg-type]
        model_bindings={"retrospective_analysis": "model-1"},
    )

    assert agents.cleanup is runnable
    assert captured["spec"].role == "retrospective_analysis"
    assert captured["spec"].execution_name == "interview_retrospective_cleanup"
    assert captured["spec"].tools == ()
    assert captured["spec"].response_format is CleanupOutput
    assert captured["kwargs"]["model_bindings"] == {
        "retrospective_analysis": "model-1"
    }
