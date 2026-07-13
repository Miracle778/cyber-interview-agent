from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.hitl.models import ResolveActionCommand
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
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.list_actions(
        workspace_id, status=status, session_id=session_id
    )


@router.get("/{action_id}", response_model=PendingActionResource)
async def get_action(
    action_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.get_action(action_id)


@router.post("/{action_id}/approve", response_model=PendingActionResource)
async def approve_action(
    action_id: str,
    request: ResolveActionRequest,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.approve_action(
        action_id,
        ResolveActionCommand.model_validate(request.model_dump()),
    )


@router.post("/{action_id}/reject", response_model=PendingActionResource)
async def reject_action(
    action_id: str,
    request: ResolveActionRequest,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.reject_action(
        action_id,
        ResolveActionCommand.model_validate(request.model_dump()),
    )
