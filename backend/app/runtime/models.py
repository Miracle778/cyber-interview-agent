from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


SessionStatus: TypeAlias = Literal[
    "active",
    "waiting_for_approval",
    "interrupted",
    "completed",
    "migration_required",
    "archived",
]
RunStatus: TypeAlias = Literal[
    "queued",
    "running",
    "waiting_for_approval",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
]
MessageRole: TypeAlias = Literal["user", "assistant", "system", "tool"]


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    workspace_id: str
    graph_id: str
    graph_version: int
    title: str
    status: SessionStatus
    parent_session_id: str | None
    summary: str | None
    created_at: str
    updated_at: str
    last_run_id: str | None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    session_id: str
    status: RunStatus
    input: dict[str, Any]
    model_bindings: dict[str, str]
    resume_count: int
    last_resumed_at: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: str
    session_id: str
    run_id: str | None
    role: MessageRole
    content: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: int
    session_id: str
    run_id: str | None
    type: str
    payload: dict[str, Any]
    created_at: str
