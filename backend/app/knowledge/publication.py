from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias
from uuid import uuid4

import aiosqlite

from app.db.connection import connect_index
from app.infrastructure.runtime_database import runtime_database_path
from app.hitl.models import PendingActionRecord
from app.knowledge.atomic_writer import ExternalDocumentChangedError, atomic_write_text, hash_file
from app.knowledge.document_types import create_document_type_registry
from app.knowledge.drafts import DraftVersionChangedError, KnowledgeDraftRecord, KnowledgeDraftService
from app.knowledge.frontmatter import PublishedDocument, PublishedProvenance, render_published_document
from app.security.workspace_paths import WorkspacePathPolicy
from app.services.search_index import IndexedDocument, upsert_document
from app.services.vault import initialize_vault


PublicationState: TypeAlias = Literal["prepared", "file_written", "indexed", "completed", "index_stale", "failed"]
IndexDocument = Callable[[Path, PublishedDocument, str, str], None]


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    id: str
    action_id: str
    draft_id: str
    expected_draft_version: int
    expected_content_hash: str
    document_id: str
    target_path: str
    state: PublicationState
    result_hash: str | None
    error_code: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class PublicationRepository:
    def __init__(self, workspace_root: Path) -> None:
        self._database_path = runtime_database_path(workspace_root)

    async def prepare(self, action: PendingActionRecord, draft: KnowledgeDraftRecord, target_path: str) -> PublicationRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute("SELECT * FROM publication_runs WHERE action_id = ?", (action.id,))
            row = await cursor.fetchone()
            if row is None:
                publication_id = str(uuid4())
                await connection.execute(
                    "INSERT INTO publication_runs (id, action_id, draft_id, expected_draft_version, expected_content_hash, document_id, target_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (publication_id, action.id, draft.id, draft.version, draft.content_hash, draft.document_id, target_path),
                )
                row = await self._require(connection, publication_id)
            await connection.commit()
        return self._record(row)

    async def transition(self, publication_id: str, *, expected: tuple[str, ...], target: PublicationState, result_hash: str | None = None, error_code: str | None = None) -> PublicationRecord:
        placeholders = ",".join("?" for _ in expected)
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                f"UPDATE publication_runs SET state = ?, result_hash = COALESCE(?, result_hash), error_code = ?, updated_at = CURRENT_TIMESTAMP, completed_at = CASE WHEN ? = 'completed' THEN CURRENT_TIMESTAMP ELSE completed_at END WHERE id = ? AND state IN ({placeholders})",
                (target, result_hash, error_code, target, publication_id, *expected),
            )
            if cursor.rowcount != 1:
                row = await self._require(connection, publication_id)
                await connection.commit()
                return self._record(row)
            row = await self._require(connection, publication_id)
            await connection.commit()
        return self._record(row)

    async def list_by_state(self, state: PublicationState) -> tuple[PublicationRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM publication_runs WHERE state = ? ORDER BY created_at, id",
                (state,),
            )
            rows = await cursor.fetchall()
        return tuple(self._record(row) for row in rows)

    async def latest_for_draft(
        self, draft_id: str
    ) -> PublicationRecord | None:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM publication_runs WHERE draft_id = ? "
                "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (draft_id,),
            )
            row = await cursor.fetchone()
        return None if row is None else self._record(row)

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection

    @staticmethod
    async def _require(connection: aiosqlite.Connection, publication_id: str) -> aiosqlite.Row:
        cursor = await connection.execute("SELECT * FROM publication_runs WHERE id = ?", (publication_id,))
        row = await cursor.fetchone()
        if row is None:
            raise LookupError(publication_id)
        return row

    @staticmethod
    def _record(row: aiosqlite.Row) -> PublicationRecord:
        return PublicationRecord(**{key: row[key] for key in row.keys()})


class PublicationService:
    def __init__(self, workspace_root: Path, *, workspace_id: str, index_document: IndexDocument | None = None) -> None:
        self._root = workspace_root
        self._drafts = KnowledgeDraftService(workspace_root, workspace_id=workspace_id)
        self._repository = PublicationRepository(workspace_root)
        self._index_document = index_document or _index_document

    async def publish_approved_action(self, action: PendingActionRecord) -> PublicationRecord:
        if action.status not in {"approved", "edited_and_approved"}:
            raise ValueError("publication action must be approved")
        draft = await self._drafts.get(str(action.payload["draftId"]))
        if draft.version != action.payload["draftVersion"] or draft.content_hash != action.payload["contentHash"]:
            raise DraftVersionChangedError(f"draft {draft.id!r} changed before publication")
        definition = create_document_type_registry().resolve(draft.document_type)
        target_path = definition.path_for(draft.document_id)
        publication = await self._repository.prepare(action, draft, target_path)
        if publication.state == "completed":
            return publication

        document = PublishedDocument(
            id=draft.document_id, type=draft.document_type, title=draft.title, markdown=draft.markdown,
            source_refs=draft.source_refs, relation_refs=draft.relation_refs,
            published_at=action.resolved_at or action.created_at,
            provenance=PublishedProvenance(agent_type=draft.agent_type, session_id=draft.session_id, run_id=draft.run_id),
        )
        rendered = render_published_document(document)
        vault = initialize_vault(self._root)
        target = WorkspacePathPolicy(self._root).resolve_for_create("knowledge.active", target_path)

        if publication.state == "prepared":
            if target.exists():
                from hashlib import sha256
                expected_result = sha256(rendered.encode("utf-8")).hexdigest()
                if hash_file(target) != expected_result:
                    raise ExternalDocumentChangedError("published target changed externally")
                result_hash = expected_result
            else:
                result_hash = atomic_write_text(target, rendered, expected_existing_hash=None)
            publication = await self._repository.transition(publication.id, expected=("prepared",), target="file_written", result_hash=result_hash)

        if publication.result_hash is None or not target.exists() or hash_file(target) != publication.result_hash:
            raise ExternalDocumentChangedError("published target changed externally")
        await self._drafts.mark_published(draft.id, expected_version=draft.version, expected_hash=draft.content_hash)
        try:
            self._index_document(vault, document, rendered, target_path)
        except Exception:
            return await self._repository.transition(publication.id, expected=("file_written", "index_stale"), target="index_stale", error_code="publication_index_failed")
        publication = await self._repository.transition(publication.id, expected=("file_written", "index_stale"), target="indexed")
        return await self._repository.transition(publication.id, expected=("indexed",), target="completed")

    async def repair_index_stale_after_rescan(self) -> int:
        repaired = 0
        policy = WorkspacePathPolicy(self._root)
        for publication in await self._repository.list_by_state("index_stale"):
            try:
                target = policy.resolve_for_read("knowledge.active", publication.target_path)
            except Exception:
                continue
            if publication.result_hash is None or hash_file(target) != publication.result_hash:
                continue
            completed = await self._repository.transition(
                publication.id,
                expected=("index_stale",),
                target="completed",
            )
            if completed.state == "completed":
                repaired += 1
        return repaired

    async def latest_for_draft(
        self, draft_id: str
    ) -> PublicationRecord | None:
        return await self._repository.latest_for_draft(draft_id)


def _index_document(vault: Path, document: PublishedDocument, rendered: str, target_path: str) -> None:
    connection = connect_index(vault / ".cyber-interview-agent/index.sqlite")
    try:
        upsert_document(connection, IndexedDocument(id=document.id, path=target_path, title=document.title, type=document.type, status="ingested", body=rendered))
    finally:
        connection.close()
