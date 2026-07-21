from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeAlias
from uuid import uuid4

import aiosqlite

from app.infrastructure.runtime_database import connect_runtime_database, runtime_database_path
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.security.workspace_paths import WorkspacePathPolicy


DocumentType: TypeAlias = Literal[
    "source", "question", "concept", "session_report", "mastery_report"
]
DraftStatus: TypeAlias = Literal[
    "draft", "review_pending", "rejected", "published", "superseded"
]
_DOCUMENT_TYPES = frozenset(
    {"source", "question", "concept", "session_report", "mastery_report"}
)
_EDITABLE_STATUSES = frozenset({"draft", "review_pending", "rejected"})


class KnowledgeDraftError(RuntimeError):
    pass


class DraftNotFoundError(KnowledgeDraftError):
    pass


class DraftVersionChangedError(KnowledgeDraftError):
    pass


class DraftContentChangedError(KnowledgeDraftError):
    pass


class DraftNotEditableError(KnowledgeDraftError):
    pass


@dataclass(frozen=True, slots=True)
class CreateDraftCommand:
    domain: str
    document_type: DocumentType
    title: str
    markdown: str
    source_refs: tuple[str, ...]
    relation_refs: tuple[str, ...]
    session_id: str | None = None
    run_id: str | None = None
    agent_type: str | None = None
    draft_id: str | None = None
    document_id: str | None = None

    def __post_init__(self) -> None:
        if self.domain != "review":
            raise ValueError("unsupported draft domain")
        if self.document_type not in _DOCUMENT_TYPES:
            raise ValueError("unsupported document type")
        if not self.title.strip():
            raise ValueError("draft title must not be empty")
        if not self.markdown.strip():
            raise ValueError("draft markdown must not be empty")


@dataclass(frozen=True, slots=True)
class UpdateDraftCommand:
    expected_version: int
    markdown: str | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        if self.expected_version < 1:
            raise ValueError("expected_version must be positive")
        if self.markdown is None and self.title is None:
            raise ValueError("draft update must change title or markdown")
        if self.markdown is not None and not self.markdown.strip():
            raise ValueError("draft markdown must not be empty")
        if self.title is not None and not self.title.strip():
            raise ValueError("draft title must not be empty")


@dataclass(frozen=True, slots=True)
class KnowledgeDraftRecord:
    id: str
    workspace_id: str
    session_id: str | None
    run_id: str | None
    agent_type: str | None
    domain: str
    document_type: DocumentType
    document_id: str
    title: str
    markdown: str
    content_path: str
    source_refs: tuple[str, ...]
    relation_refs: tuple[str, ...]
    status: DraftStatus
    version: int
    content_hash: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class StagedDraftRecord:
    id: str
    workspace_id: str
    session_id: str | None
    run_id: str | None
    agent_type: str | None
    domain: str
    document_type: DocumentType
    document_id: str
    title: str
    markdown: str
    content_path: str
    source_refs: tuple[str, ...]
    relation_refs: tuple[str, ...]
    content_hash: str


def stage_draft(
    workspace_root: Path,
    *,
    workspace_id: str,
    command: CreateDraftCommand,
) -> StagedDraftRecord:
    """Write deterministic draft content without creating a formal DB row."""
    if command.draft_id is None or command.document_id is None:
        raise ValueError("staged drafts require stable draft and document ids")
    initialize_knowledge_artifacts(workspace_root, domain=command.domain)
    filename = f"{command.draft_id}.md"
    content_path = f"artifacts/{command.domain}/drafts/{filename}"
    digest = _hash_text(command.markdown)
    policy = WorkspacePathPolicy(workspace_root)
    target = policy.resolve_for_create("review.drafts", filename)
    if target.exists():
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise DraftContentChangedError(
                f"staged draft {command.draft_id!r} content changed"
            )
    else:
        _atomic_write(
            workspace_root,
            filename,
            command.markdown,
            expected_hash=None,
        )
    return StagedDraftRecord(
        id=command.draft_id,
        workspace_id=workspace_id,
        session_id=command.session_id,
        run_id=command.run_id,
        agent_type=command.agent_type,
        domain=command.domain,
        document_type=command.document_type,
        document_id=command.document_id,
        title=command.title.strip(),
        markdown=command.markdown,
        content_path=content_path,
        source_refs=command.source_refs,
        relation_refs=command.relation_refs,
        content_hash=digest,
    )


class KnowledgeDraftService:
    def __init__(self, workspace_root: Path, *, workspace_id: str) -> None:
        if not workspace_id.strip():
            raise ValueError("workspace_id must not be empty")
        self._workspace_root = workspace_root
        self._workspace_id = workspace_id
        self._database_path = runtime_database_path(workspace_root)
        connect_runtime_database(workspace_root).close()

    async def stage_curation_draft(
        self, batch_id: str, command: CreateDraftCommand
    ) -> StagedDraftRecord:
        if (
            command.draft_id is None
            or command.document_id is None
            or command.run_id is None
        ):
            raise ValueError(
                "curation staging requires stable draft, document, and execution ids"
            )
        staged = StagedDraftRecord(
            id=command.draft_id,
            workspace_id=self._workspace_id,
            session_id=command.session_id,
            run_id=command.run_id,
            agent_type=command.agent_type,
            domain=command.domain,
            document_type=command.document_type,
            document_id=command.document_id,
            title=command.title.strip(),
            markdown=command.markdown,
            content_path=(
                f"artifacts/{command.domain}/drafts/{command.draft_id}.md"
            ),
            source_refs=command.source_refs,
            relation_refs=command.relation_refs,
            content_hash=_hash_text(command.markdown),
        )
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                owner = await connection.execute(
                    "SELECT f.state, f.execution_id, b.run_id, b.status, "
                    "b.control_intent, c.session_id AS curation_session_id, "
                    "c.active_batch_id "
                    "FROM review_curation_finalizations f "
                    "JOIN review_question_batches b ON b.id = f.batch_id "
                    "LEFT JOIN review_curation_sessions c "
                    "ON c.session_id = b.session_id "
                    "WHERE f.batch_id = ?",
                    (batch_id,),
                )
                row = await owner.fetchone()
                if (
                    row is None
                    or row["state"] != "preparing"
                    or row["execution_id"] != command.run_id
                    or row["run_id"] != command.run_id
                    or row["status"] != "generating"
                    or row["control_intent"] is not None
                    or (
                        row["curation_session_id"] is not None
                        and row["active_batch_id"] != batch_id
                    )
                ):
                    raise DraftNotEditableError(
                        "curation finalization no longer owns staging"
                    )
                existing_cursor = await connection.execute(
                    "SELECT * FROM review_curation_staged_drafts "
                    "WHERE draft_id = ?",
                    (staged.id,),
                )
                existing = await existing_cursor.fetchone()
                expected = (
                    batch_id,
                    command.run_id,
                    staged.content_path,
                    staged.content_hash,
                )
                if existing is None:
                    await connection.execute(
                        "INSERT INTO review_curation_staged_drafts "
                        "(draft_id, batch_id, execution_id, content_path, "
                        "content_hash) VALUES (?, ?, ?, ?, ?)",
                        (staged.id, *expected),
                    )
                elif tuple(
                    existing[key]
                    for key in (
                        "batch_id",
                        "execution_id",
                        "content_path",
                        "content_hash",
                    )
                ) != expected:
                    raise DraftContentChangedError(
                        f"staged draft {staged.id!r} identity changed"
                    )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        try:
            return stage_draft(
                self._workspace_root,
                workspace_id=self._workspace_id,
                command=command,
            )
        except Exception:
            async with self._connection() as connection:
                await connection.execute(
                    "DELETE FROM review_curation_staged_drafts "
                    "WHERE draft_id = ? AND batch_id = ? "
                    "AND execution_id = ?",
                    (staged.id, batch_id, command.run_id),
                )
                await connection.commit()
            raise

    def validate_curation_artifact(
        self, draft_id: str, content_path: str, content_hash: str
    ) -> None:
        expected_path = f"artifacts/review/drafts/{draft_id}.md"
        if content_path != expected_path:
            raise DraftContentChangedError(
                f"staged draft {draft_id!r} path changed"
            )
        path = WorkspacePathPolicy(self._workspace_root).resolve_for_create(
            "review.drafts", f"{draft_id}.md"
        )
        if not path.is_file():
            raise DraftContentChangedError(
                f"staged draft {draft_id!r} artifact is missing"
            )
        if sha256(path.read_bytes()).hexdigest() != content_hash:
            raise DraftContentChangedError(
                f"staged draft {draft_id!r} artifact hash changed"
            )

    async def cleanup_curation_staging(
        self, *, batch_id: str, execution_id: str
    ) -> int:
        removed = 0
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT * FROM review_curation_staged_drafts "
                    "WHERE batch_id = ? AND execution_id = ? "
                    "ORDER BY created_at, draft_id",
                    (batch_id, execution_id),
                )
                rows = await cursor.fetchall()
                policy = WorkspacePathPolicy(self._workspace_root)
                for row in rows:
                    formal_cursor = await connection.execute(
                        "SELECT 1 FROM knowledge_drafts "
                        "WHERE id = ? OR content_path = ? LIMIT 1",
                        (row["draft_id"], row["content_path"]),
                    )
                    if await formal_cursor.fetchone() is not None:
                        await connection.execute(
                            "DELETE FROM review_curation_staged_drafts "
                            "WHERE draft_id = ?",
                            (row["draft_id"],),
                        )
                        continue
                    expected_path = (
                        f"artifacts/review/drafts/{row['draft_id']}.md"
                    )
                    if row["content_path"] != expected_path:
                        continue
                    path = policy.resolve_for_create(
                        "review.drafts", f"{row['draft_id']}.md"
                    )
                    if not path.exists():
                        await connection.execute(
                            "DELETE FROM review_curation_staged_drafts "
                            "WHERE draft_id = ?",
                            (row["draft_id"],),
                        )
                        continue
                    if sha256(path.read_bytes()).hexdigest() != row["content_hash"]:
                        continue
                    path.unlink()
                    removed += 1
                    await connection.execute(
                        "DELETE FROM review_curation_staged_drafts "
                        "WHERE draft_id = ?",
                        (row["draft_id"],),
                    )
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return removed

    async def reconcile_curation_staging(self) -> int:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT DISTINCT staged.batch_id, staged.execution_id "
                "FROM review_curation_staged_drafts staged "
                "LEFT JOIN review_curation_finalizations f "
                "ON f.batch_id = staged.batch_id "
                "LEFT JOIN review_question_batches b ON b.id = staged.batch_id "
                "LEFT JOIN review_curation_sessions c ON c.session_id = b.session_id "
                "LEFT JOIN agent_runs run ON run.id = staged.execution_id "
                "LEFT JOIN knowledge_drafts draft "
                "ON draft.id = staged.draft_id "
                "OR draft.content_path = staged.content_path "
                "WHERE draft.id IS NULL AND (f.batch_id IS NULL "
                "OR f.state != 'preparing' "
                "OR f.execution_id != staged.execution_id "
                "OR b.run_id != staged.execution_id "
                "OR b.status != 'generating' "
                "OR b.control_intent IS NOT NULL "
                "OR run.id IS NULL "
                "OR run.status NOT IN ('queued', 'running') "
                "OR (c.session_id IS NOT NULL "
                "AND c.active_batch_id != b.id))"
            )
            owners = await cursor.fetchall()
        removed = 0
        for owner in owners:
            removed += await self.cleanup_curation_staging(
                batch_id=str(owner["batch_id"]),
                execution_id=str(owner["execution_id"]),
            )
        return removed

    async def create(self, command: CreateDraftCommand) -> KnowledgeDraftRecord:
        initialize_knowledge_artifacts(
            self._workspace_root, domain=command.domain
        )
        draft_id = command.draft_id or str(uuid4())
        document_id = command.document_id or (
            f"{command.document_type}_{uuid4().hex}"
        )
        filename = f"{draft_id}.md"
        content_path = f"artifacts/{command.domain}/drafts/{filename}"
        digest = _hash_text(command.markdown)

        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            target: Path | None = None
            try:
                target = _atomic_write(
                    self._workspace_root,
                    filename,
                    command.markdown,
                    expected_hash=None,
                )
                await connection.execute(
                    "INSERT INTO knowledge_drafts "
                    "(id, workspace_id, session_id, run_id, agent_type, domain, "
                    "document_type, document_id, title, content_path, "
                    "source_refs_json, relation_refs_json, content_hash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        draft_id,
                        self._workspace_id,
                        command.session_id,
                        command.run_id,
                        command.agent_type,
                        command.domain,
                        command.document_type,
                        document_id,
                        command.title.strip(),
                        content_path,
                        _canonical_json(command.source_refs),
                        _canonical_json(command.relation_refs),
                        digest,
                    ),
                )
                row = await self._require_row(connection, draft_id)
                await connection.commit()
            except Exception:
                await connection.rollback()
                if target is not None and target.exists():
                    target.unlink()
                raise
        return self._record_from_row(row)

    async def get(self, draft_id: str) -> KnowledgeDraftRecord:
        async with self._connection() as connection:
            row = await self._require_row(connection, draft_id)
        return self._record_from_row(row)

    async def list(self) -> tuple[KnowledgeDraftRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM knowledge_drafts WHERE workspace_id = ? "
                "ORDER BY created_at, rowid",
                (self._workspace_id,),
            )
            rows = await cursor.fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    async def update(
        self, draft_id: str, command: UpdateDraftCommand
    ) -> KnowledgeDraftRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                row = await self._require_row(connection, draft_id)
                current = self._record_from_row(row)
                if current.version != command.expected_version:
                    raise DraftVersionChangedError(
                        f"draft {draft_id!r} expected version "
                        f"{command.expected_version}, got {current.version}"
                    )
                if current.status not in _EDITABLE_STATUSES:
                    raise DraftNotEditableError(
                        f"draft {draft_id!r} is {current.status!r}"
                    )
                if await self._has_active_publication(connection, current):
                    raise DraftNotEditableError(
                        f"draft {draft_id!r} has an active publication claim"
                    )

                markdown = command.markdown or current.markdown
                title = (command.title or current.title).strip()
                filename = Path(current.content_path).name
                _atomic_write(
                    self._workspace_root,
                    filename,
                    markdown,
                    expected_hash=current.content_hash,
                )
                digest = _hash_text(markdown)
                cursor = await connection.execute(
                    "UPDATE knowledge_drafts SET title = ?, content_hash = ?, "
                    "status = CASE WHEN status = 'rejected' "
                    "THEN 'review_pending' ELSE status END, "
                    "version = version + 1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND workspace_id = ? AND version = ? "
                    "AND content_hash = ?",
                    (
                        title,
                        digest,
                        draft_id,
                        self._workspace_id,
                        command.expected_version,
                        current.content_hash,
                    ),
                )
                if cursor.rowcount != 1:
                    _atomic_write(
                        self._workspace_root,
                        filename,
                        current.markdown,
                        expected_hash=digest,
                    )
                    raise DraftVersionChangedError(
                        f"draft {draft_id!r} changed during update"
                    )
                updated_row = await self._require_row(connection, draft_id)
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return self._record_from_row(updated_row)

    async def mark_published(
        self, draft_id: str, *, expected_version: int, expected_hash: str
    ) -> KnowledgeDraftRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            row = await self._require_row(connection, draft_id)
            current = self._record_from_row(row)
            if (
                current.version != expected_version
                or current.content_hash != expected_hash
            ):
                await connection.rollback()
                raise DraftVersionChangedError(
                    f"draft {draft_id!r} changed before publication"
                )
            if current.status != "published":
                await connection.execute(
                    "UPDATE knowledge_drafts SET status = 'published', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (draft_id,),
                )
            published_row = await self._require_row(connection, draft_id)
            await connection.commit()
        return self._record_from_row(published_row)

    async def mark_review_pending(
        self, draft_id: str, *, expected_version: int, expected_hash: str
    ) -> KnowledgeDraftRecord:
        return await self._set_status(
            draft_id,
            expected_version=expected_version,
            expected_hash=expected_hash,
            target_status="review_pending",
            allowed_statuses=("draft", "review_pending"),
        )

    async def mark_rejected(
        self, draft_id: str, *, expected_version: int, expected_hash: str
    ) -> KnowledgeDraftRecord:
        return await self._set_status(
            draft_id,
            expected_version=expected_version,
            expected_hash=expected_hash,
            target_status="rejected",
            allowed_statuses=("draft", "review_pending", "rejected"),
        )

    async def _set_status(
        self,
        draft_id: str,
        *,
        expected_version: int,
        expected_hash: str,
        target_status: DraftStatus,
        allowed_statuses: tuple[DraftStatus, ...],
    ) -> KnowledgeDraftRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                row = await self._require_row(connection, draft_id)
                current = self._record_from_row(row)
                if (
                    current.version != expected_version
                    or current.content_hash != expected_hash
                ):
                    raise DraftVersionChangedError(
                        f"draft {draft_id!r} changed before status transition"
                    )
                if current.status not in allowed_statuses:
                    raise DraftNotEditableError(
                        f"draft {draft_id!r} cannot transition from "
                        f"{current.status!r} to {target_status!r}"
                    )
                if await self._has_active_publication(connection, current):
                    raise DraftNotEditableError(
                        f"draft {draft_id!r} has an active publication claim"
                    )
                if current.status != target_status:
                    await connection.execute(
                        "UPDATE knowledge_drafts SET status = ?, "
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (target_status, draft_id),
                    )
                updated = await self._require_row(connection, draft_id)
                await connection.commit()
            except Exception:
                await connection.rollback()
                raise
        return self._record_from_row(updated)

    @staticmethod
    async def _has_active_publication(
        connection: aiosqlite.Connection, draft: KnowledgeDraftRecord
    ) -> bool:
        cursor = await connection.execute(
            "SELECT 1 FROM publication_runs WHERE draft_id = ? "
            "AND expected_draft_version = ? AND expected_content_hash = ? "
            "AND state IN ('prepared', 'file_written', 'indexed', 'index_stale') "
            "LIMIT 1",
            (draft.id, draft.version, draft.content_hash),
        )
        return await cursor.fetchone() is not None

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection

    async def _require_row(
        self, connection: aiosqlite.Connection, draft_id: str
    ) -> aiosqlite.Row:
        cursor = await connection.execute(
            "SELECT * FROM knowledge_drafts WHERE id = ? AND workspace_id = ?",
            (draft_id, self._workspace_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise DraftNotFoundError(f"draft {draft_id!r} not found")
        return row

    def _record_from_row(self, row: aiosqlite.Row) -> KnowledgeDraftRecord:
        content_path = row["content_path"]
        filename = Path(content_path).name
        policy = WorkspacePathPolicy(self._workspace_root)
        path = policy.resolve_for_read("review.drafts", filename)
        body = path.read_bytes()
        digest = sha256(body).hexdigest()
        if digest != row["content_hash"]:
            raise DraftContentChangedError(
                f"draft {row['id']!r} content changed outside the service"
            )
        return KnowledgeDraftRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            agent_type=row["agent_type"],
            domain=row["domain"],
            document_type=row["document_type"],
            document_id=row["document_id"],
            title=row["title"],
            markdown=body.decode("utf-8"),
            content_path=content_path,
            source_refs=tuple(json.loads(row["source_refs_json"])),
            relation_refs=tuple(json.loads(row["relation_refs_json"])),
            status=row["status"],
            version=row["version"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _canonical_json(value: tuple[str, ...]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _atomic_write(
    workspace_root: Path,
    filename: str,
    markdown: str,
    *,
    expected_hash: str | None,
) -> Path:
    policy = WorkspacePathPolicy(workspace_root)
    target = policy.resolve_for_create("review.drafts", filename)
    if target.exists():
        current_hash = sha256(target.read_bytes()).hexdigest()
        if expected_hash is None or current_hash != expected_hash:
            raise DraftContentChangedError("draft content hash changed")

    temp_name = f".{filename}.{uuid4().hex}.tmp"
    temp = policy.resolve_for_create("review.drafts", temp_name)
    encoded = markdown.encode("utf-8")
    try:
        with temp.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        target = policy.resolve_for_create("review.drafts", filename)
        if target.exists():
            current_hash = sha256(target.read_bytes()).hexdigest()
            if expected_hash is None or current_hash != expected_hash:
                raise DraftContentChangedError("draft content hash changed")
        os.replace(temp, target)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()
    return target
