from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


CoverageStatus = Literal["uncovered", "partial", "covered"]
_STATUS_RANK: dict[CoverageStatus, int] = {
    "uncovered": 0,
    "partial": 1,
    "covered": 2,
}


@dataclass(frozen=True, slots=True)
class KeyPointCoverage:
    point: str
    status: CoverageStatus
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.point.strip():
            raise ValueError("key point must not be empty")
        if self.status not in _STATUS_RANK:
            raise ValueError("unsupported coverage status")
        if any(not item.strip() for item in self.evidence):
            raise ValueError("coverage evidence must not be empty")


def merge_key_point_coverage(
    required_points: Iterable[str],
    previous: Iterable[KeyPointCoverage],
    decision: Iterable[KeyPointCoverage],
) -> tuple[KeyPointCoverage, ...]:
    ordered_points = tuple(dict.fromkeys(point.strip() for point in required_points))
    if not ordered_points or any(not point for point in ordered_points):
        raise ValueError("required key points must not be empty")
    allowed = set(ordered_points)
    previous_by_point = _validated_map(previous, allowed)
    decision_by_point = _validated_map(decision, allowed)
    merged: list[KeyPointCoverage] = []
    for point in ordered_points:
        old = previous_by_point.get(
            point, KeyPointCoverage(point=point, status="uncovered")
        )
        current = decision_by_point.get(point)
        if current is None or _STATUS_RANK[current.status] < _STATUS_RANK[old.status]:
            merged.append(old)
            continue
        evidence = tuple(dict.fromkeys((*old.evidence, *current.evidence)))
        merged.append(
            KeyPointCoverage(
                point=point,
                status=current.status,
                evidence=evidence,
            )
        )
    return tuple(merged)


def _validated_map(
    values: Iterable[KeyPointCoverage], allowed: set[str]
) -> dict[str, KeyPointCoverage]:
    result: dict[str, KeyPointCoverage] = {}
    for item in values:
        if item.point not in allowed:
            raise ValueError(f"unknown key point: {item.point}")
        if item.point in result:
            raise ValueError(f"duplicate key point decision: {item.point}")
        result[item.point] = item
    return result


class ReviewCompletionPolicy:
    @staticmethod
    def can_advance(
        coverage: Iterable[KeyPointCoverage], *, skipped: bool
    ) -> bool:
        if skipped:
            return True
        values = tuple(coverage)
        return bool(values) and all(item.status == "covered" for item in values)
