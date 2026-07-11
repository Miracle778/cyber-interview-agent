from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent_runtime
from app.runtime.models import RunRecord, SessionRecord
from app.runtime.service import AgentRuntime
from app.schemas.agent import (
    CreateSessionCommand,
    RunResource,
    SessionDetailResource,
    SessionResource,
    StartRunCommand,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post(
    "/sessions",
    response_model=SessionResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    command: CreateSessionCommand,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> SessionRecord:
    return await runtime.create_session(
        workspace_id=command.workspace_id,
        graph_id=command.graph_id,
        graph_version=command.graph_version,
        title=command.title,
    )


@router.get("/sessions", response_model=list[SessionResource])
def list_sessions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> tuple[SessionRecord, ...]:
    return runtime.list_sessions(workspace_id)


@router.get("/sessions/{session_id}", response_model=SessionDetailResource)
def get_session(
    session_id: str, runtime: AgentRuntime = Depends(get_agent_runtime)
):
    return runtime.session_detail(session_id)


@router.post(
    "/sessions/{session_id}/runs",
    response_model=RunResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    session_id: str,
    command: StartRunCommand,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> RunRecord:
    return await runtime.start_run(session_id, input=command.input)


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_run(
    run_id: str, runtime: AgentRuntime = Depends(get_agent_runtime)
) -> RunRecord:
    return await runtime.resume_run(run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunResource)
async def cancel_run(
    run_id: str, runtime: AgentRuntime = Depends(get_agent_runtime)
) -> RunRecord:
    return await runtime.cancel_run(run_id)


@router.get("/sessions/{session_id}/events")
def stream_events(
    session_id: str,
    after: int | None = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> StreamingResponse:
    cursor = after
    if cursor is None and last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError:
            cursor = None
    return StreamingResponse(
        runtime.events(session_id, after_id=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
