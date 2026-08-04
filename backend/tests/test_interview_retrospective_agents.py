from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.agents import interview_retrospective_contracts as retrospective_contracts
from app.agents.prompts import interview_retrospective_prompts as retrospective_prompts
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.interview_retrospective_agents import (
    InterviewRetrospectiveAgents,
    RetrospectiveCleanupModelError,
    RetrospectiveQuestionExtractionModelError,
)
from app.agents.interview_retrospective_contracts import (
    CleanupOutput,
    MaterializedCleanupOutput,
    QuestionAnalysisOutput,
    QuestionExtractionOutput,
    QuestionExtractionModelOutput,
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
        "sourceEnd": 7,
        "confidence": 0.9,
        "uncertaintyReason": None,
    }
    value.update(overrides)
    return value


def _correction(**overrides):
    value = {
        "segmentOrdinal": 1,
        "sourceStart": 4,
        "sourceEnd": 7,
        "originalText": "瑞迪斯",
        "suggestedText": "Redis",
        "changeType": "recognition",
        "riskLevel": "low",
        "reason": "上下文中的技术名词可以唯一确定",
        "confidence": 0.96,
    }
    value.update(overrides)
    return value


def _agent_context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="session-1",
        run_id="run-1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def test_cleanup_output_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MaterializedCleanupOutput.model_validate(
            {"segments": [{**_segment(), "unexpected": True}]}
        )


def test_cleanup_agent_output_only_returns_grounded_source_units() -> None:
    output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": "unit:100:104",
                    "turns": [
                        {
                            "sourceText": "用了瑞迪斯。",
                            "speakerRole": "candidate",
                            "rawSpeakerLabel": "我",
                            "displayName": "候选人",
                            "correctedText": "用了 Redis。",
                            "confidence": 0.96,
                            "uncertaintyReason": None,
                        }
                    ],
                }
            ]
        }
    )

    output.validate_units(expected_unit_ids=("unit:100:104",))

    assert output.units[0].unit_id == "unit:100:104"
    assert output.units[0].turns[0].corrected_text == "用了 Redis。"


def test_cleanup_target_output_contains_only_corrected_target_and_sparse_issues() -> None:
    output = retrospective_contracts.CleanupWindowOutput.model_validate(
        {
            "correctedTarget": "候选人：我做过数字签名服务。",
            "uncertainItems": [
                {
                    "excerpt": "数字签名",
                    "possibleValue": None,
                    "issueKind": "uncertain_term",
                    "reason": "录音术语需要确认",
                    "confidence": 0.7,
                }
            ],
        }
    )

    assert output.corrected_target == "候选人：我做过数字签名服务。"
    assert output.uncertain_items[0].excerpt == "数字签名"


def test_cleanup_target_prompt_separates_context_from_the_owned_target() -> None:
    rendered = json.loads(
        retrospective_prompts.render_cleanup_target_window(
            source_kind="transcript",
            recording_coverage="candidate_only",
            target_start=100,
            target_end=104,
            before_context="上文。",
            target_text="目标正文",
            after_context="下文。",
            terminology_hints=("数字签名",),
        )
    )

    assert rendered == {
        "sourceKind": "transcript",
        "recordingCoverage": "candidate_only",
        "targetStart": 100,
        "targetEnd": 104,
        "beforeContext": "上文。",
        "targetText": "目标正文",
        "afterContext": "下文。",
        "terminologyHints": ["数字签名"],
    }


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
        MaterializedCleanupOutput.model_validate(
            {"segments": [_segment(**overrides)]}
        )
    assert message in str(error.value)


def test_cleanup_output_requires_ascending_non_overlapping_offsets() -> None:
    with pytest.raises(ValidationError, match="有序且不重叠"):
        MaterializedCleanupOutput.model_validate(
            {
                "segments": [
                    _segment(sourceStart=10, sourceEnd=14),
                    _segment(ordinal=2, sourceStart=12, sourceEnd=16),
                ]
            }
        )


def test_cleanup_output_checks_current_source_window_ownership() -> None:
    output = MaterializedCleanupOutput.model_validate(
        {"segments": [_segment(sourceStart=99, sourceEnd=103)]}
    )
    with pytest.raises(ValueError, match="当前文字窗口"):
        output.validate_window(source_start=100, source_end=200)


def test_cleanup_output_rejects_segments_from_context_only_overlap() -> None:
    output = MaterializedCleanupOutput.model_validate(
        {"segments": [_segment(sourceStart=100, sourceEnd=120)]}
    )

    with pytest.raises(ValueError, match="允许输出范围"):
        output.validate_window(source_start=80, source_end=200, emit_start=120)


def test_cleanup_output_accepts_auditable_low_risk_correction() -> None:
    output = MaterializedCleanupOutput.model_validate(
        {
            "segments": [_segment(sourceStart=4, sourceEnd=12)],
            "corrections": [_correction()],
        }
    )

    output.validate_window(
        source_start=0,
        source_end=20,
        source_body="甲乙丙丁瑞迪斯后续内容占位",
    )

    assert output.corrections[0].suggested_text == "Redis"
    assert output.corrections[0].risk_level == "low"


@pytest.mark.parametrize(
    "correction",
    [
        _correction(sourceStart=3, sourceEnd=7),
        _correction(originalText="不存在的原文"),
        _correction(sourceStart=4, sourceEnd=6, originalText="瑞迪斯"),
    ],
)
def test_cleanup_output_rejects_correction_without_exact_source_evidence(
    correction,
) -> None:
    output = MaterializedCleanupOutput.model_validate(
        {
            "segments": [_segment(sourceStart=4, sourceEnd=12)],
            "corrections": [correction],
        }
    )

    with pytest.raises(ValueError, match="修订原文"):
        output.validate_window(
            source_start=0,
            source_end=20,
            source_body="甲乙丙丁瑞迪斯后续内容占位",
        )


def test_cleanup_output_rejects_overlapping_corrections() -> None:
    output = MaterializedCleanupOutput.model_validate(
        {
            "segments": [_segment(sourceStart=4, sourceEnd=12)],
            "corrections": [
                _correction(),
                _correction(
                    sourceStart=5,
                    sourceEnd=7,
                    originalText="迪斯",
                    suggestedText="dis",
                ),
            ],
        }
    )

    with pytest.raises(ValueError, match="修订范围.*重叠"):
        output.validate_window(
            source_start=0,
            source_end=20,
            source_body="甲乙丙丁瑞迪斯后续内容占位",
        )


def test_cleanup_prompt_has_stable_identity_and_input_kind() -> None:
    assert RETROSPECTIVE_CLEANUP_PROMPT.id == "interview_retrospective.cleanup"
    assert RETROSPECTIVE_CLEANUP_PROMPT.version == "2026-08-02-clean-transcript-target-v1"
    transcript = render_cleanup_window(
        source_kind="transcript",
        recording_coverage="candidate_only",
        source_start=0,
        source_end=len("面试官：你好"),
        body="面试官：你好",
    )
    recollection = render_cleanup_window(
        source_kind="recollection",
        source_start=0,
        source_end=len("问了缓存"),
        body="问了缓存",
    )
    assert '"sourceKind": "transcript"' in transcript
    assert '"recordingCoverage": "candidate_only"' in transcript
    assert '"sourceKind": "recollection"' in recollection
    assert transcript != recollection


def test_cleanup_prompt_keeps_context_read_only_and_internal_structures_out() -> None:
    prompt = RETROSPECTIVE_CLEANUP_PROMPT.system

    assert "你只拥有 targetText" in prompt
    assert "绝不能复制到 correctedTarget" in prompt
    assert "只返回 correctedTarget 与必要的少量 uncertainItems" in prompt
    assert "不得返回 sourceUnits、turns、offset、segments、corrections 或 Diff" in prompt


def test_cleanup_prompt_includes_frozen_speaker_hints() -> None:
    body = "说话人1：请介绍项目"
    rendered = render_cleanup_window(
        source_kind="transcript",
        source_start=4_000,
        source_end=4_000 + len(body),
        emit_start=4_004,
        body=body,
        speaker_hints=(
            {
                "rawSpeakerLabel": "说话人1",
                "speakerRole": "interviewer",
                "displayName": "面试官",
            },
        ),
        terminology_hints=("字节跳动", "Redis", "云原生开发"),
    )

    assert '"speakerHints"' in rendered
    assert '"emitFrom": 4004' in rendered
    assert '"rawSpeakerLabel": "说话人1"' in rendered
    assert '"terminologyHints"' in rendered
    assert '"Redis"' in rendered


def test_cleanup_prompt_uses_stable_source_units_instead_of_raw_window_body() -> None:
    rendered = json.loads(
        render_cleanup_window(
            source_kind="transcript",
            source_start=100,
            source_end=103,
            emit_start=102,
            body="甲。乙",
        )
    )

    assert "body" not in rendered
    assert rendered["sourceUnits"] == [
        {
            "unitId": "unit:100:102",
            "sourceStart": 100,
            "sourceEnd": 102,
            "text": "甲。",
            "emit": False,
        },
        {
            "unitId": "unit:102:103",
            "sourceStart": 102,
            "sourceEnd": 103,
            "text": "乙",
            "emit": True,
        },
    ]


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
    assert cleanup.response_format is retrospective_contracts.CleanupWindowOutput
    assert cleanup.invocation_policy is not None
    assert cleanup.invocation_policy.max_output_tokens == 8_192
    assert cleanup.invocation_policy.request_timeout_seconds == 120
    assert cleanup.invocation_policy.max_retries == 0
    assert cleanup.structured_output_handle_errors is False
    assert kwargs["model_bindings"] == {"retrospective_analysis": "model-1"}
    assert (
        specs["interview_retrospective_question_extraction"][0].response_format
        is QuestionExtractionModelOutput
    )
    assert (
        specs["interview_retrospective_question_extraction"][0]
        .structured_output_handle_errors
        is False
    )
    assert (
        specs["interview_retrospective_question_analysis"][0].response_format
        is QuestionAnalysisOutput
    )
    analysis_policy = specs["interview_retrospective_question_analysis"][0].invocation_policy
    assert analysis_policy is not None
    assert analysis_policy.max_output_tokens == 4_096
    assert analysis_policy.request_timeout_seconds == 120
    assert analysis_policy.max_retries == 0
    assert specs["interview_retrospective_chat"][0].role == "retrospective_chat"
    assert all(spec.tools == () for spec, _kwargs, _runnable in captured)


@pytest.mark.asyncio
async def test_cleanup_window_returns_only_the_owned_corrected_target(
    tmp_path: Path,
) -> None:
    class StubRunnable:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "structured_response": {
                    "correctedTarget": "候选人：我用了 Redis。",
                    "uncertainItems": [
                        {
                            "excerpt": "Redis",
                            "possibleValue": None,
                            "issueKind": "uncertain_term",
                            "reason": "需要确认技术术语",
                            "confidence": 0.7,
                        }
                    ]
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    result = await agents.cleanup_window(
        source_kind="transcript",
        recording_coverage="candidate_only",
        target_start=100,
        target_end=107,
        before_context="面试开始。",
        target_text="我用了瑞迪斯。",
        after_context="继续回答。",
        terminology_hints=("Redis",),
        context=_agent_context(tmp_path),
        config={},
    )

    assert result.corrected_target == "候选人：我用了 Redis。"
    assert result.uncertain_items[0].excerpt == "Redis"


@pytest.mark.asyncio
async def test_cleanup_window_rejects_a_missing_corrected_target(
    tmp_path: Path,
) -> None:
    class StubRunnable:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "structured_response": {
                    "correctedTarget": "",
                    "uncertainItems": [],
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    with pytest.raises(RetrospectiveCleanupModelError) as error:
        await agents.cleanup_window(
            source_kind="transcript",
            recording_coverage="mixed_unknown",
            target_start=0,
            target_end=2,
            before_context="",
            target_text="原文",
            after_context="",
            context=_agent_context(tmp_path),
            config={},
        )

    assert error.value.code == "schema_validation_error"


@pytest.mark.asyncio
async def test_cleanup_window_classifies_missing_truncated_output(
    tmp_path: Path,
) -> None:
    class StubRunnable:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        response_metadata={"stop_reason": "max_tokens"},
                    )
                ]
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    with pytest.raises(RetrospectiveCleanupModelError) as error:
        await agents.cleanup_window(
            source_kind="transcript",
            recording_coverage="mixed_unknown",
            target_start=0,
            target_end=2,
            before_context="",
            target_text="原文",
            after_context="",
            context=_agent_context(tmp_path),
            config={},
        )

    assert error.value.code == "output_truncated"


def test_question_extraction_preserves_ordered_provenance() -> None:
    output = QuestionExtractionOutput.model_validate(
        {
            "questions": [
                {
                    "ordinal": 1,
                    "questionKind": "project_experience",
                    "origin": "original",
                    "questionText": "你在缓存治理中承担了什么职责？",
                    "anchorSegmentId": "segment-q1",
                    "boundaryRelation": "complete",
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
                    "anchorSegmentId": "segment-a2",
                    "boundaryRelation": "complete",
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
    assert output.questions[1].anchor_segment_id == "segment-a2"
    assert output.questions[1].inference_basis


def test_question_extraction_program_assigns_deterministic_fields() -> None:
    model_output = QuestionExtractionModelOutput.model_validate(
        {
            "questions": [
                {
                    "origin": "original",
                    "questionText": "你在项目中承担了什么职责？",
                    "questionSegmentIds": ["segment-q1"],
                    "answerSegmentIds": ["segment-a1"],
                    "confidence": 0.9,
                },
                {
                    "origin": "inferred",
                    "questionText": "为什么选择这个技术方案？",
                    "answerSegmentIds": ["segment-a2"],
                    "inferenceBasis": "回答解释了技术选型原因",
                },
            ]
        }
    )

    output = model_output.materialize(
        allowed_segment_ids={"segment-q1", "segment-a1", "segment-a2"}
    )

    assert [item.ordinal for item in output.questions] == [1, 2]
    assert [item.anchor_segment_id for item in output.questions] == [
        "segment-q1",
        "segment-a2",
    ]
    assert [item.question_kind for item in output.questions] == ["unknown", "unknown"]


@pytest.mark.asyncio
async def test_question_extraction_request_contains_only_transcript_window(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class StubRunnable:
        async def ainvoke(self, request, *_args, **_kwargs):
            calls.append(str(request["messages"][0].content))
            return {
                "structured_response": {
                    "questions": [
                        {
                            "origin": "original",
                            "questionText": "介绍项目",
                            "questionSegmentIds": ["s1"],
                            "answerSegmentIds": ["s2"],
                        }
                    ]
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    output = await agents.extract_questions(
        segments=[
            {"id": "s1", "speakerRole": "interviewer", "body": "介绍项目"},
            {"id": "s2", "speakerRole": "candidate", "body": "项目回答"},
        ],
        recording_coverage="full_dialogue",
        context=_agent_context(tmp_path),
        config={},
    )

    payload = json.loads(calls[0])
    assert set(payload) == {"contextScope", "recordingCoverage", "segments"}
    assert payload["contextScope"] == "transcript_only"
    assert output.questions[0].ordinal == 1
    assert output.questions[0].anchor_segment_id == "s1"


@pytest.mark.asyncio
async def test_question_extraction_repairs_only_invalid_candidates_and_evidence(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    invalid_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "QuestionExtractionModelOutput",
                "args": {
                    "questions": [
                        {
                            "origin": "original",
                            "questionSegmentIds": ["s1"],
                            "answerSegmentIds": ["s2"],
                        }
                    ]
                },
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )

    class StubRunnable:
        async def ainvoke(self, request, *_args, **_kwargs):
            calls.append(str(request["messages"][0].content))
            if len(calls) == 1:
                raise StructuredOutputValidationError(
                    "QuestionExtractionModelOutput",
                    ValueError("questionText Field required"),
                    invalid_message,
                )
            return {
                "structured_response": {
                    "questions": [
                        {
                            "origin": "original",
                            "questionText": "介绍项目",
                            "questionSegmentIds": ["s1"],
                            "answerSegmentIds": ["s2"],
                        }
                    ]
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    output = await agents.extract_questions(
        segments=[
            {"id": "s1", "speakerRole": "interviewer", "body": "介绍项目"},
            {"id": "s2", "speakerRole": "candidate", "body": "项目回答"},
            {
                "id": "s3",
                "speakerRole": "candidate",
                "body": "不应进入修复请求的简历隐私",
            },
        ],
        context=_agent_context(tmp_path),
        config={},
    )

    assert len(calls) == 2
    repair_payload = json.loads(calls[1])
    assert repair_payload["task"] == "repair_question_extraction_output"
    assert [item["id"] for item in repair_payload["evidenceSegments"]] == ["s1", "s2"]
    assert "不应进入修复请求的简历隐私" not in calls[1]
    assert output.questions[0].question_text == "介绍项目"


@pytest.mark.asyncio
async def test_question_extraction_stops_after_one_compact_repair(
    tmp_path: Path,
) -> None:
    calls = 0
    invalid_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "QuestionExtractionModelOutput",
                "args": {"questions": [{"answerSegmentIds": ["s1"]}]},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )

    class StubRunnable:
        async def ainvoke(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise StructuredOutputValidationError(
                "QuestionExtractionModelOutput",
                ValueError("semantic fields missing"),
                invalid_message,
            )

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    with pytest.raises(RetrospectiveQuestionExtractionModelError) as error:
        await agents.extract_questions(
            segments=[
                {"id": "s1", "speakerRole": "candidate", "body": "项目回答"}
            ],
            context=_agent_context(tmp_path),
            config={},
        )

    assert error.value.code == "schema_validation_error"
    assert calls == 2


@pytest.mark.asyncio
async def test_question_extraction_rejects_out_of_window_evidence_without_retry(
    tmp_path: Path,
) -> None:
    calls = 0

    class StubRunnable:
        async def ainvoke(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            return {
                "structured_response": {
                    "questions": [
                        {
                            "origin": "inferred",
                            "questionText": "介绍项目",
                            "answerSegmentIds": ["outside-window"],
                            "inferenceBasis": "回答介绍了项目",
                        }
                    ]
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
    )

    with pytest.raises(RetrospectiveQuestionExtractionModelError) as error:
        await agents.extract_questions(
            segments=[
                {"id": "s1", "speakerRole": "candidate", "body": "项目回答"}
            ],
            context=_agent_context(tmp_path),
            config={},
        )

    assert error.value.code == "schema_validation_error"
    assert calls == 1


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
                        "anchorSegmentId": "segment-a1",
                        "boundaryRelation": "complete",
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
    )
    analysis = render_question_analysis_input(
        question={
            "id": "q1",
            "questionKind": "motivation_hr",
            "questionText": "请做一下自我介绍",
        },
        segments=[
            {
                "id": "s2",
                "speakerRole": "candidate",
                "body": "我毕业于杭州电子科技大学，之后在华为参与数字签名服务。",
            }
        ],
        context_snapshot={
            "target": {
                "id": "target-1",
                "companyName": "字节跳动",
                "roleName": "云原生开发",
                "seniority": "",
                "document": {"bodyExcerpt": "不得发送的完整岗位文档"},
            },
            "profile": {
                "version": "profile-v1",
                "items": [
                    {
                        "claimId": "education-1",
                        "claimType": "education",
                        "supportStatus": "supported",
                        "value": {"school": "杭州电子科技大学"},
                    },
                    {
                        "claimId": "project-1",
                        "claimType": "project",
                        "supportStatus": "supported",
                        "value": {"name": "数字签名服务"},
                    },
                    {
                        "claimId": "unrelated-1",
                        "claimType": "achievement",
                        "supportStatus": "supported",
                        "value": {"title": "完全无关的开源治理成果"},
                    },
                ],
            },
            "model": {"providerModelId": "model-1"},
        },
    )
    analysis_payload = json.loads(analysis)

    assert '"segments"' in extraction
    assert "contextSnapshot" not in extraction
    assert "后端工程师" not in extraction
    assert '"question"' in analysis
    assert "storagePath" not in extraction + analysis
    assert analysis_payload["contextSnapshot"]["target"] == {
        "id": "target-1",
        "companyName": "字节跳动",
        "roleName": "云原生开发",
        "seniority": "",
    }
    assert [
        item["claimId"]
        for item in analysis_payload["contextSnapshot"]["profileEvidence"]
    ] == ["education-1", "project-1"]
    assert "不得发送的完整岗位文档" not in analysis
    assert "完全无关的开源治理成果" not in analysis


@pytest.mark.asyncio
async def test_chat_sends_history_as_complete_role_messages(tmp_path: Path) -> None:
    requests = []

    class StubRunnable:
        async def ainvoke(self, request, *_args, **_kwargs):
            requests.append(request)
            return {
                "structured_response": {
                    "resultType": "explanation",
                    "explanation": "这道题缺少失败恢复说明。",
                }
            }

    runnable = StubRunnable()
    agents = InterviewRetrospectiveAgents(
        cleanup=runnable,  # type: ignore[arg-type]
        question_extraction=runnable,  # type: ignore[arg-type]
        question_analysis=runnable,  # type: ignore[arg-type]
        chat=runnable,  # type: ignore[arg-type]
        chat_history_token_budget=8_000,
    )

    result = await agents.discuss(
        message="这道题哪里答得不好？",
        selected_question_id="question-1",
        conversation=[
            {"id": "user-1", "role": "user", "content": "先解释一下"},
            {
                "id": "assistant-1",
                "role": "assistant",
                "content": "先前的解释",
            },
        ],
        context=_agent_context(tmp_path),
        config={},
    )

    messages = requests[0]["messages"]
    assert [type(item) for item in messages] == [
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert messages[0].content == "先解释一下"
    assert messages[1].content == "先前的解释"
    current = json.loads(str(messages[2].content))
    assert current["selectedQuestionId"] == "question-1"
    assert "recentConversation" not in current
    assert result.explanation == "这道题缺少失败恢复说明。"
