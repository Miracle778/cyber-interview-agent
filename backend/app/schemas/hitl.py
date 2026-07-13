from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class HitlModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class PendingActionResource(HitlModel):
    id: str
    workspace_id: str
    session_id: str
    execution_id: str = Field(validation_alias="run_id")
    action_type: str
    preview: dict[str, Any]
    editable_fields: tuple[str, ...]
    status: Literal[
        "pending",
        "approved",
        "edited_and_approved",
        "rejected",
        "cancelled",
    ]
    version: int
    created_at: str
    resolved_at: str | None


class ResolveActionRequest(HitlModel):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)
    edited_payload: dict[str, Any] | None = None
    reason: str | None = None
