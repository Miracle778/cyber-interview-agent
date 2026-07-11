from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_agent_runtime
from app.hitl.models import ResolveActionCommand
from app.runtime.service import AgentRuntime
from app.schemas.hitl import PendingActionResource, ResolveActionRequest


router = APIRouter(prefix="/api/agent/actions", tags=["agent-actions"])


@router.get("", response_model=list[PendingActionResource])
async def list_actions(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    status: Literal[
        "pending",
        "approved",
        "edited_and_approved",
        "rejected",
        "cancelled",
    ]
    | None = None,
    session_id: Annotated[str | None, Query(alias="sessionId")] = None,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.list_actions(
        workspace_id, status=status, session_id=session_id
    )


@router.get("/{action_id}", response_model=PendingActionResource)
async def get_action(
    action_id: str,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.get_action(action_id)


@router.post("/{action_id}/approve", response_model=PendingActionResource)
async def approve_action(
    action_id: str,
    request: ResolveActionRequest,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.approve_action(
        action_id,
        ResolveActionCommand.model_validate(request.model_dump()),
    )


@router.post("/{action_id}/reject", response_model=PendingActionResource)
async def reject_action(
    action_id: str,
    request: ResolveActionRequest,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.reject_action(
        action_id,
        ResolveActionCommand.model_validate(request.model_dump()),
    )
