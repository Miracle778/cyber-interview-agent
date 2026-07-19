from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class AgentModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel, populate_by_name=True, from_attributes=True
    )


class CreateSessionCommand(AgentModel):
    workspace_id: str
    kind: str
    title: str | None = None


class ExecutionConfigurationResource(AgentModel):
    provider_model_id: str | None = None
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"


class StartExecutionCommand(AgentModel):
    input: dict[str, Any]
    configuration: ExecutionConfigurationResource | None = None


class SessionResource(AgentModel):
    id: str
    workspace_id: str
    kind: str
    title: str
    status: str
    created_at: str
    updated_at: str
    latest_execution_id: str | None
    deleted_at: str | None = None


class ExecutionResource(AgentModel):
    id: str
    session_id: str
    status: str
    configuration: "ExecutionConfigurationResource"
    cancel_requested_at: str | None
    resume_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class MessageResource(AgentModel):
    id: str
    execution_id: str | None
    role: str
    content: str
    message_kind: str
    payload: dict[str, Any]
    created_at: str


class PendingActionSummaryResource(AgentModel):
    id: str
    action_type: str
    preview: dict[str, Any]
    status: str
    version: int


class SessionUsageResource(AgentModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    call_count: int
    estimated_count: int


class ContextUsageResource(AgentModel):
    current_tokens: int
    threshold_tokens: int
    estimated: bool


class GuardWarningResource(AgentModel):
    code: str
    message: str


class SessionDetailResource(SessionResource):
    usage: SessionUsageResource
    context_usage: ContextUsageResource
    context_compacted: bool
    latest_warning: GuardWarningResource | None = None
    messages: list[MessageResource]
    executions: list[ExecutionResource]
    latest_execution: ExecutionResource | None
    current_action: PendingActionSummaryResource | None = None
