from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Mapping

from app.agents.interview_retrospective_contracts import (
    CleanupCorrection,
    CleanupOutput,
    CleanupSegment,
    CleanupTurnOutput,
    CleanupUnitOutput,
    MaterializedCleanupOutput,
)


MAX_WINDOW_CHARACTERS = 4_000
WINDOW_OVERLAP_CHARACTERS = 400
ADAPTIVE_SPLIT_MIN_CHARACTERS = 2_500
MAX_SPEAKER_HINTS = 8
MAX_SOURCE_UNIT_CHARACTERS = 800
TARGET_WINDOW_CHARACTERS = 2_400
TARGET_CONTEXT_CHARACTERS = 400


@dataclass(frozen=True, slots=True)
class SourceWindow:
    ordinal: int
    source_start: int
    source_end: int
    body: str

    @property
    def work_key(self) -> str:
        return f"window:{self.source_start}:{self.source_end}"


@dataclass(frozen=True, slots=True)
class CleanupTargetWindow:
    ordinal: int
    context_start: int
    target_start: int
    target_end: int
    context_end: int
    before_context: str
    target_text: str
    after_context: str

    @property
    def source_start(self) -> int:
        return self.target_start

    @property
    def source_end(self) -> int:
        return self.target_end

    @property
    def body(self) -> str:
        return self.target_text

    @property
    def work_key(self) -> str:
        return f"target:{self.target_start}:{self.target_end}"


@dataclass(frozen=True, slots=True)
class AssembledCleanDocument:
    document_body: str
    review_issues: tuple[dict[str, object], ...]


def create_cleanup_target_windows(
    body: str,
    *,
    target_size: int = TARGET_WINDOW_CHARACTERS,
    context_size: int = TARGET_CONTEXT_CHARACTERS,
) -> tuple[CleanupTargetWindow, ...]:
    if not body:
        return ()
    if target_size <= 0 or context_size < 0:
        raise ValueError("目标窗口或上下文大小无效")
    windows: list[CleanupTargetWindow] = []
    target_start = 0
    while target_start < len(body):
        hard_end = min(target_start + target_size, len(body))
        target_end = (
            hard_end
            if hard_end == len(body)
            else _natural_window_end(
                body,
                source_start=target_start,
                hard_end=hard_end,
                window_size=target_size,
            )
        )
        context_start = max(0, target_start - context_size)
        context_end = min(len(body), target_end + context_size)
        windows.append(
            CleanupTargetWindow(
                ordinal=len(windows) + 1,
                context_start=context_start,
                target_start=target_start,
                target_end=target_end,
                context_end=context_end,
                before_context=body[context_start:target_start],
                target_text=body[target_start:target_end],
                after_context=body[target_end:context_end],
            )
        )
        target_start = target_end
    return tuple(windows)


def split_cleanup_target_window(
    body: str,
    *,
    target_start: int,
    target_end: int,
    context_size: int = TARGET_CONTEXT_CHARACTERS,
) -> tuple[CleanupTargetWindow, ...]:
    if target_start < 0 or target_end > len(body) or target_end <= target_start:
        raise ValueError("待拆分目标窗口无效")
    length = target_end - target_start
    if length <= 800:
        return ()
    half = (length + 1) // 2
    split_at = _natural_window_end(
        body,
        source_start=target_start,
        hard_end=target_start + half,
        window_size=half,
    )
    if split_at <= target_start or split_at >= target_end:
        split_at = target_start + half
    ranges = ((target_start, split_at), (split_at, target_end))
    return tuple(
        _target_window(
            body,
            ordinal=ordinal,
            target_start=start,
            target_end=end,
            context_size=context_size,
        )
        for ordinal, (start, end) in enumerate(ranges, start=1)
    )


def assemble_cleanup_document(
    window_outputs: Iterable[tuple[int, int, Mapping[str, object]]],
    *,
    source_length: int,
) -> AssembledCleanDocument:
    ordered = sorted(window_outputs, key=lambda item: (item[0], item[1]))
    expected_start = 0
    document_parts: list[str] = []
    review_issues: list[dict[str, object]] = []
    document_length = 0
    for target_start, target_end, output in ordered:
        if target_start != expected_start or target_end <= target_start:
            raise ValueError("整理目标窗口没有无缝覆盖原文")
        corrected_target = str(
            output.get("correctedTarget") or output.get("corrected_target") or ""
        )
        if not corrected_target:
            raise ValueError("整理目标窗口没有返回正文")
        document_parts.append(corrected_target)
        raw_issues = output.get("uncertainItems") or output.get("uncertain_items") or ()
        for raw_issue in raw_issues:
            if not isinstance(raw_issue, Mapping):
                raise ValueError("整理目标窗口的不确定项格式无效")
            original_excerpt = str(raw_issue.get("excerpt") or "")
            possible_value_raw = raw_issue.get("possibleValue") or raw_issue.get(
                "possible_value"
            )
            possible_value = (
                str(possible_value_raw).strip() if possible_value_raw else None
            )
            issue_kind = str(
                raw_issue.get("issueKind")
                or raw_issue.get("issue_kind")
                or "semantic"
            )
            excerpt = original_excerpt
            first = corrected_target.find(excerpt) if excerpt else -1
            unique = first >= 0 and corrected_target.find(excerpt, first + 1) < 0
            # Provider uncertainty is diagnostic evidence, not automatically a
            # user task. Only exact, uniquely located issues can enter the review
            # queue; otherwise the raw response remains available in the trace.
            if not unique:
                continue
            if possible_value == excerpt.strip():
                continue
            # A normal-looking term without a concrete alternative does not give
            # the user an actionable decision. Speaker/semantic ambiguity may still
            # require a manual keep/edit decision even without a replacement.
            if issue_kind == "uncertain_term" and possible_value is None:
                continue
            local_start = first
            local_end = first + len(excerpt)
            reason = str(raw_issue.get("reason") or "需要人工确认")
            review_issues.append(
                {
                    "document_start": document_length + local_start,
                    "document_end": document_length + local_end,
                    "excerpt": excerpt,
                    "suggestion": possible_value,
                    "issue_kind": issue_kind,
                    "reason": reason,
                    "confidence": float(raw_issue.get("confidence", 0)),
                }
            )
        document_length += len(corrected_target)
        expected_start = target_end
    if expected_start != source_length:
        raise ValueError("整理目标窗口没有覆盖完整原文")
    return AssembledCleanDocument(
        document_body="".join(document_parts),
        review_issues=tuple(review_issues),
    )


def _target_window(
    body: str,
    *,
    ordinal: int,
    target_start: int,
    target_end: int,
    context_size: int,
) -> CleanupTargetWindow:
    context_start = max(0, target_start - context_size)
    context_end = min(len(body), target_end + context_size)
    return CleanupTargetWindow(
        ordinal=ordinal,
        context_start=context_start,
        target_start=target_start,
        target_end=target_end,
        context_end=context_end,
        before_context=body[context_start:target_start],
        target_text=body[target_start:target_end],
        after_context=body[target_end:context_end],
    )


@dataclass(frozen=True, slots=True)
class SourceUnit:
    unit_id: str
    source_start: int
    source_end: int
    text: str
    emit: bool

    def as_prompt_dict(self) -> dict[str, object]:
        return {
            "unitId": self.unit_id,
            "sourceStart": self.source_start,
            "sourceEnd": self.source_end,
            "text": self.text,
            "emit": self.emit,
        }


def create_source_units(
    body: str,
    *,
    source_start: int,
    source_end: int,
    emit_start: int,
    max_unit_characters: int = MAX_SOURCE_UNIT_CHARACTERS,
) -> tuple[SourceUnit, ...]:
    if source_end - source_start != len(body):
        raise ValueError("原文单元窗口范围与正文长度不一致")
    if not source_start <= emit_start < source_end:
        raise ValueError("原文单元输出起点无效")
    if max_unit_characters <= 0:
        raise ValueError("原文单元大小必须大于零")

    local_emit = emit_start - source_start
    boundaries = {0, len(body), local_emit}
    for index, character in enumerate(body, start=1):
        if character in "\r\n。！？!?；;":
            boundaries.add(index)
    ordered = sorted(boundaries)
    atomic_spans: list[tuple[int, int]] = []
    for left, right in zip(ordered, ordered[1:], strict=False):
        cursor = left
        while cursor < right:
            end = min(cursor + max_unit_characters, right)
            atomic_spans.append((cursor, end))
            cursor = end

    grouped: list[tuple[int, int]] = []
    for left, right in atomic_spans:
        if (
            grouped
            and grouped[-1][1] == left
            and right - grouped[-1][0] <= max_unit_characters
            and left != local_emit
        ):
            grouped[-1] = (grouped[-1][0], right)
        else:
            grouped.append((left, right))

    return tuple(
        SourceUnit(
            unit_id=f"unit:{source_start + left}:{source_start + right}",
            source_start=source_start + left,
            source_end=source_start + right,
            text=body[left:right],
            emit=source_start + left >= emit_start,
        )
        for left, right in grouped
        if right > left
    )


def materialize_cleanup_output(
    *,
    source_units: tuple[SourceUnit, ...],
    model_output: CleanupOutput,
    terminology_hints: tuple[str, ...] = (),
) -> MaterializedCleanupOutput:
    """Turn compact model text into offsets and auditable corrections.

    Absolute locations and original text always come from the immutable source
    units. The model can suggest corrected text, but it never owns offsets.
    """

    expected_units = tuple(unit for unit in source_units if unit.emit)
    output_by_id = _resolve_cleanup_units(
        expected_units=expected_units,
        model_output=model_output,
    )
    segments: list[CleanupSegment] = []
    corrections: list[CleanupCorrection] = []
    normalized_hints = {hint.strip().casefold() for hint in terminology_hints if hint}

    ordinal = 0
    for source_unit in expected_units:
        model_unit = output_by_id[source_unit.unit_id]
        turns = list(model_unit.turns)
        if len(turns) > 1 and all(turn.source_text is None for turn in turns):
            turns = [
                _collapse_unverifiable_turns(
                    turns,
                    immutable_source=source_unit.text,
                )
            ]
        if len(turns) == 1:
            # A single turn always owns the complete immutable Source Unit.
            # Provider-returned sourceText is only evidence, never authority.
            turn_source_texts: list[str | None] = [source_unit.text]
        else:
            turn_source_texts = _resolve_turn_source_texts(
                source_text=source_unit.text,
                turns=turns,
            )
            if any(text is None for text in turn_source_texts) or "".join(
                text for text in turn_source_texts if text is not None
            ) != source_unit.text:
                turns = [
                    _collapse_unverifiable_turns(
                        turns,
                        immutable_source=source_unit.text,
                    )
                ]
                turn_source_texts = [source_unit.text]

        turn_start = source_unit.source_start
        for turn, turn_source_text in zip(
            turns,
            turn_source_texts,
            strict=True,
        ):
            assert turn_source_text is not None
            ordinal += 1
            turn_end = turn_start + len(turn_source_text)
            turn_source = SourceUnit(
                unit_id=source_unit.unit_id,
                source_start=turn_start,
                source_end=turn_end,
                text=turn_source_text,
                emit=True,
            )
            corrected_text, turn_corrections = _materialize_cleanup_turn(
                source_turn=turn_source,
                corrected_text=turn.corrected_text,
                confidence=turn.confidence,
                segment_ordinal=ordinal,
                normalized_hints=normalized_hints,
            )
            segments.append(
                CleanupSegment(
                    ordinal=ordinal,
                    speaker_role=turn.speaker_role,
                    raw_speaker_label=turn.raw_speaker_label,
                    display_name=_cleanup_display_name(
                        turn.speaker_role,
                        turn.raw_speaker_label,
                        turn.display_name,
                    ),
                    text=corrected_text,
                    source_start=turn_start,
                    source_end=turn_end,
                    confidence=turn.confidence,
                    uncertainty_reason=turn.uncertainty_reason,
                )
            )
            corrections.extend(turn_corrections)
            turn_start = turn_end

    materialized = MaterializedCleanupOutput(
        segments=segments,
        corrections=corrections,
    )
    first_source_start = expected_units[0].source_start if expected_units else 0
    last_source_end = expected_units[-1].source_end if expected_units else 0
    if expected_units:
        materialized.validate_window(
            source_start=first_source_start,
            source_end=last_source_end,
            emit_start=first_source_start,
            source_body="".join(unit.text for unit in expected_units),
        )
    return materialized


def _resolve_cleanup_units(
    *,
    expected_units: tuple[SourceUnit, ...],
    model_output: CleanupOutput,
) -> dict[str, CleanupUnitOutput]:
    """Map provider units without allowing one malformed unit to fail a window.

    Model output may omit an item, return an unknown id, or omit all ids. Exact
    program-owned Source Units remain authoritative. Any unit that cannot be
    mapped deterministically falls back to its original text for user review.
    """

    expected_by_id = {unit.unit_id: unit for unit in expected_units}
    model_units = list(model_output.units)
    resolved: dict[str, CleanupUnitOutput] = {}

    if len(model_units) == len(expected_units) and all(
        unit.unit_id is None for unit in model_units
    ):
        resolved.update(
            {
                source_unit.unit_id: model_unit
                for source_unit, model_unit in zip(
                    expected_units,
                    model_units,
                    strict=True,
                )
            }
        )
    else:
        duplicate_ids: set[str] = set()
        for model_unit in model_units:
            unit_id = model_unit.unit_id
            if unit_id not in expected_by_id:
                continue
            if unit_id in resolved:
                duplicate_ids.add(unit_id)
                resolved.pop(unit_id, None)
                continue
            if unit_id not in duplicate_ids:
                resolved[unit_id] = model_unit

    for source_unit in expected_units:
        resolved.setdefault(
            source_unit.unit_id,
            _fallback_cleanup_unit(source_unit),
        )
    return resolved


def _fallback_cleanup_unit(source_unit: SourceUnit) -> CleanupUnitOutput:
    return CleanupUnitOutput(
        unit_id=source_unit.unit_id,
        turns=[
            CleanupTurnOutput(
                source_text=None,
                speaker_role="unknown",
                raw_speaker_label=None,
                display_name=None,
                corrected_text=source_unit.text,
                confidence=0,
                uncertainty_reason=(
                    "模型未返回可验证的原文单元，已保留原文并标记为待确认"
                ),
            )
        ],
    )


def _resolve_turn_source_texts(*, source_text: str, turns) -> list[str | None]:
    """Recover exact source slices from unambiguous provider turn anchors.

    Providers sometimes omit the first ``sourceText`` or normalize punctuation
    inside later evidence. The provider may identify turn starts, but the program
    always rebuilds the actual evidence from the immutable source unit.
    """

    if len(turns) == 1 and turns[0].source_text is None:
        return [source_text]

    values = [turn.source_text for turn in turns]
    if all(value is not None for value in values) and "".join(
        value for value in values if value is not None
    ) == source_text:
        return values
    if not values or any(value is None for value in values[1:]):
        return values

    source_content, source_offsets = _content_with_source_offsets(source_text)
    turn_starts = [0]
    normalized_cursor = 0
    for value in values[1:]:
        assert value is not None
        anchor = _content_only(value)
        normalized_start = _find_unique_content_anchor(
            source_content=source_content,
            anchor=anchor,
            search_start=normalized_cursor,
        )
        if normalized_start is None:
            return values
        source_start = source_offsets[normalized_start]
        if source_start <= turn_starts[-1]:
            return values
        turn_starts.append(source_start)
        normalized_cursor = normalized_start + 1

    turn_ends = [*turn_starts[1:], len(source_text)]
    recovered = [
        source_text[start:end]
        for start, end in zip(turn_starts, turn_ends, strict=True)
    ]
    for index, (provided, exact_source) in enumerate(
        zip(values, recovered, strict=True)
    ):
        if provided is None or index > 0:
            continue
        # The first turn starts at offset zero rather than at a searched anchor,
        # so a supplied first sourceText must still describe the whole first
        # source slice. Later sourceText values are boundary anchors only; the
        # guarded correctedText diff decides whether their prose is adoptable.
        similarity = SequenceMatcher(
            None,
            _content_only(provided),
            _content_only(exact_source),
            autojunk=False,
        ).ratio()
        if similarity < 0.9:
            return values
    return recovered


def _content_with_source_offsets(value: str) -> tuple[str, list[int]]:
    content: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(value):
        if character in _FORMATTING_CHARACTERS:
            continue
        folded = character.casefold()
        content.extend(folded)
        offsets.extend([index] * len(folded))
    return "".join(content), offsets


def _find_unique_content_anchor(
    *,
    source_content: str,
    anchor: str,
    search_start: int,
) -> int | None:
    if len(anchor) < 4:
        return None
    for length in range(min(48, len(anchor)), 3, -1):
        prefix = anchor[:length]
        matches: list[int] = []
        cursor = source_content.find(prefix, search_start)
        while cursor >= 0:
            matches.append(cursor)
            cursor = source_content.find(prefix, cursor + 1)
        if len(matches) == 1:
            return matches[0]
    return None


def _collapse_unverifiable_turns(turns, *, immutable_source: str):
    """Preserve one auditable source range when the model omits split evidence."""

    roles = {turn.speaker_role for turn in turns}
    role = next(iter(roles)) if len(roles) == 1 else "unknown"
    raw_labels = {
        turn.raw_speaker_label.strip()
        for turn in turns
        if turn.raw_speaker_label and turn.raw_speaker_label.strip()
    }
    raw_label = next(iter(raw_labels)) if len(raw_labels) == 1 else None
    reasons = [
        turn.uncertainty_reason.strip()
        for turn in turns
        if turn.uncertainty_reason and turn.uncertainty_reason.strip()
    ]
    reasons.append("模型未返回可验证的说话人切分边界，已合并为单段待确认")
    corrected_text = "".join(turn.corrected_text for turn in turns)
    if len(corrected_text) > 2_000:
        corrected_text = immutable_source
    return CleanupTurnOutput(
        source_text=None,
        speaker_role=role,
        raw_speaker_label=raw_label,
        display_name=None,
        corrected_text="".join(turn.corrected_text for turn in turns),
        confidence=min(turn.confidence for turn in turns),
        uncertainty_reason="；".join(dict.fromkeys(reasons))[:500],
    )


def _cleanup_display_name(
    speaker_role: str,
    raw_speaker_label: str | None,
    model_display_name: str | None,
) -> str:
    if model_display_name and model_display_name.strip():
        return model_display_name.strip()
    if speaker_role == "candidate":
        return "我"
    if speaker_role == "interviewer":
        return "面试官"
    if raw_speaker_label and raw_speaker_label.strip():
        return raw_speaker_label.strip()
    return "待确认"


def _materialize_cleanup_turn(
    *,
    source_turn: SourceUnit,
    corrected_text: str,
    confidence: float,
    segment_ordinal: int,
    normalized_hints: set[str],
) -> tuple[str, list[CleanupCorrection]]:
    corrected_parts: list[str] = []
    corrections: list[CleanupCorrection] = []
    matcher = SequenceMatcher(
        None,
        source_turn.text,
        corrected_text,
        autojunk=False,
    )
    opcodes = matcher.get_opcodes()
    if _is_unreliable_rewrite(
        source_text=source_turn.text,
        corrected_text=corrected_text,
        opcodes=opcodes,
        similarity=matcher.ratio(),
    ):
        return corrected_text, [
            CleanupCorrection(
                segment_ordinal=segment_ordinal,
                source_start=source_turn.source_start,
                source_end=source_turn.source_end,
                original_text=source_turn.text,
                suggested_text=corrected_text,
                change_type="semantic",
                risk_level="high",
                reason="模型对整段做了较大改写，需要确认是否改变原意",
                confidence=confidence,
            )
        ]
    for tag, source_left, source_right, corrected_left, corrected_right in opcodes:
        original = source_turn.text[source_left:source_right]
        suggestion = corrected_text[corrected_left:corrected_right]
        if tag == "equal":
            corrected_parts.append(original)
            continue
        absolute_start = source_turn.source_start + source_left
        absolute_end = source_turn.source_start + source_right
        classification = _classify_cleanup_change(
            original=original,
            suggestion=suggestion,
            normalized_hints=normalized_hints,
            source_text=source_turn.text,
            corrected_text=corrected_text,
            source_left=source_left,
            source_right=source_right,
            corrected_left=corrected_left,
            corrected_right=corrected_right,
        )
        if classification is None:
            corrected_parts.append(original)
            continue
        change_type, risk_level, reason = classification
        applied_suggestion = suggestion
        if source_left == source_right:
            absolute_start, absolute_end, original, suggestion = _anchor_insertion(
                source_turn,
                local_offset=source_left,
                suggestion=suggestion,
            )
        corrections.append(
            CleanupCorrection(
                segment_ordinal=segment_ordinal,
                source_start=absolute_start,
                source_end=absolute_end,
                original_text=original,
                suggested_text=suggestion,
                change_type=change_type,
                risk_level=risk_level,
                reason=reason,
                confidence=confidence,
            )
        )
        # Review-pending segments deliberately show the provider's corrected
        # text. High-risk edits remain blocking corrections until the user
        # accepts them, restores the immutable source, or enters manual text.
        corrected_parts.append(applied_suggestion)
    return "".join(corrected_parts) or source_turn.text, corrections


def _anchor_insertion(
    source_unit: SourceUnit,
    *,
    local_offset: int,
    suggestion: str,
) -> tuple[int, int, str, str]:
    if local_offset < len(source_unit.text):
        original = source_unit.text[local_offset : local_offset + 1]
        return (
            source_unit.source_start + local_offset,
            source_unit.source_start + local_offset + 1,
            original,
            suggestion + original,
        )
    original = source_unit.text[-1:]
    return (
        source_unit.source_end - 1,
        source_unit.source_end,
        original,
        original + suggestion,
    )


_FORMATTING_CHARACTERS = set(" \t\r\n，。！？；：、,.!?;:()（）[]【】\"'“”‘’")
_SEMANTIC_RISK_PATTERN = re.compile(
    r"(?:\d|不|没|未|无|否|不能|不会|从不|永远|之前|之后|年|月|日|%|％)"
)
_PROTECTED_CLAIM_PATTERN = re.compile(
    r"(?:参与|负责|主导|设计|独立|协助|支持|了解|熟悉|掌握|精通|管理|带领|核心)"
)
_FILLER_SEQUENCE_PATTERN = re.compile(
    r"^(?:(?:嗯|呃|额|啊|哦|那个|就是说|然后的话|然后呢|怎么说呢))+$"
)
_SAFE_SINGLE_CHARACTER_REPETITIONS = frozenset(
    {"我", "你", "他", "她", "它", "这", "那", "是", "的", "就", "还", "也", "有"}
)


def _classify_cleanup_change(
    *,
    original: str,
    suggestion: str,
    normalized_hints: set[str],
    source_text: str,
    corrected_text: str,
    source_left: int,
    source_right: int,
    corrected_left: int,
    corrected_right: int,
) -> tuple[str, str, str] | None:
    changed_characters = set(original + suggestion)
    if changed_characters <= _FORMATTING_CHARACTERS:
        return "formatting", "low", "仅调整空白或标点格式"
    if _is_safe_filler_removal(original=original, suggestion=suggestion):
        return "formatting", "low", "删除不承载语义的口头衔接词"
    if _is_safe_adjacent_repetition_removal(
        source_text=source_text,
        source_left=source_left,
        source_right=source_right,
        original=original,
        suggestion=suggestion,
    ):
        return "recognition", "low", "合并语音转写产生的紧邻重复词"
    if _SEMANTIC_RISK_PATTERN.search(original + suggestion) or _PROTECTED_CLAIM_PATTERN.search(
        original + suggestion
    ):
        return "semantic", "high", "涉及数字、否定、时间、职责或其他可能改变原意的信息"
    if _is_small_local_change(
        original=original,
        suggestion=suggestion,
    ) and _change_overlaps_terminology_hint(
        corrected_text=corrected_text,
        corrected_left=corrected_left,
        corrected_right=corrected_right,
        normalized_hints=normalized_hints,
    ):
        return "recognition", "low", "修正结果与当前求职目标中的术语提示一致"
    return "recognition", "low", "采用模型在有界转写清洗中的错字、口头语或断句修正"


def _content_only(value: str) -> str:
    return "".join(
        character.casefold()
        for character in value
        if character not in _FORMATTING_CHARACTERS
    )


def _is_safe_filler_removal(*, original: str, suggestion: str) -> bool:
    if _content_only(suggestion):
        return False
    content = _content_only(original)
    return bool(content and _FILLER_SEQUENCE_PATTERN.fullmatch(content))


def _is_safe_adjacent_repetition_removal(
    *,
    source_text: str,
    source_left: int,
    source_right: int,
    original: str,
    suggestion: str,
) -> bool:
    if suggestion or not original or any(
        character in _FORMATTING_CHARACTERS for character in original
    ):
        return False
    if len(original) == 1 and original not in _SAFE_SINGLE_CHARACTER_REPETITIONS:
        return False
    repeated_before = source_text[max(0, source_left - len(original)) : source_left]
    repeated_after = source_text[source_right : source_right + len(original)]
    return repeated_before == original or repeated_after == original


def _change_overlaps_terminology_hint(
    *,
    corrected_text: str,
    corrected_left: int,
    corrected_right: int,
    normalized_hints: set[str],
) -> bool:
    normalized_text = corrected_text.casefold()
    for hint in normalized_hints:
        start = normalized_text.find(hint)
        while start >= 0:
            end = start + len(hint)
            if corrected_left < end and corrected_right > start:
                return True
            start = normalized_text.find(hint, start + 1)
    return False


def _is_small_local_change(*, original: str, suggestion: str) -> bool:
    original_content = _content_only(original)
    suggestion_content = _content_only(suggestion)
    if not original_content and not suggestion_content:
        return False
    return (
        max(len(original_content), len(suggestion_content)) <= 8
        and len(original_content) + len(suggestion_content) <= 12
    )


def _is_unreliable_rewrite(
    *,
    source_text: str,
    corrected_text: str,
    opcodes: list[tuple[str, int, int, int, int]],
    similarity: float,
) -> bool:
    if not source_text:
        return bool(corrected_text)
    length_ratio = len(corrected_text) / len(source_text)
    if similarity < 0.45:
        return True
    if len(source_text) >= 32 and not 0.45 <= length_ratio <= 1.35:
        return True
    has_content_deletion = any(
        tag == "delete" and _content_only(source_text[source_left:source_right])
        for tag, source_left, source_right, _, _ in opcodes
    )
    has_content_insertion = any(
        tag == "insert" and _content_only(corrected_text[corrected_left:corrected_right])
        for tag, _, _, corrected_left, corrected_right in opcodes
    )
    return has_content_deletion and has_content_insertion and similarity < 0.65


def create_source_windows(
    body: str,
    *,
    window_size: int = MAX_WINDOW_CHARACTERS,
    overlap: int = WINDOW_OVERLAP_CHARACTERS,
) -> tuple[SourceWindow, ...]:
    if not body:
        return ()
    if window_size <= 0 or overlap < 0 or overlap >= window_size:
        raise ValueError("窗口大小或重叠范围无效")
    windows: list[SourceWindow] = []
    start = 0
    while start < len(body):
        hard_end = min(start + window_size, len(body))
        end = (
            hard_end
            if hard_end == len(body)
            else _natural_window_end(
                body,
                source_start=start,
                hard_end=hard_end,
                window_size=window_size,
            )
        )
        windows.append(
            SourceWindow(
                ordinal=len(windows) + 1,
                source_start=start,
                source_end=end,
                body=body[start:end],
            )
        )
        if end == len(body):
            break
        start = max(end - overlap, start + 1)
    return tuple(windows)


def split_source_window(
    body: str,
    *,
    source_start: int,
    source_end: int,
) -> tuple[SourceWindow, ...]:
    if source_start < 0 or source_end > len(body) or source_end <= source_start:
        raise ValueError("待拆分文字窗口无效")
    length = source_end - source_start
    if length <= ADAPTIVE_SPLIT_MIN_CHARACTERS:
        return ()
    local_body = body[source_start:source_end]
    child_size = (length + WINDOW_OVERLAP_CHARACTERS + 1) // 2
    children = create_source_windows(
        local_body,
        window_size=child_size,
        overlap=WINDOW_OVERLAP_CHARACTERS,
    )
    return tuple(
        SourceWindow(
            ordinal=ordinal,
            source_start=source_start + child.source_start,
            source_end=source_start + child.source_end,
            body=child.body,
        )
        for ordinal, child in enumerate(children, start=1)
    )


def speaker_hints_from_outputs(
    window_outputs: Iterable[Iterable[Mapping[str, object]]],
) -> tuple[dict[str, str], ...]:
    hints: list[dict[str, str]] = []
    seen: set[str] = set()
    for window in window_outputs:
        for item in window:
            raw_label = item.get("rawSpeakerLabel") or item.get("raw_speaker_label")
            role = item.get("speakerRole") or item.get("speaker_role")
            display_name = item.get("displayName") or item.get("display_name")
            if (
                not isinstance(raw_label, str)
                or not raw_label.strip()
                or role not in {"candidate", "interviewer"}
                or not isinstance(display_name, str)
                or not display_name.strip()
            ):
                continue
            normalized = raw_label.strip().casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            hints.append(
                {
                    "rawSpeakerLabel": raw_label.strip(),
                    "speakerRole": str(role),
                    "displayName": display_name.strip(),
                }
            )
            if len(hints) == MAX_SPEAKER_HINTS:
                return tuple(hints)
    return tuple(hints)


def _natural_window_end(
    body: str,
    *,
    source_start: int,
    hard_end: int,
    window_size: int,
) -> int:
    minimum_end = min(hard_end, source_start + max(1, int(window_size * 0.65)))
    for index in range(hard_end - 1, minimum_end - 1, -1):
        if body[index] in "\r\n。！？!?；;":
            return index + 1
    return hard_end


def reduce_cleanup_segments(
    window_outputs: Iterable[Iterable[Mapping[str, object]]],
) -> tuple[dict[str, object], ...]:
    collected: list[dict[str, object]] = []
    seen: set[tuple[int, int, str]] = set()
    for window in window_outputs:
        previous_end = -1
        for raw in window:
            item = dict(raw)
            start = int(_value(item, "sourceStart", "source_start"))
            end = int(_value(item, "sourceEnd", "source_end"))
            if start < previous_end or end <= start:
                raise ValueError("window segment offset regression")
            previous_end = end
            text = str(_value(item, "text", "body")).strip()
            fingerprint = (start, end, _normalize_text(text))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            item["sourceStart"] = start
            item["sourceEnd"] = end
            item["text"] = text
            collected.append(item)
    collected.sort(key=lambda item: (int(item["sourceStart"]), int(item["sourceEnd"])))
    for ordinal, item in enumerate(collected, start=1):
        item["ordinal"] = ordinal
    return tuple(collected)


def reduce_cleanup_result(
    window_outputs: Iterable[Mapping[str, object]],
) -> dict[str, tuple[dict[str, object], ...]]:
    outputs = [dict(item) for item in window_outputs]
    segments = reduce_cleanup_segments(
        item.get("segments", []) for item in outputs  # type: ignore[arg-type]
    )
    corrections_by_range: dict[tuple[int, int, str], dict[str, object]] = {}
    conflicting_ranges: set[tuple[int, int, str]] = set()
    for output in outputs:
        for raw in output.get("corrections", []):  # type: ignore[union-attr]
            correction = dict(raw)
            start = int(_value(correction, "sourceStart", "source_start"))
            end = int(_value(correction, "sourceEnd", "source_end"))
            original = str(_value(correction, "originalText", "original_text"))
            key = (start, end, original)
            correction["sourceStart"] = start
            correction["sourceEnd"] = end
            correction["originalText"] = original
            existing = corrections_by_range.get(key)
            if existing is None:
                corrections_by_range[key] = correction
                continue
            if existing.get("suggestedText") != correction.get("suggestedText"):
                conflicting_ranges.add(key)

    corrections: list[dict[str, object]] = []
    for key, correction in corrections_by_range.items():
        start, end, _original = key
        segment = next(
            (
                item
                for item in segments
                if int(item["sourceStart"]) <= start
                and int(item["sourceEnd"]) >= end
            ),
            None,
        )
        if segment is None:
            raise ValueError("修订原文没有对应的整理片段")
        correction["segmentOrdinal"] = int(segment["ordinal"])
        if key in conflicting_ranges:
            correction["suggestedText"] = None
            correction["riskLevel"] = "high"
            correction["changeType"] = "semantic"
            correction["reason"] = "重叠窗口对同一原文给出冲突修订，请人工确认"
            correction["confidence"] = min(float(correction.get("confidence", 0)), 0.5)
        corrections.append(correction)
    corrections.sort(
        key=lambda item: (int(item["sourceStart"]), int(item["sourceEnd"]))
    )
    previous_end = -1
    for correction in corrections:
        if int(correction["sourceStart"]) < previous_end:
            raise ValueError("归并后的修订范围不能重叠")
        previous_end = int(correction["sourceEnd"])
    return {"segments": segments, "corrections": tuple(corrections)}


def _value(item: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in item:
            return item[name]
    raise ValueError(f"missing cleanup segment field: {names[0]}")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
