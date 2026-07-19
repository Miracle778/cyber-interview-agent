from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.knowledge.drafts import UpdateDraftCommand
from app.schemas.drafts import (
    KnowledgeDraftResource,
    PublishDraftExecutionResource,
    UpdateKnowledgeDraftRequest,
)
from app.schemas.hitl import PendingActionResource


router = APIRouter(prefix="/api/knowledge/drafts", tags=["knowledge-drafts"])


@router.get("", response_model=list[KnowledgeDraftResource])
async def list_drafts(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.list_drafts(workspace_id)


@router.get("/{draft_id}", response_model=KnowledgeDraftResource)
async def get_draft(
    draft_id: str,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.get_draft(draft_id)


@router.patch("/{draft_id}", response_model=KnowledgeDraftResource)
async def update_draft(
    draft_id: str,
    request: UpdateKnowledgeDraftRequest,
    application: AgentApplication = Depends(get_agent_application),
):
    return await application.update_draft(
        draft_id,
        UpdateDraftCommand(
            expected_version=request.version,
            title=request.title,
            markdown=request.markdown,
        ),
    )


@router.post(
    "/{draft_id}/publish-request",
    response_model=PublishDraftExecutionResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_publication(
    draft_id: str,
    application: AgentApplication = Depends(get_agent_application),
) -> PublishDraftExecutionResource:
    result = await application.request_draft_publication(draft_id)
    return PublishDraftExecutionResource(
        session_id=result.execution.session_id,
        execution_id=result.execution.id,
        status=result.execution.status,
        action=PendingActionResource.model_validate(result.action),
        reused=result.reused,
    )
