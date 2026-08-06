"""Coverage-first planning for deterministic and model question discovery."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import re

from app.agents.question_curation_contracts import (
    MAX_QUESTION_SEED_SOURCE_REFS,
    QuestionSeed,
)
from app.review.curation_sections import (
    MAX_DISCOVERY_CHARACTERS,
    MAX_DISCOVERY_SECTIONS,
    DiscoveryUnit,
    SourceSection,
)


_QUESTION_CUES = re.compile(
    r"(?:什么|如何|为什么|区别|原理|机制|怎么|哪些|是否|能否|介绍|说说|谈谈|分析)"
)
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?P<text>.+?)\s*$")
_BOLD_HEADING = re.compile(r"^\s*(?:\*\*|__)(?P<text>.+?)(?:\*\*|__)\s*$")
_NUMBERED_PREFIX = re.compile(
    r"^\s*\d{1,3}(?:(?:\.(?!\d))|[、]|\))\s*(?P<text>\S.*)$"
)
_INTERROGATIVE_START = re.compile(
    r"^(?:什么|如何|为什么|怎么|哪些|是否|能否|介绍|说说|谈谈|分析)"
)
_QUESTION_TOPIC_END = re.compile(r"(?:区别|原理|机制)\s*[：:]?$")
_DECLARATIVE_NUMBERED_PROSE = re.compile(
    r"(?:取决于|通过.+实现|包括|是指|用于|表示|由.+组成)"
)
_NUMBERED_TOPIC_HINT = re.compile(
    r"(?:区别|特性|底层|实现|过程|原理|机制|容量|条件|用途|参数|策略|流程)"
)
_COLON_TOPIC = re.compile(
    r"^(?P<topic>[^：:\n]{1,40})[：:](?P<details>\S.+)$"
)
_ANSWER_LIST_INTRO = re.compile(
    r"(?:(?:参考)?答案\s*[：:]|"
    r"(?:答案|要点|原因|步骤|类型|特点|优势|劣势|场景|条件|组成)"
    r".{0,8}(?:如下|包括|有|分为)\s*[：:]?)\s*$"
)


class CurationPlanningError(ValueError):
    code = "curation_discovery_plan_invalid"


@dataclass(frozen=True, slots=True)
class DeterministicSeedUnit:
    unit_index: int
    seeds: tuple[QuestionSeed, ...]
    source_refs: tuple[str, ...]
    input_digest: str


@dataclass(frozen=True, slots=True)
class CurationDiscoveryPlan:
    deterministic_units: tuple[DeterministicSeedUnit, ...]
    model_units: tuple[DiscoveryUnit, ...]
    covered_source_refs: tuple[str, ...]


def plan_curation_discovery(
    sections: tuple[SourceSection, ...],
) -> CurationDiscoveryPlan:
    """Assign every atomic section to exactly one deterministic range or model window."""
    _validate_atomic_sections(sections)
    deterministic_units: list[DeterministicSeedUnit] = []
    model_units: list[DiscoveryUnit] = []
    next_unit_index = 0

    cursor = 0
    while cursor < len(sections):
        source_id = sections[cursor].source_id
        end = cursor + 1
        while end < len(sections) and sections[end].source_id == source_id:
            end += 1
        source_sections = sections[cursor:end]
        anchor_indexes = _question_anchor_indexes(source_sections)
        first_anchor = anchor_indexes[0] if anchor_indexes else len(source_sections)
        for packed in pack_model_sections(source_sections[:first_anchor]):
            model_units.append(DiscoveryUnit(
                unit_index=next_unit_index,
                sections=packed,
                input_digest=_sections_digest(packed),
            ))
            next_unit_index += 1
        for anchor_position, start in enumerate(anchor_indexes):
            stop = (
                anchor_indexes[anchor_position + 1]
                if anchor_position + 1 < len(anchor_indexes)
                else len(source_sections)
            )
            full_question_range = source_sections[start:stop]
            question_range = full_question_range[:MAX_QUESTION_SEED_SOURCE_REFS]
            source_refs = tuple(section.ref for section in question_range)
            seed = QuestionSeed(
                question_text=_question_text(question_range[0]),
                source_ref=source_refs[0],
                source_refs=list(source_refs),
            )
            deterministic_units.append(DeterministicSeedUnit(
                unit_index=next_unit_index,
                seeds=(seed,),
                source_refs=source_refs,
                input_digest=_sections_digest(question_range),
            ))
            next_unit_index += 1
            for packed in pack_model_sections(
                full_question_range[MAX_QUESTION_SEED_SOURCE_REFS:]
            ):
                model_units.append(DiscoveryUnit(
                    unit_index=next_unit_index,
                    sections=packed,
                    input_digest=_sections_digest(packed),
                ))
                next_unit_index += 1
        cursor = end

    plan = CurationDiscoveryPlan(
        deterministic_units=tuple(deterministic_units),
        model_units=tuple(model_units),
        covered_source_refs=tuple(section.ref for section in sections),
    )
    _validate_coverage(sections, plan)
    return plan


def plan_curation_audit(
    sections: tuple[SourceSection, ...],
    discovered_seeds: tuple[QuestionSeed, ...],
) -> tuple[DiscoveryUnit, ...]:
    """Plan an independent full-source pass whose identity includes prior findings."""
    _validate_atomic_sections(sections)
    units: list[DiscoveryUnit] = []
    cursor = 0
    while cursor < len(sections):
        source_id = sections[cursor].source_id
        end = cursor + 1
        while end < len(sections) and sections[end].source_id == source_id:
            end += 1
        source_seeds = tuple(
            seed
            for seed in discovered_seeds
            if seed.source_ref.split("#", 1)[0] == source_id
        )
        seed_index = "\n".join(
            f"{seed.source_ref}\t{seed.question_text.strip()}"
            for seed in source_seeds
        )
        for packed in pack_model_sections(sections[cursor:end]):
            digest_input = f"{_sections_digest(packed)}\n{seed_index}"
            units.append(DiscoveryUnit(
                unit_index=len(units),
                sections=packed,
                input_digest=sha256(digest_input.encode("utf-8")).hexdigest(),
            ))
        cursor = end
    assigned = [section.ref for unit in units for section in unit.sections]
    expected = [section.ref for section in sections]
    if assigned != expected or any(
        len({section.source_id for section in unit.sections}) != 1
        for unit in units
    ):
        raise CurationPlanningError("invalid audit coverage")
    return tuple(units)


def _question_anchor_indexes(
    sections: tuple[SourceSection, ...],
) -> list[int]:
    indexes: list[int] = []
    inside_answer_list = False
    for index, section in enumerate(sections):
        first_line = section.text.splitlines()[0].strip()
        if _NUMBERED_PREFIX.match(first_line):
            has_question_mark = _question_text(section).endswith(("?", "？"))
            if _numbered_question(first_line, _QUESTION_CUES) and (
                not inside_answer_list or has_question_mark
            ):
                indexes.append(index)
                inside_answer_list = _has_answer_list_intro(section)
            continue
        if _is_non_numbered_question_anchor(section):
            indexes.append(index)
            inside_answer_list = _has_answer_list_intro(section)
            continue
        if _MARKDOWN_HEADING.match(first_line) or _BOLD_HEADING.match(first_line):
            inside_answer_list = False
            continue
        if _has_answer_list_intro(section):
            inside_answer_list = True
    return indexes


def _is_non_numbered_question_anchor(section: SourceSection) -> bool:
    first_line = section.text.splitlines()[0].strip()
    return (
        _question_text(section).endswith(("?", "？"))
        or _question_heading(first_line, _QUESTION_CUES)
        or _colon_topic_question(first_line)
    )


def _question_heading(first_line: str, cues: re.Pattern[str]) -> bool:
    match = _MARKDOWN_HEADING.match(first_line) or _BOLD_HEADING.match(first_line)
    if match is None:
        return False
    text = match.group("text").strip()
    return text.endswith(("?", "？")) or cues.search(text) is not None


def _numbered_question(first_line: str, cues: re.Pattern[str]) -> bool:
    match = _NUMBERED_PREFIX.match(first_line)
    if match is None:
        return False
    text = match.group("text").strip()
    if text.endswith(("?", "？")):
        return True
    if _DECLARATIVE_NUMBERED_PROSE.search(text):
        return False
    if (
        _INTERROGATIVE_START.match(text) is not None
        or _QUESTION_TOPIC_END.search(text) is not None
    ):
        return True
    return (
        len(text) <= 160
        and _NUMBERED_TOPIC_HINT.search(text) is not None
        and (cues.search(text) is not None or "，" in text or "," in text)
    )


def _colon_topic_question(first_line: str) -> bool:
    match = _COLON_TOPIC.match(first_line)
    if match is None:
        return False
    details = match.group("details").strip()
    return (
        len(first_line) <= 220
        and _QUESTION_CUES.search(details) is not None
        and _DECLARATIVE_NUMBERED_PROSE.search(details) is None
    )


def _has_answer_list_intro(section: SourceSection) -> bool:
    return any(
        _ANSWER_LIST_INTRO.search(line.strip())
        for line in section.text.splitlines()
    )


def _question_text(section: SourceSection) -> str:
    text = section.text.splitlines()[0].strip()
    for pattern in (_MARKDOWN_HEADING, _BOLD_HEADING, _NUMBERED_PREFIX):
        match = pattern.match(text)
        if match is not None:
            text = match.group("text").strip()
    return text


def pack_model_sections(
    sections: tuple[SourceSection, ...],
) -> tuple[tuple[SourceSection, ...], ...]:
    """Pack one source into model-safe groups by both density dimensions."""
    packed: list[tuple[SourceSection, ...]] = []
    current: list[SourceSection] = []
    characters = 0
    for section in sections:
        if current and (
            len(current) == MAX_DISCOVERY_SECTIONS
            or characters + len(section.text) > MAX_DISCOVERY_CHARACTERS
        ):
            packed.append(tuple(current))
            current = []
            characters = 0
        current.append(section)
        characters += len(section.text)
    if current:
        packed.append(tuple(current))
    return tuple(packed)


def _sections_digest(sections: tuple[SourceSection, ...]) -> str:
    digest_input = "\n".join(
        f"{section.ref}\t{section.digest}" for section in sections
    )
    return sha256(digest_input.encode("utf-8")).hexdigest()


def _validate_atomic_sections(sections: tuple[SourceSection, ...]) -> None:
    refs = [section.ref for section in sections]
    if len(refs) != len(set(refs)):
        raise CurationPlanningError("invalid source coverage: duplicate atomic ref")
    if any(
        section.ref.split("#", 1)[0] != section.source_id
        for section in sections
    ):
        raise CurationPlanningError("invalid source coverage: incompatible source ref")


def _validate_coverage(
    sections: tuple[SourceSection, ...], plan: CurationDiscoveryPlan
) -> None:
    expected = tuple(section.ref for section in sections)
    assigned = [
        ref
        for unit in plan.deterministic_units
        for ref in unit.source_refs
    ]
    assigned.extend(
        section.ref
        for unit in plan.model_units
        for section in unit.sections
    )
    counts = Counter(assigned)
    if any(counts[ref] != 1 for ref in expected):
        raise CurationPlanningError("invalid source coverage: missing or repeated ref")
    if set(counts) != set(expected) or any(count != 1 for count in counts.values()):
        raise CurationPlanningError("invalid source coverage: incompatible ranges")
    if any(
        len({ref.split("#", 1)[0] for ref in unit.source_refs}) != 1
        for unit in plan.deterministic_units
    ) or any(
        len({section.source_id for section in unit.sections}) != 1
        for unit in plan.model_units
    ):
        raise CurationPlanningError("invalid source coverage: cross-source range")
