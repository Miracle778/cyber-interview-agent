from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import aiosqlite

from app.db.runtime_database import connect_runtime_database, runtime_database_path
from app.knowledge.sources import save_source
from app.security.workspace_paths import WorkspacePathPolicy


@dataclass(frozen=True, slots=True)
class KnowledgeSourceRecord:
    id: str
    workspace_id: str
    original_filename: str
    stored_path: str
    content_type: str
    size_bytes: int
    draft_id: str | None
    created_at: str


class KnowledgeSourceService:
    def __init__(self, workspace_root: Path, *, workspace_id: str) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must not be empty")
        self._workspace_root = workspace_root
        self._workspace_id = workspace_id
        self._database_path = runtime_database_path(workspace_root)
        connect_runtime_database(workspace_root).close()

    async def create(
        self, *, original_filename: str, content_type: str, content: bytes
    ) -> KnowledgeSourceRecord:
        stored_path = save_source(
            self._workspace_root,
            original_filename=original_filename,
            content=content,
        )
        source_id = str(uuid4())
        try:
            async with self._connection() as connection:
                await connection.execute(
                    "INSERT INTO knowledge_sources "
                    "(id, workspace_id, original_filename, stored_path, "
                    "content_type, size_bytes) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        source_id,
                        self._workspace_id,
                        original_filename,
                        stored_path,
                        content_type or "application/octet-stream",
                        len(content),
                    ),
                )
                row = await self._require_row(connection, source_id)
                await connection.commit()
        except Exception:
            self._unlink(stored_path)
            raise
        return self._record(row)

    async def attach_draft(
        self, source_id: str, *, draft_id: str
    ) -> KnowledgeSourceRecord:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "UPDATE knowledge_sources SET draft_id = ? "
                "WHERE id = ? AND workspace_id = ?",
                (draft_id, source_id, self._workspace_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"source {source_id!r} not found")
            row = await self._require_row(connection, source_id)
            await connection.commit()
        return self._record(row)

    async def list(self) -> tuple[KnowledgeSourceRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM knowledge_sources WHERE workspace_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (self._workspace_id,),
            )
            rows = await cursor.fetchall()
        return tuple(self._record(row) for row in rows)

    async def delete(self, source_id: str) -> None:
        async with self._connection() as connection:
            row = await self._require_row(connection, source_id)
            await connection.execute(
                "DELETE FROM knowledge_sources WHERE id = ? AND workspace_id = ?",
                (source_id, self._workspace_id),
            )
            await connection.commit()
        self._unlink(row["stored_path"])

    def _unlink(self, stored_path: str) -> None:
        filename = Path(stored_path).name
        target = WorkspacePathPolicy(self._workspace_root).resolve_for_read(
            "review.sources", filename
        )
        target.unlink()

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection

    async def _require_row(
        self, connection: aiosqlite.Connection, source_id: str
    ) -> aiosqlite.Row:
        cursor = await connection.execute(
            "SELECT * FROM knowledge_sources WHERE id = ? AND workspace_id = ?",
            (source_id, self._workspace_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(f"source {source_id!r} not found")
        return row

    @staticmethod
    def _record(row: aiosqlite.Row) -> KnowledgeSourceRecord:
        return KnowledgeSourceRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            original_filename=row["original_filename"],
            stored_path=row["stored_path"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            draft_id=row["draft_id"],
            created_at=row["created_at"],
        )
