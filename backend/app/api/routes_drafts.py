from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_agent_runtime
from app.knowledge.drafts import UpdateDraftCommand
from app.runtime.service import AgentRuntime
from app.schemas.drafts import (
    KnowledgeDraftResource,
    PublishDraftRunResource,
    UpdateKnowledgeDraftRequest,
)


router = APIRouter(prefix="/api/knowledge/drafts", tags=["knowledge-drafts"])


@router.get("", response_model=list[KnowledgeDraftResource])
async def list_drafts(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.list_drafts(workspace_id)


@router.get("/{draft_id}", response_model=KnowledgeDraftResource)
async def get_draft(
    draft_id: str,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.get_draft(draft_id)


@router.patch("/{draft_id}", response_model=KnowledgeDraftResource)
async def update_draft(
    draft_id: str,
    request: UpdateKnowledgeDraftRequest,
    runtime: AgentRuntime = Depends(get_agent_runtime),
):
    return await runtime.update_draft(
        draft_id,
        UpdateDraftCommand(
            expected_version=request.version,
            title=request.title,
            markdown=request.markdown,
        ),
    )


@router.post(
    "/{draft_id}/publish-request",
    response_model=PublishDraftRunResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_publication(
    draft_id: str,
    runtime: AgentRuntime = Depends(get_agent_runtime),
) -> PublishDraftRunResource:
    run = await runtime.request_draft_publication(draft_id)
    return PublishDraftRunResource(
        session_id=run.session_id,
        run_id=run.id,
        status=run.status,
    )
