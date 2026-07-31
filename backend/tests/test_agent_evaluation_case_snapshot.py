from __future__ import annotations

import sqlite3

import pytest

from app.evaluation.case_snapshot import (
    create_pre_execution_snapshot,
    create_restorable_case_snapshot,
    load_pre_execution_snapshot,
    restore_case_snapshot,
)
from app.infrastructure.runtime_database import connect_runtime_database


def test_case_snapshot_copies_database_and_artifacts_into_isolated_root(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connection = connect_runtime_database(workspace)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', 'review.discussion', 1, 'Test')"
    )
    connection.commit()
    artifact = workspace / "artifacts" / "review" / "sources" / "source.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("private source", encoding="utf-8")

    snapshot = create_restorable_case_snapshot(
        workspace_root=workspace,
        case_id="case-1",
        connection=connection,
    )
    sandbox = tmp_path / "sandbox"
    restore_case_snapshot(
        workspace_root=workspace,
        snapshot=snapshot,
        sandbox_root=sandbox,
    )

    restored = sqlite3.connect(
        sandbox / ".cyber-interview-agent" / "runtime.sqlite"
    )
    try:
        assert restored.execute(
            "SELECT title FROM agent_sessions WHERE id = 'session-1'"
        ).fetchone()[0] == "Test"
    finally:
        restored.close()
        connection.close()
    assert (sandbox / "artifacts/review/sources/source.md").read_text() == "private source"


def test_case_snapshot_rejects_tampering(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connection = connect_runtime_database(workspace)
    snapshot = create_restorable_case_snapshot(
        workspace_root=workspace,
        case_id="case-1",
        connection=connection,
    )
    connection.close()
    database = workspace / str(snapshot["artifactRef"]) / ".cyber-interview-agent/runtime.sqlite"
    database.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        restore_case_snapshot(
            workspace_root=workspace,
            snapshot=snapshot,
            sandbox_root=tmp_path / "sandbox",
        )


def test_pre_execution_snapshot_preserves_checkpoint_and_can_be_loaded(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connection = connect_runtime_database(workspace)
    checkpoint_path = workspace / ".cyber-interview-agent" / "checkpoints.sqlite"
    checkpoint_connection = sqlite3.connect(checkpoint_path)
    checkpoint_connection.execute("CREATE TABLE state (value TEXT NOT NULL)")
    checkpoint_connection.execute("INSERT INTO state VALUES ('before-run')")
    checkpoint_connection.commit()
    checkpoint_connection.close()

    created = create_pre_execution_snapshot(
        workspace_root=workspace,
        execution_id="execution-1",
        connection=connection,
    )
    loaded = load_pre_execution_snapshot(
        workspace_root=workspace,
        execution_id="execution-1",
    )
    sandbox = tmp_path / "sandbox"
    restore_case_snapshot(
        workspace_root=workspace,
        snapshot=loaded,
        sandbox_root=sandbox,
    )

    assert created["mode"] == "restorable"
    assert loaded["capturePoint"] == "before_graph_execution"
    restored_checkpoint = sqlite3.connect(
        sandbox / ".cyber-interview-agent" / "checkpoints.sqlite"
    )
    try:
        assert restored_checkpoint.execute("SELECT value FROM state").fetchone()[0] == "before-run"
    finally:
        restored_checkpoint.close()
        connection.close()
