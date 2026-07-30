from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.infrastructure.file_descriptors import binary_open_flags
from app.observability.content_reader import TraceContentReader
from app.observability.repository import TraceIndexRepository
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


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


class TraceExportNotFoundError(LookupError):
    pass


class TraceExportConflictError(RuntimeError):
    pass


class TraceExportGenerationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TraceExportRecord:
    id: str
    workspace_id: str
    run_id: str
    status: str
    metadata_only: bool
    includes_bodies: bool
    artifact_sha256: str | None
    error_code: str | None
    created_at: str
    completed_at: str | None


class TraceExportService:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: TraceIndexRepository,
        content_reader: TraceContentReader,
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.repository = repository
        self.content_reader = content_reader

    def create(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        metadata_only: bool,
        include_stored_bodies: bool,
        execution: dict[str, Any],
        operations: list[dict[str, Any]],
        events: list[dict[str, Any]],
    ) -> TraceExportRecord:
        request_hash = _json_hash(
            {
                "runId": run_id,
                "metadataOnly": metadata_only,
                "includeStoredBodies": include_stored_bodies,
            }
        )
        existing = self.repository.get_export_by_idempotency_key(
            workspace_id=self.workspace_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise TraceExportConflictError(
                    "idempotency key already belongs to another export request"
                )
            return _record(existing)

        export_id = str(uuid4())
        self.repository.create_export(
            export_id=export_id,
            workspace_id=self.workspace_id,
            run_id=run_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            metadata_only=metadata_only,
            includes_bodies=include_stored_bodies,
        )
        relative_path = f"{export_id}.zip"
        temp_relative_path = f"{export_id}.tmp"
        export_root = _initialize_export_root(self.workspace_root)
        temp_path = export_root / temp_relative_path
        final_path = export_root / relative_path
        try:
            members = self._members(
                run_id=run_id,
                execution=execution,
                operations=operations,
                events=events,
                include_stored_bodies=include_stored_bodies,
            )
            self._write_archive(
                temp_path=temp_path,
                final_path=final_path,
                members=members,
                run_id=run_id,
                include_stored_bodies=include_stored_bodies,
            )
            artifact_hash = hashlib.sha256(final_path.read_bytes()).hexdigest()
            self.repository.complete_export(
                export_id=export_id,
                artifact_relative_path=relative_path,
                artifact_sha256=artifact_hash,
            )
        except Exception as error:
            for path in (temp_path, final_path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            self.repository.fail_export(
                export_id=export_id,
                error_code="trace_export_failed",
            )
            raise TraceExportGenerationError(
                "trace export generation failed"
            ) from error
        row = self.repository.get_export(export_id)
        if row is None:
            raise TraceExportGenerationError("trace export receipt is missing")
        return _record(row)

    def get(self, export_id: str) -> TraceExportRecord:
        row = self.repository.get_export(export_id)
        if row is None or row["workspace_id"] != self.workspace_id:
            raise TraceExportNotFoundError("trace export not found")
        return _record(row)

    def artifact(self, export_id: str) -> Path:
        row = self.repository.get_export(export_id)
        if (
            row is None
            or row["workspace_id"] != self.workspace_id
            or row["status"] != "completed"
            or not row["artifact_relative_path"]
        ):
            raise TraceExportNotFoundError("trace export not found")
        try:
            path = WorkspacePathPolicy(self.workspace_root).resolve_for_read(
                "diagnostics.agent_exports",
                row["artifact_relative_path"],
            )
        except PathPolicyError as error:
            raise TraceExportNotFoundError("trace export not found") from error
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["artifact_sha256"]:
            raise TraceExportNotFoundError("trace export not found")
        return path

    def _members(
        self,
        *,
        run_id: str,
        execution: dict[str, Any],
        operations: list[dict[str, Any]],
        events: list[dict[str, Any]],
        include_stored_bodies: bool,
    ) -> dict[str, bytes]:
        members = {
            "execution.json": _json_bytes(_redact(execution)),
            "operations.json": _json_bytes(_redact(operations)),
            "events.jsonl": b"".join(
                _json_bytes(
                    {
                        "eventId": event["event_id"],
                        "operationId": event["operation_id"],
                        "eventType": event["event_type"],
                        "observedAt": event["observed_at"],
                        "sequence": event["sequence"],
                        "payloadSha256": event["payload_sha256"],
                    },
                    newline=True,
                )
                for event in events
            ),
        }
        if not include_stored_bodies:
            return members
        for ordinal, event in enumerate(events, start=1):
            offset = 0
            chunks: list[str] = []
            while True:
                page = self.content_reader.read(
                    run_id=run_id,
                    event_id=event["event_id"],
                    offset=offset,
                    limit=64 * 1024,
                )
                chunks.append(page.content)
                if page.complete:
                    break
                if page.next_offset is None or page.next_offset <= offset:
                    raise TraceExportGenerationError(
                        "trace content pagination made no progress"
                    )
                offset = page.next_offset
            payload = json.loads("".join(chunks))
            filename = (
                f"bodies/{ordinal:06d}-"
                f"{hashlib.sha256(event['event_id'].encode()).hexdigest()[:12]}.json"
            )
            members[filename] = _json_bytes(_redact(payload))
        return members

    def _write_archive(
        self,
        *,
        temp_path: Path,
        final_path: Path,
        members: dict[str, bytes],
        run_id: str,
        include_stored_bodies: bool,
    ) -> None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        integrity = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sorted(members.items())
        }
        manifest = {
            "manifestVersion": 1,
            "traceSchemaVersions": [3],
            "generatedAt": generated_at,
            "workspaceId": self.workspace_id,
            "runId": run_id,
            "includedCategories": (
                ["metadata", "storedBodies"]
                if include_stored_bodies
                else ["metadata"]
            ),
            "excludedCategories": (
                [] if include_stored_bodies else ["storedBodies"]
            ),
            "redactionPolicy": (
                "Secrets are excluded at trace write time and filtered again "
                "while building this local diagnostic export."
            ),
            "integrity": integrity,
        }
        descriptor = _create_private_file(temp_path)
        try:
            with os.fdopen(descriptor, "w+b") as stream:
                with zipfile.ZipFile(
                    stream,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:
                    for name, content in sorted(members.items()):
                        _write_member(archive, name, content)
                    _write_member(
                        archive,
                        "manifest.json",
                        _json_bytes(manifest),
                    )
                stream.flush()
                os.fsync(stream.fileno())
            if final_path.exists() or final_path.is_symlink():
                raise TraceExportGenerationError(
                    "trace export artifact already exists"
                )
            os.replace(temp_path, final_path)
            os.chmod(final_path, 0o600)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise


def _initialize_export_root(workspace_root: Path) -> Path:
    root = workspace_root.resolve(strict=True)
    current = root
    for part in (".cyber-interview-agent", "diagnostic-exports"):
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise PathPolicyError("diagnostics.agent_exports")
        os.chmod(current, 0o700)
    WorkspacePathPolicy(workspace_root).scope_root(
        "diagnostics.agent_exports"
    )
    return current


def _create_private_file(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, binary_open_flags(flags), 0o600)


def _write_member(
    archive: zipfile.ZipFile,
    name: str,
    content: bytes,
) -> None:
    info = zipfile.ZipInfo(name)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + suffix
    ).encode("utf-8")


def _json_hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _record(row: dict[str, Any]) -> TraceExportRecord:
    return TraceExportRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        run_id=row["run_id"],
        status=row["status"],
        metadata_only=bool(row["metadata_only"]),
        includes_bodies=bool(row["includes_bodies"]),
        artifact_sha256=row["artifact_sha256"],
        error_code=row["error_code"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )
