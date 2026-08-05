from __future__ import annotations

from app.graphs.interview_retrospective_question_extraction import (
    create_question_windows,
    reduce_extracted_questions,
)


def _segment(ordinal: int, text: str) -> dict[str, object]:
    return {
        "id": f"segment-{ordinal}",
        "ordinal": ordinal,
        "speakerRole": "candidate",
        "displayName": "候选人",
        "text": text,
    }


def _question(
    *,
    ordinal: int,
    anchor: str,
    text: str,
    question_ids: list[str],
    answer_ids: list[str],
    boundary: str = "complete",
) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "questionKind": "technical_knowledge",
        "origin": "original" if question_ids else "inferred",
        "questionText": text,
        "anchorSegmentId": anchor,
        "boundaryRelation": boundary,
        "questionSegmentIds": question_ids,
        "answerSegmentIds": answer_ids,
        "inferenceBasis": "回答明确讨论了该主题" if not question_ids else "",
        "confidence": 0.8,
    }


def test_question_windows_are_bounded_and_overlap_by_confirmed_segment() -> None:
    segments = [_segment(index, str(index) * 6_000) for index in range(1, 5)]

    windows = create_question_windows(
        segments,
        max_characters=12_000,
        overlap_segments=1,
    )

    assert [(item.first_ordinal, item.last_ordinal) for item in windows] == [
        (1, 2),
        (2, 3),
        (3, 4),
    ]
    assert [item.work_key for item in windows] == [
        "question_extraction:1:2",
        "question_extraction:2:3",
        "question_extraction:3:4",
    ]
    assert all(sum(len(str(segment["text"])) for segment in item.segments) <= 12_000 for item in windows)


def test_reducer_unions_overlap_evidence_for_the_same_anchor() -> None:
    reduced = reduce_extracted_questions(
        [
            [_question(ordinal=1, anchor="segment-2", text="如何治理缓存？", question_ids=["segment-2"], answer_ids=["segment-3"])],
            [_question(ordinal=1, anchor="segment-2", text="缓存怎么治理？", question_ids=["segment-2"], answer_ids=["segment-3", "segment-4"])],
        ],
        segment_order={f"segment-{index}": index for index in range(1, 6)},
    )

    assert len(reduced) == 1
    assert reduced[0]["anchorSegmentId"] == "segment-2"
    assert reduced[0]["answerSegmentIds"] == ["segment-3", "segment-4"]
    assert reduced[0]["ordinal"] == 1


def test_reducer_keeps_repeated_questions_with_different_anchors() -> None:
    reduced = reduce_extracted_questions(
        [
            [_question(ordinal=1, anchor="segment-2", text="为什么用 Redis？", question_ids=["segment-2"], answer_ids=["segment-3"])],
            [_question(ordinal=1, anchor="segment-8", text="为什么用 Redis？", question_ids=["segment-8"], answer_ids=["segment-9"])],
        ],
        segment_order={f"segment-{index}": index for index in range(1, 10)},
    )

    assert [item["anchorSegmentId"] for item in reduced] == ["segment-2", "segment-8"]


def test_reducer_attaches_a_leading_continuation_to_the_previous_question() -> None:
    reduced = reduce_extracted_questions(
        [
            [_question(ordinal=1, anchor="segment-2", text="介绍一下项目。", question_ids=["segment-2"], answer_ids=["segment-3"])],
            [_question(ordinal=1, anchor="segment-4", text="继续说明。", question_ids=[], answer_ids=["segment-4"], boundary="continues_previous")],
        ],
        segment_order={f"segment-{index}": index for index in range(1, 6)},
    )

    assert len(reduced) == 1
    assert reduced[0]["anchorSegmentId"] == "segment-2"
    assert reduced[0]["answerSegmentIds"] == ["segment-3", "segment-4"]
