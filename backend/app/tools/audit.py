from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias
from uuid import uuid4

import aiosqlite

from app.db.runtime_database import runtime_database_path
from app.tools.context import ToolExecutionContext


ToolAuditStatus: TypeAlias = Literal["started", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    id: str
    session_id: str
    run_id: str
    tool_name: str
    status: ToolAuditStatus
    error_code: str | None
    latency_ms: int | None
    resource_scope: str | None
    resource_path: str | None
    resource_sha256: str | None
    created_at: str
    finished_at: str | None


class ToolAuditRepository:
    def __init__(self, workspace_root: Path) -> None:
        self._database_path = runtime_database_path(workspace_root)

    async def start(
        self,
        context: ToolExecutionContext,
        *,
        tool_name: str,
        resource_scope: str | None,
        resource_path: str | None,
    ) -> ToolAuditRecord:
        audit_id = str(uuid4())
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await connection.execute(
                    "INSERT INTO tool_audits "
                    "(id, session_id, run_id, tool_name, status, resource_scope, "
                    "resource_path) VALUES (?, ?, ?, ?, 'started', ?, ?)",
                    (
                        audit_id,
                        context.session_id,
                        context.run_id,
                        tool_name,
                        resource_scope,
                        resource_path,
                    ),
                )
                record = await self._require(connection, audit_id)
                await connection.commit()
                return record
            except Exception:
                await connection.rollback()
                raise

    async def complete(
        self,
        audit_id: str,
        *,
        latency_ms: int,
        resource_sha256: str | None,
    ) -> ToolAuditRecord:
        return await self._finish(
            audit_id,
            status="completed",
            error_code=None,
            latency_ms=latency_ms,
            resource_sha256=resource_sha256,
        )

    async def fail(
        self, audit_id: str, *, error_code: str, latency_ms: int
    ) -> ToolAuditRecord:
        return await self._finish(
            audit_id,
            status="failed",
            error_code=error_code,
            latency_ms=latency_ms,
            resource_sha256=None,
        )

    async def list_for_run(self, run_id: str) -> tuple[ToolAuditRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM tool_audits WHERE run_id = ? "
                "ORDER BY created_at, rowid",
                (run_id,),
            )
            rows = await cursor.fetchall()
        return tuple(self._from_row(row) for row in rows)

    async def _finish(
        self,
        audit_id: str,
        *,
        status: Literal["completed", "failed"],
        error_code: str | None,
        latency_ms: int,
        resource_sha256: str | None,
    ) -> ToolAuditRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "UPDATE tool_audits SET status = ?, error_code = ?, "
                    "latency_ms = ?, resource_sha256 = ?, "
                    "finished_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'started'",
                    (
                        status,
                        error_code,
                        latency_ms,
                        resource_sha256,
                        audit_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Tool audit is not in started state")
                record = await self._require(connection, audit_id)
                await connection.commit()
                return record
            except Exception:
                await connection.rollback()
                raise

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self._database_path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection

    @staticmethod
    async def _require(
        connection: aiosqlite.Connection, audit_id: str
    ) -> ToolAuditRecord:
        cursor = await connection.execute(
            "SELECT * FROM tool_audits WHERE id = ?", (audit_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Tool audit record not found")
        return ToolAuditRepository._from_row(row)

    @staticmethod
    def _from_row(row: aiosqlite.Row) -> ToolAuditRecord:
        return ToolAuditRecord(
            id=row["id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            tool_name=row["tool_name"],
            status=row["status"],
            error_code=row["error_code"],
            latency_ms=row["latency_ms"],
            resource_scope=row["resource_scope"],
            resource_path=row["resource_path"],
            resource_sha256=row["resource_sha256"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )
