from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.observability.repository import TraceIndexRepository
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


MAX_TRACE_CONTENT_PAGE_BYTES = 64 * 1024


class TraceContentNotFoundError(LookupError):
    pass


class TraceContentUnavailableError(RuntimeError):
    pass


class InvalidTraceContentRangeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TraceContentPage:
    event_id: str
    event_type: str
    content: str
    content_encoding: str
    offset: int
    next_offset: int | None
    complete: bool
    sha256: str
    redactions_applied: bool
    reasoning: Any | None = None


class TraceContentReader:
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

    def read(
        self,
        *,
        run_id: str,
        event_id: str,
        offset: int,
        limit: int,
    ) -> TraceContentPage:
        if offset < 0 or not 1 <= limit <= MAX_TRACE_CONTENT_PAGE_BYTES:
            raise InvalidTraceContentRangeError("invalid trace content range")
        event = self.repository.get_event(event_id)
        if event is None or event["run_id"] != run_id:
            raise TraceContentNotFoundError("trace event not found")
        execution = self.repository.get_execution(run_id)
        if (
            execution is None
            or execution["workspace_id"] != self.workspace_id
        ):
            raise TraceContentNotFoundError("trace event not found")
        if event["event_type"] == "trace.index_gap":
            raise TraceContentUnavailableError("trace event body is malformed")
        if event.get("body_state", "available") != "available":
            raise TraceContentUnavailableError("trace event body was removed by retention")

        row = self._read_indexed_row(event)
        payload = row.get("payload")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload_hash = hashlib.sha256(canonical).hexdigest()
        if payload_hash != event["payload_sha256"]:
            raise TraceContentUnavailableError("trace event body changed")
        if offset > len(canonical) or not _is_utf8_boundary(canonical, offset):
            raise InvalidTraceContentRangeError("invalid trace content range")

        end = min(offset + limit, len(canonical))
        while end > offset:
            try:
                content = canonical[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            if end != len(canonical):
                raise InvalidTraceContentRangeError(
                    "trace content page cannot end on a UTF-8 boundary"
                )
            content = ""

        complete = end == len(canonical)
        reasoning = (
            payload.get("reasoning")
            if isinstance(payload, dict) and "reasoning" in payload
            else None
        )
        return TraceContentPage(
            event_id=event_id,
            event_type=event["event_type"],
            content=content,
            content_encoding="utf-8-json",
            offset=offset,
            next_offset=None if complete else end,
            complete=complete,
            sha256=payload_hash,
            redactions_applied=True,
            reasoning=reasoning,
        )

    def _read_indexed_row(self, event: dict[str, Any]) -> dict[str, Any]:
        try:
            path = WorkspacePathPolicy(self.workspace_root).resolve_for_read(
                "diagnostics.agent_traces",
                event["relative_path"],
            )
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            descriptor = os.open(path, flags)
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise TraceContentUnavailableError(
                        "trace event source is not a regular file"
                    )
                byte_start = int(event["byte_start"])
                byte_length = int(event["byte_length"])
                if (
                    byte_start < 0
                    or byte_length <= 0
                    or byte_start + byte_length > file_stat.st_size
                ):
                    raise TraceContentUnavailableError(
                        "trace event pointer is outside its source"
                    )
                os.lseek(descriptor, byte_start, os.SEEK_SET)
                chunks: list[bytes] = []
                remaining = byte_length
                while remaining:
                    chunk = os.read(descriptor, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                raw = b"".join(chunks)
            finally:
                os.close(descriptor)
        except (OSError, PathPolicyError, KeyError, TypeError, ValueError) as error:
            raise TraceContentUnavailableError(
                "trace event source is unavailable"
            ) from error

        if len(raw) != int(event["byte_length"]):
            raise TraceContentUnavailableError("trace event source is incomplete")
        try:
            row = json.loads(raw.rstrip(b"\r\n"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise TraceContentUnavailableError(
                "trace event body is malformed"
            ) from error
        if not isinstance(row, dict):
            raise TraceContentUnavailableError("trace event body is malformed")
        if (
            row.get("workspace_id") != self.workspace_id
            or row.get("run_id") != event["run_id"]
            or row.get("event_id") != event["event_id"]
            or row.get("event_type") != event["event_type"]
        ):
            raise TraceContentUnavailableError(
                "trace event identity no longer matches its index"
            )
        return row


def _is_utf8_boundary(content: bytes, offset: int) -> bool:
    try:
        content[:offset].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
