from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.evaluation.contracts import EvaluationTriggerPolicy


@dataclass(frozen=True, slots=True)
class AutomaticEvaluationDecision:
    selected: bool
    reason: str


_RISK_STATUSES = frozenset(
    {"failed", "partial_success", "degraded", "rejected", "heavily_edited"}
)


def decide_automatic_evaluation(
    *,
    execution_id: str,
    status: str,
    policy: EvaluationTriggerPolicy,
    degraded: bool = False,
    rejected: bool = False,
    heavily_edited: bool = False,
) -> AutomaticEvaluationDecision:
    effective_statuses = {status}
    if degraded:
        effective_statuses.add("degraded")
    if rejected:
        effective_statuses.add("rejected")
    if heavily_edited:
        effective_statuses.add("heavily_edited")
    if effective_statuses & _RISK_STATUSES & policy.automatic_statuses:
        return AutomaticEvaluationDecision(True, "risk")
    if status != "completed" or policy.successful_sample_percent <= 0:
        return AutomaticEvaluationDecision(False, "not_selected")
    bucket = int(hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return AutomaticEvaluationDecision(
        bucket < policy.successful_sample_percent,
        "success_sample" if bucket < policy.successful_sample_percent else "not_selected",
    )
