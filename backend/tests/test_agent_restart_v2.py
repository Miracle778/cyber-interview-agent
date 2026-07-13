from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import (
    IncompatibleRuntimeDatabaseError,
    connect_runtime_database,
    runtime_database_path,
)
from app.application.session_service import ProductRepository
from app.application.workspace_runtime import AgentApplication


def test_fresh_runtime_database_has_current_generation(tmp_path: Path):
    connection = connect_runtime_database(tmp_path)
    try:
        generation = connection.execute(
            "SELECT generation FROM runtime_schema_metadata"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert generation == 2
    assert {"agent_sessions", "agent_runs", "agent_events", "pending_actions"} <= tables


def test_old_runtime_schema_is_rejected_with_development_reset_guidance(tmp_path: Path):
    path = runtime_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE runtime_schema_migrations(version INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    with pytest.raises(IncompatibleRuntimeDatabaseError) as raised:
        connect_runtime_database(tmp_path)

    assert "删除 .cyber-interview-agent/runtime.sqlite" in str(raised.value)


@pytest.mark.asyncio
async def test_recovery_marks_orphaned_running_execution_interrupted(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connection = connect_runtime_database(workspace)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="w1", kind="diagnostic.echo", title="Echo"
    )
    execution = repository.create_execution(
        session.id, input={"text": "hello"}, model_bindings={}
    )
    connection.close()

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=lambda *_args, **_kwargs: None,
    )
    try:
        assert await application.recover() == (execution.id,)
        detail = await application.session_detail(session.id)
        assert detail["latest_execution"]["status"] == "interrupted"
    finally:
        await application.close()
