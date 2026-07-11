import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

@dataclass(frozen=True)
class IndexedDocument:
    id: str
    path: str
    title: str
    type: str
    status: str
    body: str

def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def upsert_document(conn: sqlite3.Connection, document: IndexedDocument) -> None:
    now = datetime.now(timezone.utc).isoformat()
    digest = checksum(document.body)
    conn.execute(
        """
        INSERT INTO manifest_documents (id, path, title, type, status, checksum, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          path=excluded.path,
          title=excluded.title,
          type=excluded.type,
          status=excluded.status,
          checksum=excluded.checksum,
          updated_at=excluded.updated_at
        """,
        (document.id, document.path, document.title, document.type, document.status, digest, now),
    )
    conn.execute("DELETE FROM document_fts WHERE id = ?", (document.id,))
    conn.execute(
        "INSERT INTO document_fts (id, title, body) VALUES (?, ?, ?)",
        (document.id, document.title, document.body),
    )
    conn.commit()

def search_documents(conn: sqlite3.Connection, query: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM document_fts WHERE document_fts MATCH ? ORDER BY rank LIMIT 20",
        (query,),
    ).fetchall()
    return [row[0] for row in rows]


def rescan_active_documents(conn: sqlite3.Connection, vault: Path) -> dict[str, int]:
    conn.execute("DELETE FROM document_fts")
    conn.execute("DELETE FROM manifest_documents")
    conn.commit()
    indexed = 0
    skipped = 0
    for path in sorted(vault.rglob("*.md")):
        if path.is_symlink():
            skipped += 1
            continue
        try:
            post = frontmatter.load(path)
        except Exception:
            skipped += 1
            continue
        ingestion = post.metadata.get("ingestion")
        if post.metadata.get("status") != "ingested" or not isinstance(ingestion, dict) or ingestion.get("confirmed_by_user") is not True:
            skipped += 1
            continue
        document_id = post.metadata.get("id")
        document_type = post.metadata.get("type")
        title = post.metadata.get("title")
        if not all(isinstance(value, str) and value for value in (document_id, document_type, title)):
            skipped += 1
            continue
        relative = path.relative_to(vault).as_posix()
        upsert_document(conn, IndexedDocument(id=document_id, path=relative, title=title, type=document_type, status="ingested", body=post.content))
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}
