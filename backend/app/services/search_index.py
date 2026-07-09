import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

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
