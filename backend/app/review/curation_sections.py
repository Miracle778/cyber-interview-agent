"""Deterministic, bounded source sections for question discovery."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re


MAX_SECTION_CHARACTERS = 2_000
MAX_DISCOVERY_SECTIONS = 6
MAX_DISCOVERY_CHARACTERS = 6_000

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s|$)")
_BOLD_HEADING = re.compile(r"^\s*(?:\*\*.+\*\*|__.+__)\s*$")
_NUMBERED_PREFIX = re.compile(r"^\s*\d{1,3}(?:[.、]|\))\s*\S")
_QUESTION_LINE = re.compile(r"^.*(?:\?|？)\s*$")
_BLANK_LINE = re.compile(
    r"^\s*(?:[\u200b\u200c\u200d\ufeff]|&nbsp;|<br\s*/?>|<p>&nbsp;</p>)*\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SourceSection:
    source_id: str
    ref: str
    ordinal: int
    text: str
    digest: str


@dataclass(frozen=True, slots=True)
class DiscoveryUnit:
    unit_index: int
    sections: tuple[SourceSection, ...]
    input_digest: str


def section_sources(source_excerpts: tuple[str, ...]) -> tuple[SourceSection, ...]:
    """Return source-local sections with stable references and normalized digests."""
    result: list[SourceSection] = []
    for source_excerpt in source_excerpts:
        source_id, body = _split_source_excerpt(source_excerpt)
        ordinal = 1
        for text in _split_semantic_sections(body):
            for chunk in _split_to_limit(text):
                result.append(
                    SourceSection(
                        source_id=source_id,
                        ref=f"{source_id}#section-{ordinal:04d}",
                        ordinal=ordinal,
                        text=chunk,
                        digest=sha256(chunk.encode("utf-8")).hexdigest(),
                    )
                )
                ordinal += 1
    return tuple(result)


def pack_discovery_units(sections: tuple[SourceSection, ...]) -> tuple[DiscoveryUnit, ...]:
    """Pack sections in order without exceeding discovery call budgets."""
    units: list[DiscoveryUnit] = []
    current: list[SourceSection] = []
    current_characters = 0

    for section in sections:
        if current and (
            len(current) == MAX_DISCOVERY_SECTIONS
            or current_characters + len(section.text) > MAX_DISCOVERY_CHARACTERS
        ):
            units.append(_discovery_unit(len(units), current))
            current = []
            current_characters = 0
        current.append(section)
        current_characters += len(section.text)

    if current:
        units.append(_discovery_unit(len(units), current))
    return tuple(units)


def _split_source_excerpt(source_excerpt: str) -> tuple[str, str]:
    normalized = source_excerpt.replace("\r\n", "\n").replace("\r", "\n")
    header, separator, body = normalized.partition("\n")
    source_id, colon, _ = header.partition(":")
    if not colon:
        return header, body if separator else ""
    return source_id, body


def _split_semantic_sections(body: str) -> tuple[str, ...]:
    sections: list[str] = []
    current: list[str] = []
    for line in body.split("\n"):
        if _BLANK_LINE.fullmatch(line):
            _append_section(sections, current)
            current = []
            continue
        if _is_boundary(line) and current:
            _append_section(sections, current)
            current = []
        current.append(line)
    _append_section(sections, current)
    return tuple(sections)


def _is_boundary(line: str) -> bool:
    return bool(
        _MARKDOWN_HEADING.match(line)
        or _BOLD_HEADING.match(line)
        or _NUMBERED_PREFIX.match(line)
        or _QUESTION_LINE.match(line)
    )


def _append_section(sections: list[str], lines: list[str]) -> None:
    if lines:
        sections.append("\n".join(lines))


def _split_to_limit(text: str) -> tuple[str, ...]:
    if len(text) <= MAX_SECTION_CHARACTERS:
        return (text,)

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) <= MAX_SECTION_CHARACTERS:
            if current and len(current) + len(line) > MAX_SECTION_CHARACTERS:
                chunks.append(current)
                current = ""
            current += line
            continue

        while line:
            capacity = MAX_SECTION_CHARACTERS - len(current)
            current += line[:capacity]
            line = line[capacity:]
            if len(current) == MAX_SECTION_CHARACTERS:
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)
    return tuple(chunks)


def _discovery_unit(unit_index: int, sections: list[SourceSection]) -> DiscoveryUnit:
    packed_sections = tuple(sections)
    digest_input = "\n".join(
        f"{section.ref}\t{section.digest}" for section in packed_sections
    )
    return DiscoveryUnit(
        unit_index=unit_index,
        sections=packed_sections,
        input_digest=sha256(digest_input.encode("utf-8")).hexdigest(),
    )
