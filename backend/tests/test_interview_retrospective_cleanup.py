from __future__ import annotations

import pytest

from app.agents.interview_retrospective_contracts import CleanupOutput
from app.schemas.interview_retrospectives import UpdateSegmentsCommand
from app.graphs import interview_retrospective_cleanup as cleanup_graph
from app.application.session_service import ProductRepository
from app.graphs.interview_retrospective_cleanup import (
    create_source_windows,
    reduce_cleanup_result,
    reduce_cleanup_segments,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.interview_retrospectives.repository import InterviewRetrospectiveRepository
from app.interview_retrospectives.service import InterviewRetrospectiveService
from app.interview_retrospectives.errors import RetrospectiveCleanupNotConfirmed
from app.job_targets.repository import JobTargetRepository


def _segment(start: int, end: int, text: str, *, ordinal: int = 1):
    return {
        "ordinal": ordinal,
        "speakerRole": "candidate",
        "rawSpeakerLabel": "我",
        "displayName": "候选人",
        "text": text,
        "sourceStart": start,
        "sourceEnd": end,
        "confidence": 0.9,
        "uncertaintyReason": None,
    }


def test_cleanup_target_windows_cover_source_once_with_read_only_context() -> None:
    windows = cleanup_graph.create_cleanup_target_windows(
        "字" * 6_000,
        target_size=2_400,
        context_size=400,
    )

    assert [
        (item.target_start, item.target_end) for item in windows
    ] == [(0, 2_400), (2_400, 4_800), (4_800, 6_000)]
    assert [
        (item.context_start, item.context_end) for item in windows
    ] == [(0, 2_800), (2_000, 5_200), (4_400, 6_000)]
    assert "".join(item.target_text for item in windows) == "字" * 6_000


def test_cleanup_target_windows_prefer_natural_boundaries_without_overlap() -> None:
    body = ("甲" * 2_200) + "。\n" + ("乙" * 2_200)

    windows = cleanup_graph.create_cleanup_target_windows(body)

    assert windows[0].target_end == 2_202
    assert all(
        previous.target_end == current.target_start
        for previous, current in zip(windows, windows[1:], strict=False)
    )
    assert "".join(item.target_text for item in windows) == body


def test_cleanup_reduce_builds_one_document_and_locates_sparse_issues() -> None:
    assembled = cleanup_graph.assemble_cleanup_document(
        (
            (
                0,
                4,
                {
                    "correctedTarget": "候选人：甲乙。",
                    "uncertainItems": [],
                },
            ),
            (
                4,
                8,
                {
                    "correctedTarget": "候选人：数字签明。",
                    "uncertainItems": [
                        {
                            "excerpt": "数字签明",
                            "possibleValue": "数字签名",
                            "issueKind": "uncertain_term",
                            "reason": "需要确认术语",
                            "confidence": 0.7,
                        }
                    ],
                },
            ),
        ),
        source_length=8,
    )

    assert assembled.document_body == "候选人：甲乙。候选人：数字签明。"
    assert assembled.review_issues == (
        {
            "document_start": 11,
            "document_end": 15,
            "excerpt": "数字签明",
            "suggestion": "数字签名",
            "issue_kind": "uncertain_term",
            "reason": "需要确认术语",
            "confidence": 0.7,
        },
    )


def test_cleanup_reduce_drops_ambiguous_candidate_from_user_review() -> None:
    corrected = "候选人：数字签名用于发布，数字签名用于部署。"

    assembled = cleanup_graph.assemble_cleanup_document(
        (
            (
                0,
                8,
                {
                    "correctedTarget": corrected,
                    "uncertainItems": [
                        {
                            "excerpt": "数字签名",
                            "possibleValue": "代码签名",
                            "issueKind": "uncertain_term",
                            "reason": "术语可能有误",
                            "confidence": 0.6,
                        }
                    ],
                },
            ),
        ),
        source_length=8,
    )

    assert assembled.document_body == corrected
    assert assembled.review_issues == ()


@pytest.mark.parametrize(
    ("possible_value", "issue_kind"),
    (("数字签名", "uncertain_term"), (None, "uncertain_term")),
)
def test_cleanup_reduce_drops_non_actionable_term_uncertainty(
    possible_value: str | None,
    issue_kind: str,
) -> None:
    assembled = cleanup_graph.assemble_cleanup_document(
        (
            (
                0,
                4,
                {
                    "correctedTarget": "我使用数字签名。",
                    "uncertainItems": [
                        {
                            "excerpt": "数字签名",
                            "possibleValue": possible_value,
                            "issueKind": issue_kind,
                            "reason": "模型不能百分之百确认",
                            "confidence": 0.6,
                        }
                    ],
                },
            ),
        ),
        source_length=4,
    )

    assert assembled.review_issues == ()


def test_cleanup_reduce_keeps_exact_speaker_ambiguity_for_manual_review() -> None:
    assembled = cleanup_graph.assemble_cleanup_document(
        (
            (
                0,
                4,
                {
                    "correctedTarget": "这部分可能由面试官补充。",
                    "uncertainItems": [
                        {
                            "excerpt": "这部分可能由面试官补充。",
                            "possibleValue": None,
                            "issueKind": "speaker",
                            "reason": "无法确认说话人",
                            "confidence": 0.45,
                        }
                    ],
                },
            ),
        ),
        source_length=4,
    )

    assert len(assembled.review_issues) == 1
    assert assembled.review_issues[0]["issue_kind"] == "speaker"


def test_source_windows_are_bounded_and_overlap_for_context() -> None:
    windows = create_source_windows("字" * 9_850)

    assert [(item.source_start, item.source_end) for item in windows] == [
        (0, 4_000),
        (3_600, 7_600),
        (7_200, 9_850),
    ]
    assert all(len(item.body) <= 4_000 for item in windows)


def test_source_windows_prefer_natural_boundaries_and_cover_long_text() -> None:
    body = ("甲" * 3_900) + "。\n" + ("乙" * 3_900)

    windows = create_source_windows(body)

    assert windows[0].source_end == 3_902
    assert windows[-1].source_end == len(body)
    assert all(len(item.body) <= 4_000 for item in windows)
    assert all(
        current.source_start <= previous.source_end
        for previous, current in zip(windows, windows[1:], strict=False)
    )


def test_timeout_split_keeps_absolute_offsets_and_bounded_overlap() -> None:
    children = cleanup_graph.split_source_window(
        "字" * 10_000,
        source_start=2_000,
        source_end=8_000,
    )

    assert children[0].source_start == 2_000
    assert children[-1].source_end == 8_000
    assert len(children) == 2
    assert children[1].source_start < children[0].source_end


def test_speaker_hints_are_deduplicated_and_bounded() -> None:
    outputs = [
        [
            {
                "rawSpeakerLabel": "说话人1",
                "speakerRole": "interviewer",
                "displayName": "面试官",
            },
            {
                "rawSpeakerLabel": "说话人1",
                "speakerRole": "interviewer",
                "displayName": "面试官",
            },
            {
                "rawSpeakerLabel": None,
                "speakerRole": "candidate",
                "displayName": "我",
            },
        ]
    ]

    hints = cleanup_graph.speaker_hints_from_outputs(outputs)

    assert hints == (
        {
            "rawSpeakerLabel": "说话人1",
            "speakerRole": "interviewer",
            "displayName": "面试官",
        },
    )


def test_cleanup_materialization_derives_exact_correction_from_source_diff() -> None:
    source = "我用了瑞迪斯。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "speakerRole": "candidate",
                            "rawSpeakerLabel": "我",
                            "displayName": "候选人",
                            "correctedText": "我用了 Redis。",
                            "confidence": 0.96,
                            "uncertaintyReason": None,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
        terminology_hints=("Redis",),
    )

    assert result.segments[0].text == "我用了 Redis。"
    assert result.corrections[0].source_start == 3
    assert result.corrections[0].source_end == 6
    assert result.corrections[0].original_text == "瑞迪斯"
    assert result.corrections[0].suggested_text == " Redis"
    assert result.corrections[0].risk_level == "low"


def test_cleanup_materialization_restores_multiple_dialogue_turns_from_one_source_unit() -> None:
    source = "你负责什么？我负责云服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": "你负责什么？",
                            "speakerRole": "interviewer",
                            "displayName": "面试官",
                            "correctedText": "你负责什么？",
                            "confidence": 0.95,
                        },
                        {
                            "sourceText": "我负责云服务开发。",
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": "我负责云服务开发。",
                            "confidence": 0.96,
                        },
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert [segment.speaker_role for segment in result.segments] == [
        "interviewer",
        "candidate",
    ]
    assert [segment.text for segment in result.segments] == [
        "你负责什么？",
        "我负责云服务开发。",
    ]
    assert [
        (segment.source_start, segment.source_end) for segment in result.segments
    ] == [(0, 6), (6, len(source))]


def test_cleanup_materialization_recovers_omitted_first_turn_source_text() -> None:
    source = "你负责什么？我负责云服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "speakerRole": "interviewer",
                            "displayName": "面试官",
                            "correctedText": "你负责什么？",
                            "confidence": 0.95,
                        },
                        {
                            "sourceText": "我负责云服务开发。",
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": "我负责云服务开发。",
                            "confidence": 0.96,
                        },
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert [segment.speaker_role for segment in result.segments] == [
        "interviewer",
        "candidate",
    ]
    assert [segment.text for segment in result.segments] == [
        "你负责什么？",
        "我负责云服务开发。",
    ]
    assert [
        (segment.source_start, segment.source_end) for segment in result.segments
    ] == [(0, 6), (6, len(source))]


def test_cleanup_materialization_recovers_boundaries_when_provider_formats_source_text() -> None:
    source = (
        "第一段。。呃 ，你说网站功能吗 ？"
        "哦哦 ，总有这一套服务吗呃 ，我觉得这个台风是有那个呃有必要的呀，"
        "然后的话呃出于功能最小化设计。"
    )
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "speakerRole": "candidate",
                            "correctedText": "第一段。",
                            "confidence": 0.9,
                        },
                        {
                            "sourceText": "呃 ，你说网站功能吗 ？",
                            "speakerRole": "interviewer",
                            "correctedText": "你说网站功能吗？",
                            "confidence": 0.9,
                        },
                        {
                            "sourceText": (
                                "哦哦，总有这一套服务吗？我觉得这个拆分是有必要的呀，"
                                "然后出于功能最小化设计。"
                            ),
                            "speakerRole": "candidate",
                            "correctedText": (
                                "哦哦，总有这一套服务吗？我觉得这个拆分是有必要的呀，"
                                "然后出于功能最小化设计。"
                            ),
                            "confidence": 0.9,
                        },
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    question_start = source.index("呃")
    answer_start = source.index("哦哦")
    assert [
        (segment.source_start, segment.source_end) for segment in result.segments
    ] == [
        (0, question_start),
        (question_start, answer_start),
        (answer_start, len(source)),
    ]
    assert [segment.text for segment in result.segments] == [
        "第一段。",
        "你说网站功能吗？",
        "哦哦，总有这一套服务吗？我觉得这个拆分是有必要的呀，然后出于功能最小化设计。",
    ]


def test_cleanup_materialization_safely_collapses_unverifiable_turn_boundaries() -> None:
    source = "你负责什么？我负责云服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "turns": [
                        {
                            "speakerRole": "interviewer",
                            "correctedText": "你负责什么？",
                            "confidence": 0.95,
                        },
                        {
                            "speakerRole": "candidate",
                            "correctedText": "我负责云服务开发。",
                            "confidence": 0.96,
                        },
                    ],
                }
            ]
        }
    )

    model_output.validate_units(expected_unit_ids=(units[0].unit_id,))
    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert len(result.segments) == 1
    assert result.segments[0].speaker_role == "unknown"
    assert result.segments[0].display_name == "待确认"
    assert result.segments[0].source_start == 0
    assert result.segments[0].source_end == len(source)
    assert "切分边界" in (result.segments[0].uncertainty_reason or "")


def test_cleanup_materialization_collapses_turns_that_do_not_exactly_cover_source_unit() -> None:
    source = "你负责什么？我负责云服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": "你做了什么？",
                            "speakerRole": "interviewer",
                            "displayName": "面试官",
                            "correctedText": "你做了什么？",
                            "confidence": 0.95,
                        },
                        {
                            "sourceText": "我负责云服务开发。",
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": "我负责云服务开发。",
                            "confidence": 0.96,
                        },
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert len(result.segments) == 1
    assert result.segments[0].speaker_role == "unknown"
    assert result.segments[0].source_start == 0
    assert result.segments[0].source_end == len(source)
    assert "切分边界" in (result.segments[0].uncertainty_reason or "")


def test_cleanup_materialization_ignores_single_turn_provider_source_text() -> None:
    source = "我负责云服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": "我主导云服务开发。",
                            "speakerRole": "candidate",
                            "correctedText": "我负责云服务开发。",
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].source_start == 0
    assert result.segments[0].source_end == len(source)
    assert result.segments[0].text == source


def test_cleanup_materialization_preserves_missing_source_unit_for_review() -> None:
    source = "第一句。第二句。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
        max_unit_characters=4,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "speakerRole": "candidate",
                            "correctedText": units[0].text,
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert len(result.segments) == len(units)
    assert result.segments[-1].text == units[-1].text
    assert result.segments[-1].speaker_role == "unknown"
    assert "保留原文" in (result.segments[-1].uncertainty_reason or "")


def test_cleanup_materialization_applies_formatting_insert_without_duplication() -> None:
    source = "你好世界"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "unknown",
                            "displayName": "未知说话人",
                            "correctedText": "你好，世界",
                            "confidence": 0.8,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == "你好，世界"


@pytest.mark.parametrize(
    ("source", "corrected"),
    [
        ("嗯，那个，我负责云服务。", "我负责云服务。"),
        ("我我负责云服务。", "我负责云服务。"),
        ("这个方案可以可以落地。", "这个方案可以落地。"),
    ],
)
def test_cleanup_materialization_auto_applies_safe_filler_and_adjacent_repetition_cleanup(
    source: str,
    corrected: str,
) -> None:
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": corrected,
                            "confidence": 0.95,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == corrected
    assert result.corrections
    assert all(item.risk_level == "low" for item in result.corrections)


def test_cleanup_materialization_uses_full_corrected_term_to_match_partial_asr_diff() -> None:
    source = "我做过数字签明服务。"
    corrected = "我做过数字签名服务。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": corrected,
                            "confidence": 0.96,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
        terminology_hints=("数字签名",),
    )

    assert result.segments[0].text == corrected
    assert result.corrections[0].change_type == "recognition"
    assert result.corrections[0].risk_level == "low"


def test_cleanup_materialization_adopts_small_unclassified_asr_correction() -> None:
    source = "我使用签明服务。"
    corrected = "我使用签名服务。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": corrected,
                            "confidence": 0.95,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == corrected
    assert len(result.corrections) == 1
    assert result.corrections[0].suggested_text == "名"
    assert result.corrections[0].risk_level == "low"


def test_cleanup_materialization_uses_model_draft_for_bounded_transcript_cleanup() -> None:
    source = (
        "嗯。方怎样喂喂你好，可以可以。好的，我首先自我介绍一下，"
        "就是呃我叫一涛，然后我是那个 2020年本科毕业于杭州电子科技大学。"
        "然后我是那个呃信息安传专业。"
    )
    corrected = (
        "嗯，喂，你好，可以可以。好的，我首先自我介绍一下，我叫一涛，"
        "2020年本科毕业于杭州电子科技大学，信息安全专业。"
    )
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "我",
                            "correctedText": corrected,
                            "confidence": 0.92,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == corrected
    assert result.corrections
    assert all(correction.risk_level == "low" for correction in result.corrections)


def test_cleanup_materialization_never_auto_applies_responsibility_upgrade_from_hint() -> None:
    source = "我参与了服务开发。"
    corrected = "我负责了服务开发。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": corrected,
                            "confidence": 0.99,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
        terminology_hints=("负责",),
    )

    assert result.segments[0].text == corrected
    assert result.corrections[0].risk_level == "high"
    assert result.corrections[0].change_type == "semantic"


def test_cleanup_materialization_keeps_numeric_semantic_change_for_review() -> None:
    source = "延迟降低了百分之十。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": "延迟降低了 30%。",
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == "延迟降低了 30%。"
    assert result.corrections[0].risk_level == "high"
    assert result.corrections[0].change_type == "semantic"


def test_cleanup_materialization_shows_unreliable_rewording_but_blocks_review() -> None:
    source = "我负责这个项目。"
    units = cleanup_graph.create_source_units(
        source,
        source_start=0,
        source_end=len(source),
        emit_start=0,
    )
    model_output = CleanupOutput.model_validate(
        {
            "units": [
                {
                    "unitId": units[0].unit_id,
                    "turns": [
                        {
                            "sourceText": source,
                            "speakerRole": "candidate",
                            "displayName": "候选人",
                            "correctedText": "这个项目由我负责。",
                            "confidence": 0.9,
                        }
                    ],
                }
            ]
        }
    )

    result = cleanup_graph.materialize_cleanup_output(
        source_units=units,
        model_output=model_output,
    )

    assert result.segments[0].text == "这个项目由我负责。"
    assert len(result.corrections) == 1
    assert result.corrections[0].original_text == source
    assert result.corrections[0].suggested_text == "这个项目由我负责。"
    assert result.corrections[0].risk_level == "high"


def test_cleanup_update_command_accepts_more_than_one_thousand_bulk_keep_decisions() -> None:
    command = UpdateSegmentsCommand.model_validate(
        {
            "workspaceId": "workspace-1",
            "expectedVersion": 3,
            "segments": [
                {
                    "speakerRole": "candidate",
                    "rawSpeakerLabel": "我",
                    "displayName": "我",
                    "body": "原文",
                    "sourceStart": 0,
                    "sourceEnd": 2,
                    "confidence": 0.9,
                    "uncertaintyReason": None,
                    "ignored": False,
                }
            ],
            "correctionDecisions": [
                {
                    "id": f"correction-{index}",
                    "decision": "kept_original",
                    "manualText": None,
                }
                for index in range(1_006)
            ],
        }
    )

    assert len(command.correction_decisions) == 1_006


def test_reducer_orders_by_source_offset_and_deduplicates_overlap() -> None:
    reduced = reduce_cleanup_segments(
        [
            [_segment(23_100, 23_120, "重复片段")],
            [
                _segment(23_100, 23_120, " 重复片段 "),
                _segment(24_000, 24_020, "后续片段", ordinal=2),
            ],
            [_segment(0, 10, "开头片段")],
        ]
    )

    assert [item["text"] for item in reduced] == [
        "开头片段",
        "重复片段",
        "后续片段",
    ]
    assert [item["ordinal"] for item in reduced] == [1, 2, 3]


def test_reducer_rejects_offset_regression_within_one_window() -> None:
    with pytest.raises(ValueError, match="offset"):
        reduce_cleanup_segments(
            [[_segment(10, 20, "后"), _segment(0, 5, "前", ordinal=2)]]
        )


def test_cleanup_result_reducer_deduplicates_corrections_from_overlap() -> None:
    correction = {
        "segmentOrdinal": 1,
        "sourceStart": 4,
        "sourceEnd": 7,
        "originalText": "瑞迪斯",
        "suggestedText": "Redis",
        "changeType": "recognition",
        "riskLevel": "low",
        "reason": "技术名词可唯一确定",
        "confidence": 0.96,
    }

    result = reduce_cleanup_result(
        [
            {"segments": [_segment(0, 12, "我使用 Redis")], "corrections": [correction]},
            {"segments": [_segment(0, 12, "我使用 Redis")], "corrections": [correction]},
        ]
    )

    assert len(result["segments"]) == 1
    assert result["corrections"] == ({**correction, "segmentOrdinal": 1},)


def test_cleanup_result_reducer_upgrades_conflicting_suggestions_to_high_risk() -> None:
    first = {
        "segmentOrdinal": 1,
        "sourceStart": 4,
        "sourceEnd": 7,
        "originalText": "瑞迪斯",
        "suggestedText": "Redis",
        "changeType": "recognition",
        "riskLevel": "low",
        "reason": "技术名词可唯一确定",
        "confidence": 0.96,
    }
    second = {**first, "suggestedText": "Redisson", "confidence": 0.72}

    result = reduce_cleanup_result(
        [
            {"segments": [_segment(0, 12, "我使用 Redis")], "corrections": [first]},
            {"segments": [_segment(0, 12, "我使用 Redis")], "corrections": [second]},
        ]
    )

    assert result["corrections"][0]["riskLevel"] == "high"
    assert result["corrections"][0]["suggestedText"] is None
    assert "冲突" in result["corrections"][0]["reason"]


def _cleanup_repository(tmp_path):
    connection = connect_runtime_database(tmp_path)
    products = ProductRepository(connection)
    targets = JobTargetRepository(connection)
    repository = InterviewRetrospectiveRepository(connection)
    service = InterviewRetrospectiveService(
        workspace_id="w1", repository=repository, job_targets=targets
    )
    target = targets.create_target(
        workspace_id="w1",
        role_name="后端工程师",
        seniority="3-5 年",
        company_name="示例公司",
        source_url=None,
    )
    analysis = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.analysis",
        title="复盘分析",
        visibility="system",
    )
    chat = products.create_session(
        workspace_id="w1",
        kind="interview.retrospective.chat",
        title="复盘讨论",
    )
    retrospective = service.create(
        job_target_id=target.id,
        title="示例公司后端一面",
        round_label="一面",
        interview_date=None,
        outcome="unrecorded",
        note="",
        analysis_session_id=analysis.id,
        chat_session_id=chat.id,
        idempotency_key="create-retrospective",
    )
    source = service.add_source_version(
        retrospective.id,
        source_kind="transcript",
        body="字" * 50_000,
        file_name=None,
        idempotency_key="source-version",
    )
    return connection, repository, retrospective, source


def test_cleanup_work_items_resume_only_unfinished_windows(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    windows = create_source_windows(source.body)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=windows,
    )

    items = repository.list_cleanup_work_items(cleanup.id)
    first = repository.claim_cleanup_work_item(items[0].id)
    repository.complete_cleanup_work_item(
        first.id,
        output={"segments": [_segment(0, 10, "开头片段")]},
    )

    pending = repository.list_resumable_cleanup_work_items(cleanup.id)
    assert cleanup.status == "queued"
    assert len(items) == len(windows)
    assert [item.source_start for item in pending] == [
        window.source_start for window in windows[1:]
    ]
    assert repository.list_cleanup_work_items(cleanup.id)[0].status == "completed"
    connection.close()


def test_stopping_cleanup_preserves_completed_window_output(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    first = repository.claim_cleanup_work_item(
        repository.list_cleanup_work_items(cleanup.id)[0].id
    )
    repository.complete_cleanup_work_item(
        first.id,
        output={"segments": [_segment(0, 10, "已完成")]} ,
    )

    stopped = repository.stop_cleanup(cleanup.id)
    items = repository.list_cleanup_work_items(cleanup.id)

    assert stopped.status == "stopped"
    assert items[0].status == "completed"
    assert items[0].output is not None
    assert all(item.status == "interrupted" for item in items[1:])
    connection.close()


def test_reconcile_interrupted_execution_makes_cleanup_resumable(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    products = ProductRepository(connection)
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    execution = products.create_execution(
        retrospective.analysis_session_id,
        input={},
        model_bindings={},
    )
    repository.attach_cleanup_execution(cleanup.id, execution_id=execution.id)
    repository.claim_cleanup_work_item(
        repository.list_cleanup_work_items(cleanup.id)[0].id
    )
    products.interrupt_running()

    reconciled = repository.reconcile_interrupted_cleanup_runs()
    current = repository.get_cleanup_version(cleanup.id)

    assert reconciled == (cleanup.id,)
    assert current.status == "stopped"
    assert repository.list_cleanup_work_items(cleanup.id)[0].status == "interrupted"
    connection.close()


def test_high_risk_correction_blocks_confirmation_until_user_accepts(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    service = InterviewRetrospectiveService(
        workspace_id="w1",
        repository=repository,
        job_targets=JobTargetRepository(connection),
    )
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    segment = {
        "speaker_role": "candidate",
        "raw_speaker_label": "我",
        "display_name": "候选人",
        "body": "不",
        "source_start": 0,
        "source_end": 1,
        "confidence": 0.8,
        "uncertainty_reason": None,
        "ignored": False,
    }
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(segment,),
        corrections=(
            {
                "segment_ordinal": 1,
                "source_start": 0,
                "source_end": 1,
                "original_text": "字",
                "suggested_text": "不",
                "change_type": "semantic",
                "risk_level": "high",
                "reason": "否定关系可能被误识别",
                "confidence": 0.6,
            },
        ),
    )
    connection.execute(
        "UPDATE interview_cleanup_versions SET status = 'running' WHERE id = ?",
        (cleanup.id,),
    )
    connection.commit()
    cleanup = repository.mark_cleanup_review_pending(cleanup.id)

    assert repository.list_segments(cleanup.id)[0].body == "不"
    assert repository.list_corrections(cleanup.id)[0].adopted_text == "不"

    with pytest.raises(RetrospectiveCleanupNotConfirmed, match="高风险"):
        service.confirm_cleanup(
            retrospective.id,
            cleanup.id,
            expected_version=cleanup.version,
            idempotency_key="confirm-pending",
        )

    correction = repository.list_corrections(cleanup.id)[0]
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(segment,),
        correction_decisions=(
            {
                "id": correction.id,
                "decision": "accepted",
                "manual_text": None,
            },
        ),
    )

    assert repository.list_segments(cleanup.id)[0].body == "不"
    confirmed = service.confirm_cleanup(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        idempotency_key="confirm-accepted",
    )
    assert confirmed.status == "confirmed"
    with pytest.raises(ValueError, match="已确认"):
        service.replace_segments(
            retrospective.id,
            cleanup.id,
            expected_version=confirmed.version,
            segments=({**segment, "body": "不能覆盖历史"},),
        )
    connection.close()


def test_high_risk_model_text_can_be_replaced_with_original_before_confirmation(
    tmp_path,
) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    service = InterviewRetrospectiveService(
        workspace_id="w1",
        repository=repository,
        job_targets=JobTargetRepository(connection),
    )
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    model_segment = {
        "speaker_role": "candidate",
        "raw_speaker_label": "我",
        "display_name": "候选人",
        "body": "不",
        "source_start": 0,
        "source_end": 1,
        "confidence": 0.8,
        "uncertainty_reason": None,
        "ignored": False,
    }
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(model_segment,),
        corrections=(
            {
                "segment_ordinal": 1,
                "source_start": 0,
                "source_end": 1,
                "original_text": "字",
                "suggested_text": "不",
                "change_type": "semantic",
                "risk_level": "high",
                "reason": "否定关系可能被误识别",
                "confidence": 0.6,
            },
        ),
    )
    correction = repository.list_corrections(cleanup.id)[0]

    service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(model_segment,),
        correction_decisions=(
            {
                "id": correction.id,
                "decision": "kept_original",
                "manual_text": None,
            },
        ),
    )

    assert repository.list_segments(cleanup.id)[0].body == "字"
    assert repository.list_corrections(cleanup.id)[0].adopted_text == "字"
    connection.close()


def test_cleanup_service_rejects_correction_that_does_not_match_source(tmp_path) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    service = InterviewRetrospectiveService(
        workspace_id="w1",
        repository=repository,
        job_targets=JobTargetRepository(connection),
    )
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )

    with pytest.raises(ValueError, match="不可变原文"):
        service.replace_segments(
            retrospective.id,
            cleanup.id,
            expected_version=cleanup.version,
            segments=(
                {
                    "speaker_role": "candidate",
                    "raw_speaker_label": "我",
                    "display_name": "候选人",
                    "body": "字",
                    "source_start": 0,
                    "source_end": 1,
                    "confidence": 0.8,
                    "uncertainty_reason": None,
                    "ignored": False,
                },
            ),
            corrections=(
                {
                    "segment_ordinal": 1,
                    "source_start": 0,
                    "source_end": 1,
                    "original_text": "错",
                    "suggested_text": "字",
                    "change_type": "recognition",
                    "risk_level": "low",
                    "reason": "错误证据",
                    "confidence": 0.9,
                },
            ),
        )
    connection.close()


def test_manual_segment_edit_supersedes_model_corrections_with_audit_record(
    tmp_path,
) -> None:
    connection, repository, retrospective, source = _cleanup_repository(tmp_path)
    service = InterviewRetrospectiveService(
        workspace_id="w1",
        repository=repository,
        job_targets=JobTargetRepository(connection),
    )
    cleanup = repository.insert_cleanup_run(
        retrospective.id,
        source_version_id=source.id,
        input_digest=source.content_sha256,
        windows=create_source_windows(source.body),
    )
    segment = {
        "speaker_role": "candidate",
        "raw_speaker_label": "我",
        "display_name": "候选人",
        "body": "词",
        "source_start": 0,
        "source_end": 1,
        "confidence": 0.8,
        "uncertainty_reason": None,
        "ignored": False,
    }
    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=(segment,),
        corrections=(
            {
                "segment_ordinal": 1,
                "source_start": 0,
                "source_end": 1,
                "original_text": "字",
                "suggested_text": "词",
                "change_type": "recognition",
                "risk_level": "low",
                "reason": "识别错误",
                "confidence": 0.9,
            },
        ),
    )
    model_correction = repository.list_corrections(cleanup.id)[0]

    cleanup = service.replace_segments(
        retrospective.id,
        cleanup.id,
        expected_version=cleanup.version,
        segments=({**segment, "body": "用户手工修正"},),
        correction_decisions=(
            {
                "id": model_correction.id,
                "decision": "accepted",
                "manual_text": None,
            },
        ),
    )

    corrections = repository.list_corrections(cleanup.id)
    assert corrections[0].decision == "superseded"
    assert corrections[1].decision == "manual"
    assert corrections[1].original_text == "字"
    assert corrections[1].adopted_text == "用户手工修正"
    connection.close()
