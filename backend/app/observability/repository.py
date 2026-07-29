from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any


class TraceIndexRepository:
    """Metadata-only query index. JSONL remains the trace source of truth."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_file(self, relative_path: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_files WHERE relative_path = ?",
            (relative_path,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_files(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM agent_trace_files ORDER BY relative_path"
            )
        )

    def get_execution(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_executions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_operations(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.connection.execute(
                "SELECT operation.*, "
                "(SELECT COUNT(*) FROM agent_trace_events event "
                "WHERE event.operation_id = operation.operation_id) AS event_count "
                "FROM agent_trace_operations operation WHERE run_id = ? "
                "ORDER BY CASE kind WHEN 'execution' THEN 0 WHEN 'agent' THEN 1 "
                "ELSE 2 END, COALESCE(started_at, ''), operation_id",
                (run_id,),
            )
        )

    def list_events(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM agent_trace_events WHERE run_id = ? "
                "ORDER BY sequence, byte_start, event_id",
                (run_id,),
            )
        )

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_exports WHERE id = ?",
            (export_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_export_by_idempotency_key(
        self,
        *,
        workspace_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM agent_trace_exports "
            "WHERE workspace_id = ? AND idempotency_key = ?",
            (workspace_id, idempotency_key),
        ).fetchone()
        return dict(row) if row is not None else None

    def create_export(
        self,
        *,
        export_id: str,
        workspace_id: str,
        run_id: str,
        idempotency_key: str,
        request_hash: str,
        metadata_only: bool,
        includes_bodies: bool,
    ) -> None:
        self.connection.execute(
            "INSERT INTO agent_trace_exports "
            "(id, workspace_id, run_id, idempotency_key, request_hash, "
            "status, metadata_only, includes_bodies) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                export_id,
                workspace_id,
                run_id,
                idempotency_key,
                request_hash,
                int(metadata_only),
                int(includes_bodies),
            ),
        )
        self.connection.commit()

    def complete_export(
        self,
        *,
        export_id: str,
        artifact_relative_path: str,
        artifact_sha256: str,
    ) -> None:
        self.connection.execute(
            "UPDATE agent_trace_exports SET status = 'completed', "
            "artifact_relative_path = ?, artifact_sha256 = ?, "
            "completed_at = CURRENT_TIMESTAMP, error_code = NULL "
            "WHERE id = ? AND status = 'pending'",
            (artifact_relative_path, artifact_sha256, export_id),
        )
        self.connection.commit()

    def fail_export(self, *, export_id: str, error_code: str) -> None:
        self.connection.execute(
            "UPDATE agent_trace_exports SET status = 'failed', "
            "artifact_relative_path = NULL, artifact_sha256 = NULL, "
            "completed_at = CURRENT_TIMESTAMP, error_code = ? "
            "WHERE id = ? AND status = 'pending'",
            (error_code, export_id),
        )
        self.connection.commit()

    def replace_file_index(
        self,
        *,
        relative_path: str,
        workspace_id: str,
        session_id: str,
        run_id: str,
        file_size: int,
        file_mtime_ns: int,
        scanned_bytes: int,
        last_sequence: int,
        health: str,
        malformed_rows: int,
        operations: Iterable[dict[str, Any]],
        events: Iterable[dict[str, Any]],
        reset: bool,
    ) -> int:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if reset:
                self.connection.execute(
                    "DELETE FROM agent_trace_executions WHERE run_id = ?",
                    (run_id,),
                )
                self.connection.execute(
                    "DELETE FROM agent_trace_files WHERE relative_path = ?",
                    (relative_path,),
                )
            self.connection.execute(
                "INSERT INTO agent_trace_files "
                "(relative_path, scanned_bytes, last_sequence, file_size, "
                "file_mtime_ns, health, malformed_rows, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(relative_path) DO UPDATE SET "
                "scanned_bytes = excluded.scanned_bytes, "
                "last_sequence = MAX(agent_trace_files.last_sequence, excluded.last_sequence), "
                "file_size = excluded.file_size, "
                "file_mtime_ns = excluded.file_mtime_ns, "
                "health = excluded.health, "
                "malformed_rows = agent_trace_files.malformed_rows + excluded.malformed_rows, "
                "updated_at = CURRENT_TIMESTAMP",
                (
                    relative_path,
                    scanned_bytes,
                    last_sequence,
                    file_size,
                    file_mtime_ns,
                    health,
                    malformed_rows,
                ),
            )
            self.connection.execute(
                "INSERT INTO agent_trace_executions "
                "(run_id, workspace_id, session_id, trace_health, updated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "workspace_id = excluded.workspace_id, "
                "session_id = excluded.session_id, "
                "trace_health = excluded.trace_health, "
                "updated_at = CURRENT_TIMESTAMP",
                (run_id, workspace_id, session_id, health),
            )
            for operation in operations:
                self._upsert_operation(operation)
            inserted = 0
            for event in events:
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO agent_trace_events "
                    "(event_id, run_id, operation_id, event_type, observed_at, "
                    "relative_path, byte_start, byte_length, payload_sha256, sequence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event["event_id"],
                        event["run_id"],
                        event["operation_id"],
                        event["event_type"],
                        event["observed_at"],
                        relative_path,
                        event["byte_start"],
                        event["byte_length"],
                        event["payload_sha256"],
                        event["sequence"],
                    ),
                )
                inserted += max(cursor.rowcount, 0)
            self._refresh_execution(run_id, health)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return inserted

    def mark_file_missing(
        self, *, relative_path: str, session_id: str, run_id: str
    ) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                "UPDATE agent_trace_files SET health = 'missing', "
                "updated_at = CURRENT_TIMESTAMP WHERE relative_path = ?",
                (relative_path,),
            )
            self.connection.execute(
                "UPDATE agent_trace_executions SET trace_health = 'missing', "
                "updated_at = CURRENT_TIMESTAMP WHERE run_id = ? AND session_id = ?",
                (run_id, session_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def reset_index(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute("DELETE FROM agent_trace_events")
            self.connection.execute("DELETE FROM agent_trace_operations")
            self.connection.execute("DELETE FROM agent_trace_executions")
            self.connection.execute("DELETE FROM agent_trace_files")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _upsert_operation(self, operation: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO agent_trace_operations "
            "(operation_id, run_id, parent_operation_id, kind, name, agent_role, "
            "status, started_at, finished_at, latency_ms, retry_count, error_code) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(operation_id) DO UPDATE SET "
            "parent_operation_id = COALESCE(excluded.parent_operation_id, "
            "agent_trace_operations.parent_operation_id), "
            "kind = excluded.kind, "
            "name = excluded.name, "
            "agent_role = COALESCE(excluded.agent_role, agent_trace_operations.agent_role), "
            "status = CASE "
            "WHEN agent_trace_operations.status = 'failed' THEN 'failed' "
            "WHEN excluded.status IN ('failed', 'completed') THEN excluded.status "
            "ELSE agent_trace_operations.status END, "
            "started_at = CASE "
            "WHEN agent_trace_operations.started_at IS NULL THEN excluded.started_at "
            "WHEN excluded.started_at IS NULL THEN agent_trace_operations.started_at "
            "ELSE MIN(agent_trace_operations.started_at, excluded.started_at) END, "
            "finished_at = CASE "
            "WHEN excluded.finished_at IS NULL THEN agent_trace_operations.finished_at "
            "WHEN agent_trace_operations.finished_at IS NULL THEN excluded.finished_at "
            "ELSE MAX(agent_trace_operations.finished_at, excluded.finished_at) END, "
            "latency_ms = COALESCE(excluded.latency_ms, agent_trace_operations.latency_ms), "
            "retry_count = MAX(agent_trace_operations.retry_count, excluded.retry_count), "
            "error_code = COALESCE(excluded.error_code, agent_trace_operations.error_code)",
            (
                operation["operation_id"],
                operation["run_id"],
                operation["parent_operation_id"],
                operation["kind"],
                operation["name"],
                operation["agent_role"],
                operation["status"],
                operation["started_at"],
                operation["finished_at"],
                operation["latency_ms"],
                operation["retry_count"],
                operation["error_code"],
            ),
        )

    def _refresh_execution(self, run_id: str, health: str) -> None:
        self.connection.execute(
            "UPDATE agent_trace_executions SET "
            "first_event_at = (SELECT MIN(observed_at) FROM agent_trace_events "
            "WHERE run_id = ?), "
            "last_event_at = (SELECT MAX(observed_at) FROM agent_trace_events "
            "WHERE run_id = ?), "
            "indexed_event_count = (SELECT COUNT(*) FROM agent_trace_events "
            "WHERE run_id = ?), "
            "trace_health = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (run_id, run_id, run_id, health, run_id),
        )
