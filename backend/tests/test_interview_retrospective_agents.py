from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.interview_retrospective_agents import InterviewRetrospectiveAgents
from app.agents.interview_retrospective_contracts import (
    CleanupOutput,
    QuestionAnalysisOutput,
    QuestionExtractionOutput,
)
from app.agents.prompts.interview_retrospective_prompts import (
    RETROSPECTIVE_ANALYSIS_PROMPT,
    RETROSPECTIVE_CLEANUP_PROMPT,
    RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT,
    render_question_analysis_input,
    render_question_extraction_input,
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
        CleanupOutput.model_validate({"segments": [{**_segment(), "unexpected": True}]})


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
    captured = []

    class StubFactory:
        def create(self, spec, **kwargs):
            runnable = object()
            captured.append((spec, kwargs, runnable))
            return runnable

    agents = InterviewRetrospectiveAgents.create(
        StubFactory(),  # type: ignore[arg-type]
        model_bindings={"retrospective_analysis": "model-1"},
    )

    specs = {
        spec.execution_name: (spec, kwargs, runnable)
        for spec, kwargs, runnable in captured
    }
    cleanup, kwargs, runnable = specs["interview_retrospective_cleanup"]
    assert agents.cleanup is runnable
    assert cleanup.role == "retrospective_analysis"
    assert cleanup.tools == ()
    assert cleanup.response_format is CleanupOutput
    assert kwargs["model_bindings"] == {"retrospective_analysis": "model-1"}
    assert (
        specs["interview_retrospective_question_extraction"][0].response_format
        is QuestionExtractionOutput
    )
    assert (
        specs["interview_retrospective_question_analysis"][0].response_format
        is QuestionAnalysisOutput
    )
    assert all(spec.tools == () for spec, _kwargs, _runnable in captured)


def test_question_extraction_preserves_ordered_provenance() -> None:
    output = QuestionExtractionOutput.model_validate(
        {
            "questions": [
                {
                    "ordinal": 1,
                    "questionKind": "project_experience",
                    "origin": "original",
                    "questionText": "你在缓存治理中承担了什么职责？",
                    "questionSegmentIds": ["segment-q1"],
                    "answerSegmentIds": ["segment-a1"],
                    "inferenceBasis": "",
                    "confidence": 0.98,
                },
                {
                    "ordinal": 2,
                    "questionKind": "technical_knowledge",
                    "origin": "inferred",
                    "questionText": "如何处理缓存与数据库的一致性？",
                    "questionSegmentIds": [],
                    "answerSegmentIds": ["segment-a2"],
                    "inferenceBasis": "候选人的回答直接讨论了一致性策略",
                    "confidence": 0.72,
                },
            ]
        }
    )

    assert [item.ordinal for item in output.questions] == [1, 2]
    assert output.questions[0].question_segment_ids == ["segment-q1"]
    assert output.questions[1].origin == "inferred"
    assert output.questions[1].inference_basis


def test_inferred_question_requires_inference_basis() -> None:
    with pytest.raises(ValidationError, match="inferenceBasis"):
        QuestionExtractionOutput.model_validate(
            {
                "questions": [
                    {
                        "ordinal": 1,
                        "questionKind": "unknown",
                        "origin": "inferred",
                        "questionText": "可能问了什么？",
                        "questionSegmentIds": [],
                        "answerSegmentIds": ["segment-a1"],
                        "inferenceBasis": "",
                        "confidence": 0.5,
                    }
                ]
            }
        )


def test_question_analysis_is_strict_and_has_no_overall_score() -> None:
    output = QuestionAnalysisOutput.model_validate(
        {
            "verdict": "improvable",
            "strengths": [
                {"summary": "说明了更新策略", "evidenceSegmentIds": ["segment-a1"]}
            ],
            "improvements": [],
            "omissions": [],
            "gaps": [
                {
                    "kind": "knowledge",
                    "summary": "缺少失败恢复说明",
                    "evidenceSegmentIds": ["segment-a1"],
                }
            ],
            "evidenceLevel": "internal_evidence",
            "confidence": 0.8,
            "improvementOutline": ["先说明目标", "再补充异常路径"],
            "suggestedAnswer": "我会先明确一致性目标，再说明更新与失败恢复策略。",
        }
    )

    assert output.verdict == "improvable"
    assert "overall_score" not in QuestionAnalysisOutput.model_fields
    with pytest.raises(ValidationError):
        QuestionAnalysisOutput.model_validate(
            {**output.model_dump(by_alias=True), "overallScore": 88}
        )


def test_analysis_prompts_use_bounded_structured_payloads() -> None:
    assert (
        RETROSPECTIVE_QUESTION_EXTRACTION_PROMPT.id
        == "interview_retrospective.question_extraction"
    )
    assert (
        RETROSPECTIVE_ANALYSIS_PROMPT.id == "interview_retrospective.question_analysis"
    )
    extraction = render_question_extraction_input(
        segments=[{"id": "s1", "speakerRole": "interviewer", "body": "介绍项目"}],
        context_snapshot={"target": {"roleName": "后端工程师"}},
    )
    analysis = render_question_analysis_input(
        question={"id": "q1", "questionText": "介绍项目"},
        segments=[{"id": "s2", "speakerRole": "candidate", "body": "回答"}],
        context_snapshot={"profile": {"items": []}},
    )

    assert '"segments"' in extraction
    assert '"question"' in analysis
    assert "storagePath" not in extraction + analysis
