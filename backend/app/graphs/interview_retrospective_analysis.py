from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence


def finalize_report(
    *,
    questions: Sequence[Mapping[str, object]],
    analyses: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build the deterministic aggregate without inventing missing results."""
    included_ids = [
        str(question["id"])
        for question in sorted(questions, key=lambda item: int(item["ordinal"]))
        if question.get("decisionStatus") == "confirmed"
    ]
    included = set(included_ids)
    verdicts = Counter(
        str(analysis["verdict"])
        for analysis in analyses
        if str(analysis["questionUnitId"]) in included
    )
    return {
        "includedQuestionIds": included_ids,
        "questionCount": len(included_ids),
        "verdictCounts": dict(verdicts),
    }
