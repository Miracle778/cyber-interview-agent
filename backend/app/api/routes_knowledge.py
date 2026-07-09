from pathlib import Path
from shutil import copyfileobj
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db.connection import connect_index
from app.schemas.review import ReviewQuestion
from app.services.document_ingestion import create_question_draft, extract_text
from app.services.search_index import IndexedDocument, upsert_document
from app.services.vault import initialize_vault
from app.services.workspace import WorkspaceError, ensure_inside_workspace, resolve_workspace

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

@router.post("/sources")
async def upload_source(workspace_path: str = Form(..., alias="workspacePath"), file: UploadFile = File(...)) -> ReviewQuestion:
    workspace = resolve_workspace(workspace_path)
    vault = initialize_vault(workspace)
    inbox = vault / "00_inbox"
    safe_filename = Path(file.filename or f"source_{uuid4().hex}.txt").name
    if safe_filename in {"", ".", ".."}:
        safe_filename = f"source_{uuid4().hex}.txt"
    destination = inbox / safe_filename
    try:
        ensure_inside_workspace(workspace, destination)
    except WorkspaceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    with destination.open("wb") as target:
        copyfileobj(file.file, target)
    text = extract_text(Path(destination))
    return create_question_draft(text)

@router.post("/rescan")
def rescan_vault(workspace_path: str = Form(..., alias="workspacePath")) -> dict[str, int]:
    workspace = resolve_workspace(workspace_path)
    vault = initialize_vault(workspace)
    db_path = vault / ".cyber-interview-agent" / "index.sqlite"
    conn = connect_index(db_path)
    count = 0
    for path in vault.rglob("*.md"):
        body = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(vault)
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
