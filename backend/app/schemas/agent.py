from typing import Any

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
    graph_id: str
    graph_version: int
    title: str


class StartRunCommand(AgentModel):
    input: dict[str, Any]


class SessionResource(AgentModel):
    id: str
    workspace_id: str
    graph_id: str
    graph_version: int
    title: str
    status: str
    created_at: str
    updated_at: str
    last_run_id: str | None


class RunResource(AgentModel):
    id: str
    session_id: str
    status: str
    resume_count: int
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class MessageResource(AgentModel):
    id: str
    run_id: str | None
    role: str
    content: str
    created_at: str


class SessionDetailResource(SessionResource):
    messages: list[MessageResource]
    latest_run: RunResource | None
    pending_action: None = None
