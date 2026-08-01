from __future__ import annotations

import pytest

from app.graphs.interview_retrospective_cleanup import (
    create_source_windows,
    reduce_cleanup_segments,
)


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


def test_source_windows_are_bounded_and_overlap_for_context() -> None:
    windows = create_source_windows("字" * 50_000)

    assert [(item.source_start, item.source_end) for item in windows] == [
        (0, 24_000),
        (23_000, 47_000),
        (46_000, 50_000),
    ]
    assert all(len(item.body) <= 24_000 for item in windows)


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
