from __future__ import annotations

import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import (
    get_agent_application,
    get_agent_observability_service,
)
from app.application.workspace_runtime import AgentApplication
from app.observability.service import (
    AgentExecutionNotFoundError,
    AgentObservabilityService,
    InvalidExecutionCursorError,
)
from app.schemas.observability import (
    ExecutionSummaryPageResource,
    ExecutionSummaryResource,
    OperationSummaryListResource,
)


router = APIRouter(prefix="/api/agent-observability", tags=["agent-observability"])


def _query_error(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "invalid_observability_query",
            "message": message,
        },
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "code": "agent_execution_not_found",
            "message": "Agent Execution 不存在或无权访问",
        },
    )


@router.get(
    "/executions",
    response_model=ExecutionSummaryPageResource,
)
async def list_observability_executions(
    search: str | None = None,
    status: str | None = None,
    agent_name: Annotated[str | None, Query(alias="agentName")] = None,
    started_from: Annotated[str | None, Query(alias="startedFrom")] = None,
    started_to: Annotated[str | None, Query(alias="startedTo")] = None,
    include_system_agents: Annotated[
        bool, Query(alias="includeSystemAgents")
    ] = False,
    cursor: str | None = None,
    limit: int = 50,
    service: AgentObservabilityService = Depends(
        get_agent_observability_service
    ),
):
    service.sync_if_due()
    try:
        return service.list_executions(
            keyword=search,
            status=status,
            agent=agent_name,
            started_from=started_from,
            started_to=started_to,
            include_system_agents=include_system_agents,
            cursor=cursor,
            limit=limit,
        )
    except InvalidExecutionCursorError:
        return _query_error("分页游标无效")
    except ValueError as error:
        message = str(error)
        if message == "limit must be between 1 and 200":
            return _query_error("每页数量必须在 1 到 200 之间")
        if message == "invalid execution time filter":
            return _query_error("时间筛选格式无效")
        return _query_error("筛选条件无效")


@router.get(
    "/executions/{run_id}",
    response_model=ExecutionSummaryResource,
)
async def get_observability_execution(
    run_id: str,
    service: AgentObservabilityService = Depends(
        get_agent_observability_service
    ),
):
    service.sync_if_due()
    try:
        return service.get_execution(run_id)
    except AgentExecutionNotFoundError:
        return _not_found()


@router.get(
    "/executions/{run_id}/operations",
    response_model=OperationSummaryListResource,
)
async def list_observability_operations(
    run_id: str,
    service: AgentObservabilityService = Depends(
        get_agent_observability_service
    ),
):
    service.sync_if_due()
    try:
        return service.list_operations(run_id)
    except AgentExecutionNotFoundError:
        return _not_found()


def _parse_event_cursor(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _encode_change_event(change) -> str:
    payload = change.model_dump(by_alias=True, mode="json")
    return (
        f"id: {change.event_id}\n"
        "event: execution.summary.changed\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _event_stream(
    service: AgentObservabilityService,
    *,
    after_event_id: int | None,
) -> AsyncIterator[str]:
    async for change in service.changes(after_event_id=after_event_id):
        yield ": keepalive\n\n" if change is None else _encode_change_event(change)


@router.get("/events")
async def stream_observability_events(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    after_event_id: Annotated[
        str | None, Query(alias="afterEventId")
    ] = None,
    last_event_id: Annotated[
        str | None, Header(alias="Last-Event-ID")
    ] = None,
    application: AgentApplication = Depends(get_agent_application),
) -> StreamingResponse:
    cursor = _parse_event_cursor(after_event_id or last_event_id)
    service = application.agent_observability(workspace_id)
    return StreamingResponse(
        _event_stream(service, after_event_id=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
