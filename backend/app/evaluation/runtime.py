from __future__ import annotations

from app.evaluation.contracts import EvalPack
from app.evaluation.rules import (
    DeterministicEvaluationResult,
    evaluate_deterministic_rules,
)
from app.evaluation.snapshot import FrozenEvaluationSnapshot


class EvaluationRuntime:
    """Read-only evaluation surface; no domain service or generic tools."""

    __slots__ = ("_snapshot", "_pack")

    def __init__(
        self,
        *,
        snapshot: FrozenEvaluationSnapshot,
        pack: EvalPack,
    ) -> None:
        if (
            snapshot.eval_pack_id != pack.id
            or snapshot.eval_pack_version != pack.version
        ):
            raise ValueError("snapshot and Eval Pack versions do not match")
        self._snapshot = snapshot
        self._pack = pack

    @property
    def snapshot(self) -> FrozenEvaluationSnapshot:
        return self._snapshot

    @property
    def pack(self) -> EvalPack:
        return self._pack

    def run_deterministic(self) -> DeterministicEvaluationResult:
        return evaluate_deterministic_rules(self._snapshot, self._pack)
