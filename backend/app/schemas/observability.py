from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

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
    system: bool
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


class TraceEventSummaryResource(ObservabilityModel):
    event_id: str
    operation_id: str
    event_type: str
    observed_at: str | None
    byte_length: int = Field(ge=0)
    sequence: int = Field(ge=0)
    body_state: Literal["available", "quarantined", "deleted", "unavailable"]


class TraceEventSummaryListResource(ObservabilityModel):
    items: list[TraceEventSummaryResource]


class TraceEventContentResource(ObservabilityModel):
    event_id: str
    event_type: str
    content: str
    content_encoding: Literal["utf-8-json"]
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    complete: bool
    sha256: str
    redactions_applied: bool
    reasoning: Any | None = None


class CreateTraceExportCommand(ObservabilityModel):
    metadata_only: StrictBool = True
    include_stored_bodies: StrictBool = False


class TraceExportResource(ObservabilityModel):
    id: str
    workspace_id: str
    run_id: str
    status: Literal["pending", "completed", "failed"]
    metadata_only: bool
    includes_bodies: bool
    artifact_sha256: str | None
    error_code: str | None
    created_at: str
    completed_at: str | None


class ExecutionChangedEventResource(ObservabilityModel):
    event_id: str
    type: Literal["execution.summary.changed"] = "execution.summary.changed"
    execution: ExecutionSummaryResource


class TraceRetentionPolicyResource(ObservabilityModel):
    workspace_id: str
    body_policy: Literal["permanent", "days", "metadata_only"]
    body_days: int | None
    metadata_policy: Literal["retain"]
    updated_at: str


class UpdateTraceRetentionPolicyCommand(ObservabilityModel):
    body_policy: Literal["permanent", "days", "metadata_only"]
    body_days: int | None = Field(default=None, ge=1, le=3650)


class TraceCleanupItemResource(ObservabilityModel):
    relative_path: str
    run_id: str
    event_count: int
    byte_count: int
    sha256: str
    status: str
    error_code: str | None


class TraceCleanupPlanResource(ObservabilityModel):
    id: str
    workspace_id: str
    status: str
    file_count: int
    event_count: int
    total_bytes: int
    protected_active_runs: int
    error_code: str | None
    created_at: str
    completed_at: str | None
    items: list[TraceCleanupItemResource]
