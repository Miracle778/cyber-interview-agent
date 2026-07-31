from __future__ import annotations

import json
import os
import re
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Literal, TypeAlias
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.infrastructure.file_descriptors import binary_open_flags
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


TraceEventType = Literal[
    "execution.started",
    "execution.completed",
    "execution.failed",
    "model.request",
    "model.response",
    "model.error",
    "tool.request",
    "tool.response",
    "tool.error",
]
TraceOperationKind = Literal["execution", "agent", "model", "tool", "graph"]
JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]

_TRACE_SCOPE = "diagnostics.agent_traces"
_TRACE_OPERATION_NAMESPACE = UUID("bed60f89-5eaa-46a5-b6f8-c946ef7adbf8")
_LOCAL_TIMEZONE_NAME = "Asia/Shanghai"
_LOCAL_TIMEZONE = ZoneInfo(_LOCAL_TIMEZONE_NAME)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "headers",
        "secret",
        "secret_ref",
        "access_token",
        "refresh_token",
        "id_token",
        "client",
        "credentials",
    }
)
_MESSAGE_FIELDS = (
    "type",
    "content",
    "name",
    "id",
    "tool_call_id",
    "tool_calls",
    "invalid_tool_calls",
    "response_metadata",
    "usage_metadata",
)


@dataclass(frozen=True, slots=True)
class TraceIdentity:
    workspace_id: str
    workspace_root: Path
    session_id: str
    run_id: str
    agent_role: str
    agent_name: str
    invocation_id: str
    operation_id: str | None = None
    parent_operation_id: str | None = None
    operation_kind: TraceOperationKind | None = None


def stable_trace_operation_id(*parts: str) -> str:
    return str(uuid5(_TRACE_OPERATION_NAMESPACE, ":".join(parts)))


def _operation_coordinates(
    identity: TraceIdentity,
    event_type: TraceEventType,
) -> tuple[str, str | None, TraceOperationKind]:
    event_family = event_type.split(".", 1)[0]
    kind: TraceOperationKind = identity.operation_kind or (
        event_family if event_family in {"execution", "model", "tool"} else "agent"
    )
    operation_id = identity.operation_id
    parent_operation_id = identity.parent_operation_id
    if operation_id is None:
        if kind == "execution":
            operation_id = f"execution:{identity.run_id}"
        else:
            operation_id = stable_trace_operation_id(
                identity.run_id,
                identity.invocation_id,
                kind,
            )
    if parent_operation_id is None and kind != "execution":
        if kind in {"model", "tool", "graph"}:
            parent_operation_id = stable_trace_operation_id(
                identity.run_id,
                identity.agent_role,
                identity.agent_name,
                "agent",
            )
        else:
            parent_operation_id = f"execution:{identity.run_id}"
    return operation_id, parent_operation_id, kind


def _safe_key(key: object) -> str:
    return key if isinstance(key, str) else f"<{type(key).__name__}>"


def _is_secret_key(key: str) -> bool:
    return key.lower() in _SECRET_KEYS and key != "content"


def _safe_message(message: BaseMessage) -> dict[str, JSONValue]:
    return {
        field: safe_trace_value(getattr(message, field))
        for field in _MESSAGE_FIELDS
        if getattr(message, field, None) is not None
    }


def safe_trace_value(value: object) -> JSONValue:
    """Convert known diagnostic values without invoking arbitrary ``repr``."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseMessage):
        return _safe_message(value)
    if isinstance(value, ModelResponse):
        return {
            "result": safe_trace_value(value.result),
            "structured_response": safe_trace_value(value.structured_response),
        }
    if isinstance(value, BaseModel):
        return safe_trace_value(value.model_dump(mode="json"))
    if isinstance(value, (list, tuple)):
        return [safe_trace_value(item) for item in value]
    if isinstance(value, dict):
        return {
            safe_key: safe_trace_value(item)
            for key, item in value.items()
            if not _is_secret_key(safe_key := _safe_key(key))
        }
    return {"type": type(value).__name__, "unserializable": True}


def _raise_denied(relative_path: str | None = None) -> None:
    raise PathPolicyError(_TRACE_SCOPE, relative_path)


def _require_directory(path: Path, *, relative_path: str | None = None) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise PathPolicyError(_TRACE_SCOPE, relative_path) from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        _raise_denied(relative_path)


def _mkdir_private(path: Path, *, relative_path: str | None = None) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise PathPolicyError(_TRACE_SCOPE, relative_path) from error
    _require_directory(path, relative_path=relative_path)
    try:
        os.chmod(path, 0o700)
    except OSError as error:
        raise PathPolicyError(_TRACE_SCOPE, relative_path) from error


def initialize_agent_trace_directory(workspace_root: Path) -> Path:
    """Create the dedicated trace root without following any path symlinks."""
    policy = WorkspacePathPolicy(workspace_root)
    root = policy.workspace_root
    dot_directory = root / ".cyber-interview-agent"
    _mkdir_private(dot_directory)
    trace_root = dot_directory / "agent-traces"
    _mkdir_private(trace_root)
    return trace_root


class AgentTraceWriter:
    _locks: ClassVar[dict[Path, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _lock_for(cls, path: Path) -> threading.Lock:
        with cls._locks_guard:
            return cls._locks.setdefault(path, threading.Lock())

    @staticmethod
    def _validate_identifier(value: str) -> None:
        if not _IDENTIFIER.fullmatch(value):
            _raise_denied(value)

    def _trace_path(self, identity: TraceIdentity) -> Path:
        self._validate_identifier(identity.session_id)
        self._validate_identifier(identity.run_id)
        trace_root = initialize_agent_trace_directory(identity.workspace_root)
        session_directory = trace_root / identity.session_id
        _mkdir_private(session_directory, relative_path=identity.session_id)
        # A final policy resolution verifies the dedicated scope remains inside root.
        WorkspacePathPolicy(identity.workspace_root).scope_root(_TRACE_SCOPE)
        return session_directory / f"{identity.run_id}.jsonl"

    @staticmethod
    def _last_complete_sequence(path: Path) -> int:
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return 0
        if not content.endswith(b"\n"):
            content = content.rsplit(b"\n", 1)[0] if b"\n" in content else b""
        last_sequence = 0
        for line in content.splitlines():
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict) and isinstance(row.get("sequence"), int):
                last_sequence = max(last_sequence, row["sequence"])
        return last_sequence

    @staticmethod
    def _discard_incomplete_trailer(path: Path) -> None:
        """Discard only a crash-torn final row before appending a new row."""
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return
        if content.endswith(b"\n"):
            return
        cutoff = content.rfind(b"\n") + 1
        with path.open("r+b") as stream:
            stream.truncate(cutoff)

    def append(
        self,
        identity: TraceIdentity,
        event_type: TraceEventType,
        payload: object,
        *,
        terminal: bool = False,
    ) -> bool:
        try:
            path = self._trace_path(identity)
        except PathPolicyError:
            raise
        except OSError:
            return False

        lock = self._lock_for(path)
        try:
            with lock:
                self._discard_incomplete_trailer(path)
                sequence = self._last_complete_sequence(path) + 1
                observed_at = datetime.now(timezone.utc)
                operation_id, parent_operation_id, operation_kind = _operation_coordinates(
                    identity,
                    event_type,
                )
                row = {
                    "schema_version": 3,
                    "timestamp": observed_at.isoformat(timespec="milliseconds"),
                    "local_timestamp": observed_at.astimezone(_LOCAL_TIMEZONE).isoformat(timespec="milliseconds"),
                    "timezone": _LOCAL_TIMEZONE_NAME,
                    "sequence": sequence,
                    "event_id": str(uuid4()),
                    "workspace_id": identity.workspace_id,
                    "session_id": identity.session_id,
                    "run_id": identity.run_id,
                    "agent_role": identity.agent_role,
                    "agent_name": identity.agent_name,
                    "invocation_id": identity.invocation_id,
                    "operation_id": operation_id,
                    "parent_operation_id": parent_operation_id,
                    "operation_kind": operation_kind,
                    "event_type": event_type,
                    "payload": safe_trace_value(payload),
                }
                encoded = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(path, binary_open_flags(flags), 0o600)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise OSError("agent trace target is not a regular file")
                    fchmod = getattr(os, "fchmod", None)
                    if fchmod is not None:
                        fchmod(descriptor, 0o600)
                    remaining = memoryview(encoded)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("agent trace append made no progress")
                        remaining = remaining[written:]
                    if terminal:
                        os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError:
            return False
        return True


def read_trace_rows(workspace_root: Path, session_id: str, run_id: str) -> list[dict[str, Any]]:
    """Parse only completed JSONL rows; intended for focused tests and diagnostics."""
    writer = AgentTraceWriter()
    probe = TraceIdentity("", workspace_root, session_id, run_id, "", "", "")
    path = writer._trace_path(probe)
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return []
    if not content.endswith(b"\n"):
        content = content.rsplit(b"\n", 1)[0] if b"\n" in content else b""
    return [json.loads(line) for line in content.splitlines() if line]
