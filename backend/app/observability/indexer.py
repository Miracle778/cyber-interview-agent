from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.diagnostics.agent_trace import initialize_agent_trace_directory
from app.observability.repository import TraceIndexRepository
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


_SYNTHETIC_NAMESPACE = UUID("af792a4c-b4fd-46d9-8115-d2f6f9340170")
_VALID_KINDS = frozenset({"execution", "agent", "model", "tool", "graph"})


@dataclass(frozen=True, slots=True)
class TraceSyncResult:
    indexed_events: int = 0
    malformed_rows: int = 0
    missing_files: int = 0


class TraceLedgerIndexer:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: TraceIndexRepository,
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.repository = repository

    def sync_workspace(self) -> TraceSyncResult:
        discovered = self._discover_trace_files()
        indexed_events = 0
        malformed_rows = 0
        for relative_path, path in discovered.items():
            inserted, malformed = self._sync_file(relative_path, path)
            indexed_events += inserted
            malformed_rows += malformed

        missing_files = 0
        for file_row in self.repository.list_files():
            relative_path = str(file_row["relative_path"])
            if relative_path in discovered:
                continue
            parsed = _parse_relative_path(relative_path)
            if parsed is None or file_row["health"] == "missing":
                continue
            session_id, run_id = parsed
            self.repository.mark_file_missing(
                relative_path=relative_path,
                session_id=session_id,
                run_id=run_id,
            )
            missing_files += 1
        return TraceSyncResult(
            indexed_events=indexed_events,
            malformed_rows=malformed_rows,
            missing_files=missing_files,
        )

    def rebuild_workspace(self) -> TraceSyncResult:
        self.repository.reset_index()
        return self.sync_workspace()

    def _discover_trace_files(self) -> dict[str, Path]:
        trace_root = initialize_agent_trace_directory(self.workspace_root)
        policy = WorkspacePathPolicy(self.workspace_root)
        policy.scope_root("diagnostics.agent_traces")
        discovered: dict[str, Path] = {}
        for session_path in trace_root.iterdir():
            try:
                session_mode = session_path.lstat().st_mode
            except OSError:
                continue
            if stat.S_ISLNK(session_mode) or not stat.S_ISDIR(session_mode):
                continue
            for candidate in session_path.iterdir():
                if candidate.suffix != ".jsonl":
                    continue
                relative_path = candidate.relative_to(trace_root).as_posix()
                try:
                    mode = candidate.lstat().st_mode
                    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                        continue
                    discovered[relative_path] = policy.resolve_for_read(
                        "diagnostics.agent_traces", relative_path
                    )
                except (OSError, PathPolicyError):
                    continue
        return discovered

    def _sync_file(self, relative_path: str, path: Path) -> tuple[int, int]:
        parsed = _parse_relative_path(relative_path)
        if parsed is None:
            return 0, 0
        session_id, run_id = parsed
        stat_result = path.stat()
        file_row = self.repository.get_file(relative_path)
        reset = bool(
            file_row is not None
            and stat_result.st_size < int(file_row["scanned_bytes"])
        )
        scanned_bytes = 0 if reset or file_row is None else int(file_row["scanned_bytes"])
        previous_sequence = (
            0 if reset or file_row is None else int(file_row["last_sequence"])
        )
        with path.open("rb") as stream:
            stream.seek(scanned_bytes)
            appended = stream.read()
        newline = appended.rfind(b"\n")
        completed = appended[: newline + 1] if newline >= 0 else b""
        has_trailer = len(completed) != len(appended)
        events: list[dict[str, Any]] = []
        operations: dict[str, dict[str, Any]] = {}
        offset = scanned_bytes
        malformed = 0
        last_sequence = previous_sequence

        root_operation_id = f"execution:{run_id}"
        operations[root_operation_id] = _operation(
            operation_id=root_operation_id,
            run_id=run_id,
            kind="execution",
            name=run_id,
        )

        for line_with_newline in completed.splitlines(keepends=True):
            raw_line = line_with_newline.rstrip(b"\r\n")
            byte_length = len(line_with_newline)
            if not raw_line:
                offset += byte_length
                continue
            try:
                row = json.loads(raw_line)
                normalized = self._normalize_row(
                    row,
                    session_id=session_id,
                    run_id=run_id,
                    relative_path=relative_path,
                    byte_start=offset,
                    byte_length=byte_length,
                    previous_sequence=last_sequence,
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                malformed += 1
                sequence = last_sequence + 1
                normalized = _gap_event(
                    workspace_id=self.workspace_id,
                    session_id=session_id,
                    run_id=run_id,
                    relative_path=relative_path,
                    byte_start=offset,
                    byte_length=byte_length,
                    raw_line=raw_line,
                    sequence=sequence,
                    root_operation_id=root_operation_id,
                )
            last_sequence = max(last_sequence, normalized["event"]["sequence"])
            for operation in normalized["operations"]:
                operations[operation["operation_id"]] = operation
            events.append(normalized["event"])
            offset += byte_length

        health = "partial" if has_trailer or malformed else "complete"
        inserted = self.repository.replace_file_index(
            relative_path=relative_path,
            workspace_id=self.workspace_id,
            session_id=session_id,
            run_id=run_id,
            file_size=stat_result.st_size,
            file_mtime_ns=stat_result.st_mtime_ns,
            scanned_bytes=scanned_bytes + len(completed),
            last_sequence=last_sequence,
            health=health,
            malformed_rows=malformed,
            operations=operations.values(),
            events=events,
            reset=reset,
        )
        return inserted, malformed

    def _normalize_row(
        self,
        row: object,
        *,
        session_id: str,
        run_id: str,
        relative_path: str,
        byte_start: int,
        byte_length: int,
        previous_sequence: int,
    ) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise TypeError("trace row must be an object")
        row_workspace = row.get("workspace_id")
        if row_workspace not in (None, "", self.workspace_id):
            raise ValueError("trace workspace mismatch")
        if row.get("session_id") not in (None, "", session_id):
            raise ValueError("trace session mismatch")
        if row.get("run_id") not in (None, "", run_id):
            raise ValueError("trace run mismatch")
        event_type = row.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("trace event type is missing")
        sequence_value = row.get("sequence")
        sequence = (
            sequence_value
            if isinstance(sequence_value, int) and sequence_value >= 0
            else previous_sequence + 1
        )
        schema_version = row.get("schema_version", 1)
        if not isinstance(schema_version, int) or schema_version < 1:
            raise ValueError("unsupported trace schema")
        operation_kind = _operation_kind(row, event_type)
        operation_id = _operation_id(row, run_id, operation_kind)
        parent_operation_id = _parent_operation_id(
            row, run_id, operation_kind
        )
        observed_at = row.get("timestamp")
        if observed_at is not None and not isinstance(observed_at, str):
            raise ValueError("invalid trace timestamp")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            event_id = _stable_id(
                "event",
                relative_path,
                str(byte_start),
                str(sequence),
            )
        payload = row.get("payload")
        payload_sha256 = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        status = _event_status(event_type)
        error_code = _error_code(payload) if status == "failed" else None
        agent_role = (
            row.get("agent_role")
            if isinstance(row.get("agent_role"), str)
            else None
        )
        name = next(
            (
                value
                for value in (
                    row.get("agent_name"),
                    row.get("agent_role"),
                    operation_kind,
                )
                if isinstance(value, str) and value
            ),
            operation_kind,
        )
        operations = [
            _operation(
                operation_id=f"execution:{run_id}",
                run_id=run_id,
                kind="execution",
                name=run_id,
            )
        ]
        if parent_operation_id and parent_operation_id != f"execution:{run_id}":
            operations.append(
                _operation(
                    operation_id=parent_operation_id,
                    run_id=run_id,
                    parent_operation_id=f"execution:{run_id}",
                    kind="agent",
                    name=agent_role or "agent",
                    agent_role=agent_role,
                    observed_at=observed_at,
                )
            )
        operations.append(
            _operation(
                operation_id=operation_id,
                run_id=run_id,
                parent_operation_id=parent_operation_id,
                kind=operation_kind,
                name=name,
                agent_role=agent_role,
                status=status,
                observed_at=observed_at,
                error_code=error_code,
                retry_count=1 if event_type.endswith(".retry") else 0,
            )
        )
        return {
            "operations": operations,
            "event": {
                "event_id": event_id,
                "run_id": run_id,
                "operation_id": operation_id,
                "event_type": event_type,
                "observed_at": observed_at,
                "relative_path": relative_path,
                "byte_start": byte_start,
                "byte_length": byte_length,
                "payload_sha256": payload_sha256,
                "sequence": sequence,
            },
        }


def _parse_relative_path(relative_path: str) -> tuple[str, str] | None:
    parts = Path(relative_path).parts
    if len(parts) != 2 or not parts[1].endswith(".jsonl"):
        return None
    session_id = parts[0]
    run_id = parts[1][: -len(".jsonl")]
    if not session_id or not run_id:
        return None
    return session_id, run_id


def _operation_kind(row: dict[str, Any], event_type: str) -> str:
    explicit = row.get("operation_kind")
    if explicit in _VALID_KINDS:
        return str(explicit)
    family = event_type.split(".", 1)[0]
    return family if family in {"model", "tool", "agent", "graph", "execution"} else "agent"


def _operation_id(row: dict[str, Any], run_id: str, kind: str) -> str:
    explicit = row.get("operation_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    invocation = row.get("invocation_id")
    return _stable_id(
        "operation",
        run_id,
        str(invocation) if invocation else "unknown",
        kind,
    )


def _parent_operation_id(
    row: dict[str, Any], run_id: str, kind: str
) -> str | None:
    explicit = row.get("parent_operation_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    if kind == "execution":
        return None
    if kind == "agent":
        return f"execution:{run_id}"
    role = row.get("agent_role")
    return _stable_id("agent", run_id, str(role) if role else "unknown")


def _event_status(event_type: str) -> str:
    if event_type.endswith(".error") or event_type.endswith(".failed"):
        return "failed"
    if event_type.endswith(".response") or event_type.endswith(".completed"):
        return "completed"
    return "running"


def _error_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("error_code", "code", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return None


def _operation(
    *,
    operation_id: str,
    run_id: str,
    kind: str,
    name: str,
    parent_operation_id: str | None = None,
    agent_role: str | None = None,
    status: str = "running",
    observed_at: str | None = None,
    error_code: str | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    terminal = status in {"completed", "failed"}
    return {
        "operation_id": operation_id,
        "run_id": run_id,
        "parent_operation_id": parent_operation_id,
        "kind": kind,
        "name": name,
        "agent_role": agent_role,
        "status": status,
        "started_at": None if terminal else observed_at,
        "finished_at": observed_at if terminal else None,
        "latency_ms": None,
        "retry_count": retry_count,
        "error_code": error_code,
    }


def _gap_event(
    *,
    workspace_id: str,
    session_id: str,
    run_id: str,
    relative_path: str,
    byte_start: int,
    byte_length: int,
    raw_line: bytes,
    sequence: int,
    root_operation_id: str,
) -> dict[str, Any]:
    del workspace_id, session_id
    digest = hashlib.sha256(raw_line).hexdigest()
    operation_id = _stable_id("gap-operation", run_id, str(byte_start))
    return {
        "operations": [
            _operation(
                operation_id=root_operation_id,
                run_id=run_id,
                kind="execution",
                name=run_id,
            ),
            _operation(
                operation_id=operation_id,
                run_id=run_id,
                parent_operation_id=root_operation_id,
                kind="agent",
                name="trace_index_gap",
                status="failed",
                error_code="trace_row_malformed",
            ),
        ],
        "event": {
            "event_id": _stable_id(
                "gap-event", relative_path, str(byte_start), digest
            ),
            "run_id": run_id,
            "operation_id": operation_id,
            "event_type": "trace.index_gap",
            "observed_at": None,
            "relative_path": relative_path,
            "byte_start": byte_start,
            "byte_length": byte_length,
            "payload_sha256": digest,
            "sequence": sequence,
        },
    }


def _stable_id(*parts: str) -> str:
    return str(uuid5(_SYNTHETIC_NAMESPACE, ":".join(parts)))


def _latency_ms(started_at: str | None, finished_at: str | None) -> int | None:
    if not started_at or not finished_at:
        return None
    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return max(int(delta.total_seconds() * 1000), 0)
