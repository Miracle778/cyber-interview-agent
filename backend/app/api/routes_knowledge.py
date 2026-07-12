from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.dependencies import get_workspace_service
from app.db.connection import connect_index
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.knowledge.source_registry import KnowledgeSourceService
from app.knowledge.sources import MAX_SOURCE_BYTES, SourceTooLargeError
from app.knowledge.publication import PublicationService
from app.schemas.drafts import (
    KnowledgeDraftResource,
    KnowledgeSourceResource,
    UploadSourceResource,
)
from app.security.workspace_paths import WorkspacePathPolicy
from app.services.document_ingestion import create_question_draft, extract_text
from app.services.markdown import render_question_markdown
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
    question = create_question_draft(extract_text(workspace / source.stored_path))
    drafts = KnowledgeDraftService(workspace, workspace_id=workspace_id)
    try:
        draft = await drafts.create(
            CreateDraftCommand(
                domain="review",
                document_type="question",
                document_id=question.id,
                title=question.title,
                markdown=render_question_markdown(question, status="draft"),
                source_refs=(source.stored_path,),
                relation_refs=(),
            )
        )
    except Exception:
        await sources.delete(source.id)
        raise
    source = await sources.attach_draft(source.id, draft_id=draft.id)
    return UploadSourceResource(
        source=KnowledgeSourceResource.model_validate(source),
        draft=KnowledgeDraftResource.model_validate(draft),
        question=question,
    )


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
