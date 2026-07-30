from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from app.diagnostics.agent_trace import AgentTraceWriter, TraceIdentity
from app.infrastructure.runtime_database import connect_runtime_database
from app.observability.indexer import TraceLedgerIndexer
from app.observability.repository import TraceIndexRepository
from app.observability.service import (
    AdvancedDiagnosticsDisabledError,
    AgentObservabilityService,
    TraceExportConflictError,
    TraceExportGenerationError,
    TraceExportNotFoundError,
)
from app.observability.export_service import _create_private_file


def _service(
    root: Path,
    *,
    workspace_id: str = "workspace-1",
    advanced_enabled: bool = True,
) -> tuple[AgentObservabilityService, object]:
    connection = connect_runtime_database(root)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', ?, 'review.round', 1, '复习')",
        (workspace_id,),
    )
    connection.execute(
        "INSERT INTO agent_runs "
        "(id, session_id, status, input_json, model_bindings_json, "
        "configuration_json) "
        "VALUES ('run-1', 'session-1', 'completed', '{}', '{}', '{}')"
    )
    connection.commit()
    AgentTraceWriter().append(
        TraceIdentity(
            workspace_id=workspace_id,
            workspace_root=root,
            session_id="session-1",
            run_id="run-1",
            agent_role="answer_evaluation",
            agent_name="review_answer_evaluation",
            invocation_id="invocation-1",
        ),
        "model.request",
        {
            "messages": ["private answer"],
            "api_key": "sk-must-not-export",
        },
    )
    repository = TraceIndexRepository(connection)
    indexer = TraceLedgerIndexer(
        workspace_id=workspace_id,
        workspace_root=root,
        repository=repository,
    )
    indexer.sync_workspace()
    return (
        AgentObservabilityService(
            workspace_id=workspace_id,
            workspace_root=root,
            connection=connection,
            trace_repository=repository,
            indexer=indexer,
            advanced_diagnostics_enabled=lambda: advanced_enabled,
        ),
        connection,
    )


def test_trace_export_is_idempotent_and_manifest_is_immutable(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    try:
        first = service.create_export(
            "run-1",
            idempotency_key="export-key-001",
            metadata_only=True,
            include_stored_bodies=False,
        )
        repeated = service.create_export(
            "run-1",
            idempotency_key="export-key-001",
            metadata_only=True,
            include_stored_bodies=False,
        )
        path = service.get_export_artifact(first.id)
        before = path.read_bytes()
        loaded = service.get_export(first.id)
        after = path.read_bytes()
    finally:
        connection.close()

    assert repeated.id == first.id
    assert repeated.artifact_sha256 == first.artifact_sha256
    assert loaded.id == first.id
    assert before == after
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "execution.json",
            "operations.json",
            "events.jsonl",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["workspaceId"] == "workspace-1"
        assert manifest["runId"] == "run-1"
        assert manifest["includedCategories"] == ["metadata"]
        assert manifest["excludedCategories"] == ["storedBodies"]
        assert manifest["integrity"]["execution.json"]


def test_trace_export_same_key_with_different_request_conflicts(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path)
    try:
        service.create_export(
            "run-1",
            idempotency_key="export-key-002",
            metadata_only=True,
            include_stored_bodies=False,
        )
        with pytest.raises(TraceExportConflictError):
            service.create_export(
                "run-1",
                idempotency_key="export-key-002",
                metadata_only=False,
                include_stored_bodies=True,
            )
    finally:
        connection.close()


def test_private_export_file_uses_binary_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "export.tmp"
    binary_flag = 1 << 29
    real_open = os.open
    observed_flags: list[int] = []

    monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)

    def tracked_open(open_path, flags, mode=0o777):
        observed_flags.append(flags)
        return real_open(open_path, flags & ~binary_flag, mode)

    monkeypatch.setattr(os, "open", tracked_open)

    descriptor = _create_private_file(path)
    os.close(descriptor)

    assert observed_flags[-1] & binary_flag


def test_trace_export_with_bodies_requires_advanced_mode(
    tmp_path: Path,
) -> None:
    service, connection = _service(tmp_path, advanced_enabled=False)
    try:
        with pytest.raises(AdvancedDiagnosticsDisabledError):
            service.create_export(
                "run-1",
                idempotency_key="export-key-003",
                metadata_only=False,
                include_stored_bodies=True,
            )
    finally:
        connection.close()


def test_trace_export_body_bundle_has_no_secret_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "pread", raising=False)
    service, connection = _service(tmp_path)
    try:
        export = service.create_export(
            "run-1",
            idempotency_key="export-key-004",
            metadata_only=False,
            include_stored_bodies=True,
        )
        path = service.get_export_artifact(export.id)
        content = path.read_bytes()
    finally:
        connection.close()

    assert b"sk-must-not-export" not in content
    with zipfile.ZipFile(path) as archive:
        body_name = next(
            name for name in archive.namelist() if name.startswith("bodies/")
        )
        body = json.loads(archive.read(body_name))
        assert body["messages"] == ["private answer"]
        assert "api_key" not in body


def test_trace_export_is_workspace_scoped(tmp_path: Path) -> None:
    service, connection = _service(tmp_path)
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_service, other_connection = _service(
        other_root,
        workspace_id="workspace-2",
    )
    try:
        export = service.create_export(
            "run-1",
            idempotency_key="export-key-005",
            metadata_only=True,
            include_stored_bodies=False,
        )
        with pytest.raises(TraceExportNotFoundError):
            other_service.get_export(export.id)
    finally:
        connection.close()
        other_connection.close()


def test_trace_export_failure_removes_partial_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    service, connection = _service(tmp_path)

    class BrokenArchive:
        def __init__(self, *_args, **_kwargs):
            raise OSError("synthetic archive failure")

    monkeypatch.setattr(
        "app.observability.export_service.zipfile.ZipFile",
        BrokenArchive,
    )
    try:
        with pytest.raises(TraceExportGenerationError):
            service.create_export(
                "run-1",
                idempotency_key="export-key-006",
                metadata_only=True,
                include_stored_bodies=False,
            )
        export_root = tmp_path / ".cyber-interview-agent" / "diagnostic-exports"
        assert not list(export_root.glob("*.tmp"))
        receipt = connection.execute(
            "SELECT status, error_code, artifact_relative_path "
            "FROM agent_trace_exports WHERE idempotency_key = ?",
            ("export-key-006",),
        ).fetchone()
    finally:
        connection.close()

    assert dict(receipt) == {
        "status": "failed",
        "error_code": "trace_export_failed",
        "artifact_relative_path": None,
    }
