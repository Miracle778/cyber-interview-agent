from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


SupportType = Literal[
    "direct", "normalized", "inferred", "user_asserted", "unsupported"
]
UserDecisionStatus = Literal[
    "pending", "accepted", "edited", "rejected", "ignored"
]


class OutcomeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeIdentity(OutcomeModel):
    workspace_id: str
    session_id: str
    execution_id: str
    graph_id: str
    domain_refs: dict[str, str]


class OutcomeInput(OutcomeModel):
    source_refs: tuple[str, ...]
    input_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    requested_scope: dict[str, object]


class OutcomeProvenance(OutcomeModel):
    field_path: str
    support_type: SupportType
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    note: str | None = None


class OutcomeUserDecision(OutcomeModel):
    status: UserDecisionStatus
    version: int = Field(default=0, ge=0)
    occurred_at: str | None = None
    reason: str | None = None


class OutcomeItem(OutcomeModel):
    item_id: str
    item_type: str
    status: str
    domain_version: int | None = Field(default=None, ge=0)
    content: dict[str, object]
    provenance: tuple[OutcomeProvenance, ...]
    user_decision: OutcomeUserDecision


class OutcomeUnit(OutcomeModel):
    unit_id: str
    unit_type: str
    status: str
    error_code: str | None = None


class OutcomeCounters(OutcomeModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    pending: int = Field(ge=0)


class BusinessOutcomePayload(OutcomeModel):
    contract_version: int = Field(default=1, ge=1)
    task_type: str
    identity: OutcomeIdentity
    input: OutcomeInput
    execution_status: str
    terminal_state: str
    items: tuple[OutcomeItem, ...]
    units: tuple[OutcomeUnit, ...]
    unit_counters: dict[str, OutcomeCounters]
    evidence_gaps: tuple[str, ...] = ()
    runtime_versions: dict[str, str] = Field(default_factory=dict)


class BusinessOutcomeProjection(BusinessOutcomePayload):
    outcome_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class BusinessOutcomeAdapter(Protocol):
    task_type: str

    def build(self, execution_id: str) -> BusinessOutcomeProjection: ...


def freeze_business_outcome(
    payload: BusinessOutcomePayload,
) -> BusinessOutcomeProjection:
    serialized = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return BusinessOutcomeProjection(
        **payload.model_dump(),
        outcome_hash=sha256(serialized.encode("utf-8")).hexdigest(),
    )
