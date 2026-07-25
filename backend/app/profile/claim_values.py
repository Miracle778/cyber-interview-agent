from __future__ import annotations

import json
from typing import Any


_EMPTY_VALUES = (None, "", [], {})


def canonical_claim_value(
    category: str, raw_value: dict[str, object]
) -> dict[str, object]:
    value = dict(raw_value)

    def alias(target: str, *sources: str) -> None:
        if target not in value:
            for source in sources:
                candidate = value.get(source)
                if candidate not in _EMPTY_VALUES:
                    value[target] = candidate
                    break
        for source in sources:
            if source != target:
                value.pop(source, None)

    if category == "skill":
        alias("name", "name", "text", "skill")
    elif category == "project":
        alias("name", "name", "title", "project")
        alias("background", "background", "description")
        alias("role", "role", "position")
        alias("tech_stack", "tech_stack", "techStack", "technologies")
        alias("results", "results", "result", "outcomes")
    elif category == "experience":
        alias("organization", "organization", "company", "employer")
        alias("title", "title", "role", "position")
        alias("period", "period", "dates", "duration")
    elif category == "education":
        alias("school", "school", "institution", "university")
        alias("major", "major", "field")
        alias("period", "period", "dates", "duration")
    elif category == "certification":
        alias("name", "name", "title", "certificate")
        alias("issuer", "issuer", "organization")
        alias("issued_at", "issued_at", "issuedAt", "date")
    elif category == "achievement":
        alias("title", "title", "name")
        alias("date", "date", "period")
    elif category == "link":
        alias("label", "label", "name", "title")
        alias("url", "url", "href", "link")
    return value


def comparable_claim_value(
    category: str, raw_value: dict[str, object]
) -> dict[str, object]:
    value = canonical_claim_value(category, raw_value)
    return {
        key: item
        for key, item in value.items()
        if key not in {"category", "confidence"} and item not in _EMPTY_VALUES
    }


def claim_identity(category: str, value: dict[str, object]) -> str | None:
    normalized = comparable_claim_value(category, value)

    def text(key: str) -> str:
        candidate = normalized.get(key)
        return str(candidate).strip().casefold() if candidate else ""

    if category in {"skill", "project"}:
        parts = (text("name"),)
    elif category == "experience":
        parts = (text("organization"), text("title"), text("period"))
    elif category == "education":
        parts = (text("school"), text("degree"), text("major"), text("period"))
    elif category == "certification":
        parts = (text("name"), text("issuer"))
    elif category == "achievement":
        parts = (text("title"), text("date"))
    elif category == "link":
        parts = (text("url"),)
    else:
        return None
    if not parts[0]:
        return None
    return json.dumps(
        [category, *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def merge_claim_values(
    preferred: dict[str, object], fallback: dict[str, object]
) -> dict[str, object]:
    """Fill complementary facts without guessing through scalar conflicts."""
    merged = dict(preferred)
    for key, candidate in fallback.items():
        current = merged.get(key)
        if current in _EMPTY_VALUES:
            merged[key] = candidate
        elif candidate in _EMPTY_VALUES or candidate == current:
            continue
        elif isinstance(current, list) and isinstance(candidate, list):
            merged[key] = list(dict.fromkeys([*current, *candidate]))
    return merged


def proposal_confidence(value: dict[str, Any]) -> float:
    candidate = value.get("confidence", 0)
    if isinstance(candidate, bool):
        return 0.0
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return 0.0
