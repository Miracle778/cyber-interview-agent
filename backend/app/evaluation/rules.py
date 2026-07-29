from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.contracts import EvalPack
from app.evaluation.snapshot import FrozenEvaluationSnapshot


@dataclass(frozen=True, slots=True)
class DeterministicRuleResult:
    rule_id: str
    status: str
    cited_event_hashes: tuple[str, ...]
    evidence_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeterministicEvaluationResult:
    status: str
    rules: tuple[DeterministicRuleResult, ...]
    evidence_gaps: tuple[str, ...]


def evaluate_deterministic_rules(
    snapshot: FrozenEvaluationSnapshot,
    pack: EvalPack,
) -> DeterministicEvaluationResult:
    available = {
        event.event_type: event
        for event in snapshot.events
        if event.available
    }
    unavailable = [
        event for event in snapshot.events if not event.available
    ]
    results: list[DeterministicRuleResult] = []
    global_gaps = [
        f"事件正文不可用: {event.event_type}#{event.sequence}"
        for event in unavailable
    ]
    for rule in pack.rules:
        missing = sorted(
            event_type
            for event_type in rule.required_event_types
            if event_type not in available
        )
        hashes = tuple(
            sorted(
                {
                    available[event_type].payload_sha256
                    for event_type in rule.required_event_types
                    if event_type in available
                }
            )
        )
        gaps = tuple(f"缺少事件: {event_type}" for event_type in missing)
        results.append(
            DeterministicRuleResult(
                rule_id=rule.id,
                status="inconclusive" if missing or unavailable else "passed",
                cited_event_hashes=hashes,
                evidence_gaps=gaps,
            )
        )
        global_gaps.extend(gaps)
    status = (
        "inconclusive"
        if global_gaps or not snapshot.events
        else "passed"
    )
    if not snapshot.events:
        global_gaps.append("Trace 中没有可评估事件")
    return DeterministicEvaluationResult(
        status=status,
        rules=tuple(results),
        evidence_gaps=tuple(dict.fromkeys(global_gaps)),
    )
