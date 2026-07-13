from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_agent_application
from app.application.session_service import ExecutionRecord, SessionRecord
from app.application.workspace_runtime import AgentApplication
from app.schemas.agent import (
    CreateSessionCommand,
    ExecutionResource,
    SessionDetailResource,
    SessionResource,
    StartExecutionCommand,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post(
    "/sessions",
    response_model=SessionResource,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    command: CreateSessionCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> SessionRecord:
    return await application.create_session(
        workspace_id=command.workspace_id,
        kind=command.kind,
        title=command.title,
    )


@router.get("/sessions", response_model=list[SessionResource])
async def list_sessions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> tuple[SessionRecord, ...]:
    return application.list_sessions(workspace_id)


@router.get("/sessions/{session_id}", response_model=SessionDetailResource)
async def get_session(
    session_id: str, application: AgentApplication = Depends(get_agent_application)
):
    return await application.session_detail(session_id)


@router.post(
    "/sessions/{session_id}/executions",
    response_model=ExecutionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_execution(
    session_id: str,
    command: StartExecutionCommand,
    application: AgentApplication = Depends(get_agent_application),
) -> ExecutionRecord:
    return await application.start_execution(session_id, input=command.input)


@router.post(
    "/executions/{execution_id}/cancel", response_model=ExecutionResource
)
async def cancel_execution(
    execution_id: str,
    application: AgentApplication = Depends(get_agent_application),
) -> ExecutionRecord:
    return await application.cancel_execution(execution_id)


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    after: int | None = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    application: AgentApplication = Depends(get_agent_application),
) -> StreamingResponse:
    await application.session_detail(session_id)
    cursor = after
    if cursor is None and last_event_id is not None:
        try:
            cursor = int(last_event_id)
        except ValueError:
            cursor = None
    return StreamingResponse(
        application.events(session_id, after_id=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
