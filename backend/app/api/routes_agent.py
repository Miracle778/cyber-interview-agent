from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import get_agent_application
from app.application.session_service import (
    ExecutionRecord,
    ProductRecordNotFoundError,
    SessionBusyError,
    SessionRecord,
)
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
    try:
        return await application.create_session(
            workspace_id=command.workspace_id,
            kind=command.kind,
            title=command.title,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/sessions", response_model=list[SessionResource])
async def list_sessions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
) -> tuple[SessionRecord, ...]:
    return application.list_sessions(workspace_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    hard: bool = False,
    application: AgentApplication = Depends(get_agent_application),
) -> Response:
    try:
        application.delete_session(session_id, hard=hard)
    except ProductRecordNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SessionBusyError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/restore", response_model=SessionResource)
async def restore_session(
    session_id: str,
    application: AgentApplication = Depends(get_agent_application),
) -> SessionRecord:
    try:
        return application.restore_session(session_id)
    except ProductRecordNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/sessions/{session_id}", response_model=SessionDetailResource)
async def get_session(
    session_id: str, application: AgentApplication = Depends(get_agent_application)
):
    try:
        return await application.session_detail(session_id)
    except ProductRecordNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


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
    configuration = (
        None
        if command.configuration is None
        else command.configuration.model_dump(by_alias=True)
    )
    return await application.start_execution(
        session_id, input=command.input, configuration=configuration
    )


@router.post(
    "/executions/{execution_id}/cancel", response_model=ExecutionResource
)
async def cancel_execution(
    execution_id: str,
    application: AgentApplication = Depends(get_agent_application),
) -> ExecutionRecord:
    try:
        return await application.cancel_execution(execution_id)
    except ProductRecordNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    after: int | None = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    application: AgentApplication = Depends(get_agent_application),
) -> Response:
    try:
        await application.session_detail(session_id)
    except ProductRecordNotFoundError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
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
