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
    DiscoveryUnit,
    SourceSection,
)


_QUESTION_CUES = re.compile(
    r"(?:什么|如何|为什么|区别|原理|机制|怎么|哪些|是否|能否|介绍|说说|谈谈|分析)"
)
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(?P<text>.+?)\s*$")
_BOLD_HEADING = re.compile(r"^\s*(?:\*\*|__)(?P<text>.+?)(?:\*\*|__)\s*$")
_NUMBERED_PREFIX = re.compile(r"^\s*\d{1,3}(?:[.、]|\))\s*(?P<text>\S.*)$")


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
    model_sections: list[tuple[SourceSection, ...]] = []

    cursor = 0
    while cursor < len(sections):
        source_id = sections[cursor].source_id
        end = cursor + 1
        while end < len(sections) and sections[end].source_id == source_id:
            end += 1
        source_sections = sections[cursor:end]
        anchor_indexes = [
            index
            for index, section in enumerate(source_sections)
            if _is_question_anchor(section)
        ]
        first_anchor = anchor_indexes[0] if anchor_indexes else len(source_sections)
        model_sections.extend(_pack_model_sections(source_sections[:first_anchor]))
        for anchor_position, start in enumerate(anchor_indexes):
            stop = (
                anchor_indexes[anchor_position + 1]
                if anchor_position + 1 < len(anchor_indexes)
                else len(source_sections)
            )
            full_question_range = source_sections[start:stop]
            question_range = full_question_range[:MAX_QUESTION_SEED_SOURCE_REFS]
            model_sections.extend(
                _pack_model_sections(
                    full_question_range[MAX_QUESTION_SEED_SOURCE_REFS:]
                )
            )
            source_refs = tuple(section.ref for section in question_range)
            seed = QuestionSeed(
                question_text=_question_text(question_range[0]),
                source_ref=source_refs[0],
                source_refs=list(source_refs),
            )
            deterministic_units.append(DeterministicSeedUnit(
                unit_index=len(deterministic_units),
                seeds=(seed,),
                source_refs=source_refs,
                input_digest=_sections_digest(question_range),
            ))
        cursor = end

    model_units = tuple(
        DiscoveryUnit(
            unit_index=index,
            sections=packed,
            input_digest=_sections_digest(packed),
        )
        for index, packed in enumerate(model_sections)
    )
    plan = CurationDiscoveryPlan(
        deterministic_units=tuple(deterministic_units),
        model_units=model_units,
        covered_source_refs=tuple(section.ref for section in sections),
    )
    _validate_coverage(sections, plan)
    return plan


def _is_question_anchor(section: SourceSection) -> bool:
    first_line = section.text.splitlines()[0].strip()
    return (
        _question_text(section).endswith(("?", "？"))
        or _question_heading(first_line, _QUESTION_CUES)
        or _numbered_question(first_line, _QUESTION_CUES)
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
    return text.endswith(("?", "？")) or cues.search(text) is not None


def _question_text(section: SourceSection) -> str:
    text = section.text.splitlines()[0].strip()
    for pattern in (_MARKDOWN_HEADING, _BOLD_HEADING, _NUMBERED_PREFIX):
        match = pattern.match(text)
        if match is not None:
            text = match.group("text").strip()
    return text


def _pack_model_sections(
    sections: tuple[SourceSection, ...],
) -> tuple[tuple[SourceSection, ...], ...]:
    packed: list[tuple[SourceSection, ...]] = []
    current: list[SourceSection] = []
    characters = 0
    for section in sections:
        if current and characters + len(section.text) > MAX_DISCOVERY_CHARACTERS:
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
