from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionWindow:
    first_ordinal: int
    last_ordinal: int
    segments: tuple[dict[str, object], ...]

    @property
    def work_key(self) -> str:
        return f"question_extraction:{self.first_ordinal}:{self.last_ordinal}"


def create_question_windows(
    segments: Sequence[Mapping[str, object]],
    *,
    max_characters: int = 12_000,
    overlap_segments: int = 4,
) -> tuple[QuestionWindow, ...]:
    if max_characters < 1:
        raise ValueError("问题提取窗口大小必须为正数")
    if overlap_segments < 0:
        raise ValueError("问题提取重叠段落数不能为负数")
    ordered = sorted(segments, key=lambda item: int(item["ordinal"]))
    if not ordered:
        return ()
    ordinals = [int(item["ordinal"]) for item in ordered]
    if len(ordinals) != len(set(ordinals)):
        raise ValueError("已确认段落 ordinal 不能重复")

    windows: list[QuestionWindow] = []
    start = 0
    while start < len(ordered):
        end = start
        characters = 0
        while end < len(ordered):
            size = len(str(ordered[end].get("text", "")))
            if end > start and characters + size > max_characters:
                break
            characters += size
            end += 1
            if characters >= max_characters:
                break
        payload = tuple(dict(item) for item in ordered[start:end])
        windows.append(
            QuestionWindow(
                first_ordinal=int(payload[0]["ordinal"]),
                last_ordinal=int(payload[-1]["ordinal"]),
                segments=payload,
            )
        )
        if end >= len(ordered):
            break
        start = max(start + 1, end - overlap_segments)
    return tuple(windows)


def split_question_window(window: QuestionWindow) -> tuple[QuestionWindow, ...]:
    if len(window.segments) < 2:
        return (window,)
    midpoint = len(window.segments) // 2
    halves = (window.segments[:midpoint], window.segments[midpoint:])
    return tuple(
        QuestionWindow(
            first_ordinal=int(items[0]["ordinal"]),
            last_ordinal=int(items[-1]["ordinal"]),
            segments=tuple(dict(item) for item in items),
        )
        for items in halves
        if items
    )


def reduce_extracted_questions(
    outputs: Sequence[Sequence[Mapping[str, object]]],
    *,
    segment_order: Mapping[str, int],
) -> list[dict[str, object]]:
    reduced: list[dict[str, object]] = []
    by_anchor: dict[str, dict[str, object]] = {}

    for questions in outputs:
        for source in questions:
            item = dict(source)
            anchor = str(item.get("anchorSegmentId", ""))
            if not anchor or anchor not in segment_order:
                raise ValueError("问题锚点不属于本次已确认段落")
            _validate_evidence(item, segment_order)
            if item.get("boundaryRelation") == "continues_previous" and reduced:
                _merge_question(reduced[-1], item, segment_order)
                continue
            existing = by_anchor.get(anchor)
            if existing is not None:
                _merge_question(existing, item, segment_order)
                continue
            normalized = dict(item)
            normalized["questionSegmentIds"] = _ordered_ids(
                item.get("questionSegmentIds", []), segment_order
            )
            normalized["answerSegmentIds"] = _ordered_ids(
                item.get("answerSegmentIds", []), segment_order
            )
            reduced.append(normalized)
            by_anchor[anchor] = normalized

    reduced.sort(key=lambda item: segment_order[str(item["anchorSegmentId"])])
    for ordinal, item in enumerate(reduced, start=1):
        item["ordinal"] = ordinal
    return reduced


def _merge_question(
    target: dict[str, object],
    incoming: Mapping[str, object],
    segment_order: Mapping[str, int],
) -> None:
    target["questionSegmentIds"] = _ordered_ids(
        [*target.get("questionSegmentIds", []), *incoming.get("questionSegmentIds", [])],
        segment_order,
    )
    target["answerSegmentIds"] = _ordered_ids(
        [*target.get("answerSegmentIds", []), *incoming.get("answerSegmentIds", [])],
        segment_order,
    )
    if target["questionSegmentIds"]:
        target["origin"] = "original"
        target["inferenceBasis"] = ""
    elif not str(target.get("inferenceBasis", "")).strip():
        target["inferenceBasis"] = str(incoming.get("inferenceBasis", ""))
    target["confidence"] = max(
        float(target.get("confidence", 0)), float(incoming.get("confidence", 0))
    )
    target["boundaryRelation"] = "complete"


def _ordered_ids(values: object, segment_order: Mapping[str, int]) -> list[str]:
    ids = {str(value) for value in values if str(value)} if isinstance(values, list) else set()
    return sorted(ids, key=lambda item: segment_order[item])


def _validate_evidence(
    item: Mapping[str, object], segment_order: Mapping[str, int]
) -> None:
    for field in ("questionSegmentIds", "answerSegmentIds"):
        values = item.get(field, [])
        if not isinstance(values, list) or any(str(value) not in segment_order for value in values):
            raise ValueError("问题证据片段不属于本次已确认段落")
