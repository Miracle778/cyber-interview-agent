from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.observability.models import (
    ObservabilityCapability,
    OperationKind,
    TraceHealth,
)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ObservabilityModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ExecutionSummaryResource(ObservabilityModel):
    id: str
    session_id: str
    workspace_id: str
    graph_id: str
    display_name: str
    title: str
    status: str
    trace_health: TraceHealth
    capabilities: list[ObservabilityCapability]
    route: str
    system_operation_count: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    context_current_tokens: int = Field(ge=0)
    context_threshold_tokens: int = Field(ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(ge=0)
    created_at: str
    started_at: str | None
    finished_at: str | None
    error_code: str | None = None


class OperationSummaryResource(ObservabilityModel):
    id: str
    run_id: str
    parent_operation_id: str | None
    kind: OperationKind
    name: str
    agent_role: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    latency_ms: int | None = Field(default=None, ge=0)
    retry_count: int = Field(ge=0)
    error_code: str | None
    event_count: int = Field(ge=0)


class ExecutionSummaryPageResource(ObservabilityModel):
    items: list[ExecutionSummaryResource]
    next_cursor: str | None
    total: int = Field(ge=0)


class OperationSummaryListResource(ObservabilityModel):
    items: list[OperationSummaryResource]


class ExecutionChangedEventResource(ObservabilityModel):
    event_id: str
    type: Literal["execution.summary.changed"] = "execution.summary.changed"
    execution: ExecutionSummaryResource
