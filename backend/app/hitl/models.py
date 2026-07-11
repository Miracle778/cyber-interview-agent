from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


PendingActionStatus: TypeAlias = Literal[
    "pending",
    "approved",
    "edited_and_approved",
    "rejected",
    "cancelled",
]
ResolvedActionStatus: TypeAlias = Literal[
    "approved", "edited_and_approved", "rejected"
]
DeliveryStatus: TypeAlias = Literal[
    "pending", "delivering", "delivered", "failed"
]


@dataclass(frozen=True, slots=True)
class CreatePendingAction:
    workspace_id: str
    session_id: str
    run_id: str
    action_type: str
    payload: dict[str, Any]
    preview: dict[str, Any]
    editable_fields: tuple[str, ...]
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in (
            "workspace_id",
            "session_id",
            "run_id",
            "action_type",
            "idempotency_key",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        if not set(self.editable_fields) <= set(self.payload):
            raise ValueError("editable_fields must reference payload fields")


@dataclass(frozen=True, slots=True)
class PendingActionRecord:
    id: str
    workspace_id: str
    session_id: str
    run_id: str
    action_type: str
    payload: dict[str, Any]
    preview: dict[str, Any]
    editable_fields: tuple[str, ...]
    status: PendingActionStatus
    version: int
    idempotency_key: str
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True, slots=True)
class ResolutionReceipt:
    id: str
    action_id: str
    resolution_key: str
    status: ResolvedActionStatus
    decision: dict[str, Any]
    reason: str | None
    delivery_status: DeliveryStatus
    delivery_attempts: int
    delivery_error_code: str | None
    created_at: str
    delivered_at: str | None
