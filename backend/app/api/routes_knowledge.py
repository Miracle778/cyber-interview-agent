from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.api.dependencies import get_workspace_service
from app.db.connection import connect_index
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.sources import MAX_SOURCE_BYTES, SourceTooLargeError
from app.knowledge.publication import PublicationService
from app.schemas.drafts import (
    KnowledgeDraftResource,
    KnowledgeSourceResource,
    UploadSourceResource,
)
from app.security.workspace_paths import WorkspacePathPolicy
from app.services.search_index import rescan_active_documents
from app.services.vault import initialize_vault
from app.services.workspace_service import WorkspaceService


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/sources", response_model=list[KnowledgeSourceResource])
async def list_sources(
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> list[KnowledgeSourceResource]:
    workspace = workspaces.resolve_root(workspace_id)
    records = await KnowledgeSourceService(
        workspace, workspace_id=workspace_id
    ).list()
    return [KnowledgeSourceResource.model_validate(item) for item in records]


@router.post(
    "/sources",
    response_model=UploadSourceResource,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    workspace_id: str = Form(alias="workspaceId"),
    file: UploadFile = File(...),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> UploadSourceResource:
    workspace = workspaces.resolve_root(workspace_id)
    content = await file.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise SourceTooLargeError("source exceeds 10 MiB")
    sources = KnowledgeSourceService(workspace, workspace_id=workspace_id)
    source = await sources.create(
        original_filename=file.filename or "source.txt",
        content_type=file.content_type or "application/octet-stream",
        content=content,
    )
    return UploadSourceResource(
        source=KnowledgeSourceResource.model_validate(source),
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    hard: bool = False,
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> Response:
    workspace = workspaces.resolve_root(workspace_id)
    try:
        await KnowledgeSourceService(workspace, workspace_id=workspace_id).delete(
            source_id, hard=hard
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sources/{source_id}/restore", response_model=KnowledgeSourceResource
)
async def restore_source(
    source_id: str,
    workspace_id: Annotated[str, Query(alias="workspaceId")],
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> KnowledgeSourceResource:
    workspace = workspaces.resolve_root(workspace_id)
    try:
        source = await KnowledgeSourceService(
            workspace, workspace_id=workspace_id
        ).restore(source_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return KnowledgeSourceResource.model_validate(source)


@router.post("/rescan")
async def rescan_vault(
    workspace_id: str = Form(alias="workspaceId"),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, int]:
    workspace = workspaces.resolve_root(workspace_id)
    policy = WorkspacePathPolicy(workspace)
    vault = initialize_vault(workspace)
    db_relative = ".cyber-interview-agent/index.sqlite"
    db_path = policy.resolve_for_create("knowledge.active", db_relative)
    connection = connect_index(db_path)
    for path in vault.rglob("*.md"):
        policy.resolve_for_read("knowledge.active", path.relative_to(vault).as_posix())
    try:
        result = rescan_active_documents(connection, vault)
    finally:
        connection.close()
    repaired = await PublicationService(
        workspace, workspace_id=workspace_id
    ).repair_index_stale_after_rescan()
    return {**result, "repaired": repaired}
