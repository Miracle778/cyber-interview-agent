from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


ObservabilityCapability = Literal[
    "open_business",
    "cancel",
    "retry",
    "resume",
    "manual_judge",
    "export_trace",
]
OperationKind = Literal["execution", "agent", "model", "tool", "graph"]


class TraceHealth(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OperationSummary:
    id: str
    run_id: str
    parent_operation_id: str | None
    kind: OperationKind
    name: str
    agent_role: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    latency_ms: int | None
    retry_count: int
    error_code: str | None
    event_count: int
