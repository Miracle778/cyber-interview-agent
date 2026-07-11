from pathlib import Path
from pathlib import PureWindowsPath
from shutil import copyfileobj
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile

from app.db.connection import connect_index
from app.schemas.review import ReviewQuestion
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy
from app.services.document_ingestion import create_question_draft, extract_text
from app.services.search_index import IndexedDocument, upsert_document
from app.services.vault import initialize_vault

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

@router.post("/sources")
async def upload_source(workspace_path: str = Form(..., alias="workspacePath"), file: UploadFile = File(...)) -> ReviewQuestion:
    policy = WorkspacePathPolicy(Path(workspace_path))
    workspace = policy.workspace_root
    vault = initialize_vault(workspace)
    filename = file.filename or f"source_{uuid4().hex}.txt"
    if (
        filename in {"", ".", ".."}
        or Path(filename).name != filename
        or PureWindowsPath(filename).name != filename
    ):
        raise PathPolicyError("knowledge.active")
    relative_path = f"00_inbox/{filename}"
    policy.resolve_for_create("knowledge.active", relative_path)
    destination = policy.resolve_for_create("knowledge.active", relative_path)
    with destination.open("wb") as target:
        copyfileobj(file.file, target)
    destination = policy.resolve_for_read("knowledge.active", relative_path)
    text = extract_text(destination)
    return create_question_draft(text)

@router.post("/rescan")
def rescan_vault(workspace_path: str = Form(..., alias="workspacePath")) -> dict[str, int]:
    policy = WorkspacePathPolicy(Path(workspace_path))
    workspace = policy.workspace_root
    vault = initialize_vault(workspace)
    db_relative = ".cyber-interview-agent/index.sqlite"
    policy.resolve_for_create("knowledge.active", db_relative)
    db_path = policy.resolve_for_create("knowledge.active", db_relative)
    conn = connect_index(db_path)
    count = 0
    for path in vault.rglob("*.md"):
        relative_path = path.relative_to(vault)
        safe_path = policy.resolve_for_read(
            "knowledge.active", relative_path.as_posix()
        )
        safe_path = policy.resolve_for_read(
            "knowledge.active", relative_path.as_posix()
        )
        body = safe_path.read_text(encoding="utf-8")
        document_id = relative_path.with_suffix("").as_posix().replace("/", "__")
        upsert_document(conn, IndexedDocument(
            id=document_id,
            path=str(relative_path),
            title=path.stem,
            type="source",
            status="reviewed",
            body=body,
        ))
        count += 1
    return {"indexed": count}
