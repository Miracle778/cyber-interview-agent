from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import aiosqlite

from app.db.runtime_database import runtime_database_path
from app.hitl.models import (
    CreatePendingAction,
    PendingActionRecord,
    ResolutionReceipt,
    ResolvedActionStatus,
)


class PendingActionError(RuntimeError):
    pass


class PendingActionNotFoundError(PendingActionError):
    pass


class ActionVersionConflictError(PendingActionError):
    pass


class ActionAlreadyResolvedError(PendingActionError):
    pass


class ActionIdempotencyConflictError(PendingActionError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class PendingActionRepository:
    def __init__(self, workspace_root: Path) -> None:
        self._database_path = runtime_database_path(workspace_root)

    async def create(self, request: CreatePendingAction) -> PendingActionRecord:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._find_by_idempotency_key(
                    connection, request.idempotency_key
                )
                if existing is not None:
                    self._ensure_same_create_request(existing, request)
                    await connection.commit()
                    return existing

                action_id = str(uuid4())
                await connection.execute(
                    "INSERT INTO pending_actions "
                    "(id, workspace_id, session_id, run_id, action_type, "
                    "payload_json, preview_json, editable_fields_json, "
                    "idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        action_id,
                        request.workspace_id,
                        request.session_id,
                        request.run_id,
                        request.action_type,
                        _canonical_json(request.payload),
                        _canonical_json(request.preview),
                        _canonical_json(request.editable_fields),
                        request.idempotency_key,
                    ),
                )
                record = await self._require_action(connection, action_id)
                await connection.commit()
                return record
            except Exception:
                await connection.rollback()
                raise

    async def get(self, action_id: str) -> PendingActionRecord:
        async with self._connection() as connection:
            return await self._require_action(connection, action_id)

    async def list_pending(
        self, workspace_id: str, *, session_id: str | None = None
    ) -> tuple[PendingActionRecord, ...]:
        query = (
            "SELECT * FROM pending_actions "
            "WHERE workspace_id = ? AND status = 'pending'"
        )
        parameters: list[str] = [workspace_id]
        if session_id is not None:
            query += " AND session_id = ?"
            parameters.append(session_id)
        query += " ORDER BY created_at, id"
        async with self._connection() as connection:
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
        return tuple(self._action_from_row(row) for row in rows)

    async def resolve(
        self,
        action_id: str,
        *,
        expected_version: int,
        status: ResolvedActionStatus,
        resolution_key: str,
        decision: dict[str, Any],
        resolved_payload: dict[str, Any] | None = None,
        resolved_preview: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> ResolutionReceipt:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._find_receipt_by_key(
                    connection, action_id, resolution_key
                )
                if existing is not None:
                    await connection.commit()
                    return existing

                action = await self._require_action(connection, action_id)
                if action.status != "pending":
                    raise ActionAlreadyResolvedError(
                        f"action {action_id!r} is already {action.status!r}"
                    )
                if action.version != expected_version:
                    raise ActionVersionConflictError(
                        f"action {action_id!r} expected version "
                        f"{expected_version}, got {action.version}"
                    )

                receipt_id = str(uuid4())
                next_payload = resolved_payload or action.payload
                next_preview = resolved_preview or action.preview
                cursor = await connection.execute(
                    "UPDATE pending_actions SET status = ?, version = version + 1, "
                    "payload_json = ?, preview_json = ?, "
                    "resolved_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'pending' AND version = ?",
                    (
                        status,
                        _canonical_json(next_payload),
                        _canonical_json(next_preview),
                        action_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ActionVersionConflictError(
                        f"action {action_id!r} changed during resolution"
                    )
                await connection.execute(
                    "INSERT INTO pending_action_resolutions "
                    "(id, action_id, resolution_key, status, decision_json, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        receipt_id,
                        action_id,
                        resolution_key,
                        status,
                        _canonical_json(decision),
                        reason,
                    ),
                )
                receipt = await self._require_receipt(connection, receipt_id)
                await connection.commit()
                return receipt
            except Exception:
                await connection.rollback()
                raise

    async def mark_delivering(self, receipt_id: str) -> ResolutionReceipt:
        claimed = await self.claim_delivery(receipt_id)
        if claimed is None:
            raise PendingActionError("resolution delivery is already in progress")
        return claimed

    async def claim_delivery(
        self, receipt_id: str
    ) -> ResolutionReceipt | None:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "UPDATE pending_action_resolutions "
                    "SET delivery_status = 'delivering', "
                    "delivery_attempts = delivery_attempts + 1, "
                    "delivery_error_code = NULL "
                    "WHERE id = ? AND delivery_status IN ('pending', 'failed')",
                    (receipt_id,),
                )
                receipt = await self._require_receipt(connection, receipt_id)
                await connection.commit()
                return receipt if cursor.rowcount == 1 else None
            except Exception:
                await connection.rollback()
                raise

    async def mark_delivered(self, receipt_id: str) -> ResolutionReceipt:
        return await self._update_delivery(
            receipt_id,
            "UPDATE pending_action_resolutions "
            "SET delivery_status = 'delivered', delivery_error_code = NULL, "
            "delivered_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND delivery_status != 'delivered'",
            allow_unchanged=True,
        )

    async def mark_delivery_failed(
        self, receipt_id: str, *, error_code: str
    ) -> ResolutionReceipt:
        return await self._update_delivery(
            receipt_id,
            "UPDATE pending_action_resolutions "
            "SET delivery_status = 'failed', delivery_error_code = ? "
            "WHERE id = ? AND delivery_status != 'delivered'",
            parameters=(error_code, receipt_id),
        )

    async def list_undelivered(self) -> tuple[ResolutionReceipt, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM pending_action_resolutions "
                "WHERE delivery_status != 'delivered' ORDER BY created_at, id"
            )
            rows = await cursor.fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    async def list_resolutions(
        self, action_id: str
    ) -> tuple[ResolutionReceipt, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM pending_action_resolutions "
                "WHERE action_id = ? ORDER BY created_at, id",
                (action_id,),
            )
            rows = await cursor.fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    async def cancel_pending_for_run(
        self, run_id: str
    ) -> PendingActionRecord | None:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT * FROM pending_actions "
                    "WHERE run_id = ? AND status = 'pending' "
                    "ORDER BY created_at, id LIMIT 1",
                    (run_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    await connection.commit()
                    return None
                action_id = cast(str, row["id"])
                await connection.execute(
                    "UPDATE pending_actions SET status = 'cancelled', "
                    "version = version + 1, resolved_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND status = 'pending'",
                    (action_id,),
                )
                action = await self._require_action(connection, action_id)
                await connection.commit()
                return action
            except Exception:
                await connection.rollback()
                raise

    async def _update_delivery(
        self,
        receipt_id: str,
        query: str,
        *,
        parameters: tuple[object, ...] | None = None,
        allow_unchanged: bool = False,
    ) -> ResolutionReceipt:
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    query, parameters or (receipt_id,)
                )
                if cursor.rowcount != 1 and not allow_unchanged:
                    await self._require_receipt(connection, receipt_id)
                    raise PendingActionError("resolution delivery is already complete")
                receipt = await self._require_receipt(connection, receipt_id)
                await connection.commit()
                return receipt
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
    async def _require_action(
        connection: aiosqlite.Connection, action_id: str
    ) -> PendingActionRecord:
        cursor = await connection.execute(
            "SELECT * FROM pending_actions WHERE id = ?", (action_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise PendingActionNotFoundError(f"action {action_id!r} not found")
        return PendingActionRepository._action_from_row(row)

    @staticmethod
    async def _find_by_idempotency_key(
        connection: aiosqlite.Connection, idempotency_key: str
    ) -> PendingActionRecord | None:
        cursor = await connection.execute(
            "SELECT * FROM pending_actions WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return None if row is None else PendingActionRepository._action_from_row(row)

    @staticmethod
    async def _require_receipt(
        connection: aiosqlite.Connection, receipt_id: str
    ) -> ResolutionReceipt:
        cursor = await connection.execute(
            "SELECT * FROM pending_action_resolutions WHERE id = ?", (receipt_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise PendingActionNotFoundError(f"receipt {receipt_id!r} not found")
        return PendingActionRepository._receipt_from_row(row)

    @staticmethod
    async def _find_receipt_by_key(
        connection: aiosqlite.Connection,
        action_id: str,
        resolution_key: str,
    ) -> ResolutionReceipt | None:
        cursor = await connection.execute(
            "SELECT * FROM pending_action_resolutions "
            "WHERE action_id = ? AND resolution_key = ?",
            (action_id, resolution_key),
        )
        row = await cursor.fetchone()
        return None if row is None else PendingActionRepository._receipt_from_row(row)

    @staticmethod
    def _ensure_same_create_request(
        existing: PendingActionRecord, request: CreatePendingAction
    ) -> None:
        comparable = (
            existing.workspace_id,
            existing.session_id,
            existing.run_id,
            existing.action_type,
            existing.payload,
            existing.preview,
            existing.editable_fields,
        )
        requested = (
            request.workspace_id,
            request.session_id,
            request.run_id,
            request.action_type,
            request.payload,
            request.preview,
            request.editable_fields,
        )
        if comparable != requested:
            raise ActionIdempotencyConflictError(
                "action idempotency key was reused with different content"
            )

    @staticmethod
    def _action_from_row(row: aiosqlite.Row) -> PendingActionRecord:
        return PendingActionRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            action_type=row["action_type"],
            payload=json.loads(row["payload_json"]),
            preview=json.loads(row["preview_json"]),
            editable_fields=tuple(json.loads(row["editable_fields_json"])),
            status=row["status"],
            version=row["version"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _receipt_from_row(row: aiosqlite.Row) -> ResolutionReceipt:
        return ResolutionReceipt(
            id=row["id"],
            action_id=row["action_id"],
            resolution_key=row["resolution_key"],
            status=row["status"],
            decision=json.loads(row["decision_json"]),
            reason=row["reason"],
            delivery_status=row["delivery_status"],
            delivery_attempts=row["delivery_attempts"],
            delivery_error_code=row["delivery_error_code"],
            created_at=row["created_at"],
            delivered_at=row["delivered_at"],
        )
