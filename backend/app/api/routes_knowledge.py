from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.dependencies import get_workspace_service
from app.db.connection import connect_index
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.knowledge.sources import MAX_SOURCE_BYTES, SourceTooLargeError, save_source
from app.schemas.drafts import KnowledgeDraftResource, UploadSourceResource
from app.security.workspace_paths import WorkspacePathPolicy
from app.services.document_ingestion import create_question_draft, extract_text
from app.services.markdown import render_question_markdown
from app.services.search_index import IndexedDocument, upsert_document
from app.services.vault import initialize_vault
from app.services.workspace_service import WorkspaceService


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


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
    source_path = save_source(
        workspace,
        original_filename=file.filename or "source.txt",
        content=content,
    )
    question = create_question_draft(extract_text(workspace / source_path))
    drafts = KnowledgeDraftService(workspace, workspace_id=workspace_id)
    draft = await drafts.create(
        CreateDraftCommand(
            domain="review",
            document_type="question",
            document_id=question.id,
            title=question.title,
            markdown=render_question_markdown(question, status="draft"),
            source_refs=(source_path,),
            relation_refs=(),
        )
    )
    return UploadSourceResource(
        draft=KnowledgeDraftResource.model_validate(draft),
        question=question,
    )


@router.post("/rescan")
def rescan_vault(
    workspace_id: str = Form(alias="workspaceId"),
    workspaces: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, int]:
    workspace = workspaces.resolve_root(workspace_id)
    policy = WorkspacePathPolicy(workspace)
    vault = initialize_vault(workspace)
    db_relative = ".cyber-interview-agent/index.sqlite"
    db_path = policy.resolve_for_create("knowledge.active", db_relative)
    connection = connect_index(db_path)
    count = 0
    for path in vault.rglob("*.md"):
        relative_path = path.relative_to(vault)
        safe_path = policy.resolve_for_read(
            "knowledge.active", relative_path.as_posix()
        )
        body = safe_path.read_text(encoding="utf-8")
        document_id = relative_path.with_suffix("").as_posix().replace("/", "__")
        upsert_document(
            connection,
            IndexedDocument(
                id=document_id,
                path=str(relative_path),
                title=path.stem,
                type="source",
                status="reviewed",
                body=body,
            ),
        )
        count += 1
    connection.close()
    return {"indexed": count}
