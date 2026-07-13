from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.infrastructure.runtime_database import (
    RuntimeDatabaseSchemaError,
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


def test_replaceable_development_schema_is_backed_up_and_rebuilt(tmp_path: Path):
    path = runtime_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE runtime_schema_migrations(version INTEGER PRIMARY KEY)")
    connection.execute("INSERT INTO runtime_schema_migrations(version) VALUES (1)")
    connection.commit()
    connection.close()

    connection = connect_runtime_database(tmp_path)
    try:
        generation = connection.execute(
            "SELECT generation FROM runtime_schema_metadata"
        ).fetchone()[0]
    finally:
        connection.close()

    backup = path.with_name("runtime.development-backup.sqlite")
    backup_connection = sqlite3.connect(backup)
    try:
        backed_up_version = backup_connection.execute(
            "SELECT version FROM runtime_schema_migrations"
        ).fetchone()[0]
    finally:
        backup_connection.close()

    assert generation == 2
    assert backed_up_version == 1


def test_unrecognized_development_schema_is_preserved_with_neutral_error(tmp_path: Path):
    path = runtime_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE important_test_data(value TEXT)")
    connection.execute("INSERT INTO important_test_data(value) VALUES ('keep-me')")
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeDatabaseSchemaError) as raised:
        connect_runtime_database(tmp_path)

    assert "无法识别的开发期数据库结构" in str(raised.value)
    assert "旧版" not in str(raised.value)
    preserved_connection = sqlite3.connect(path)
    try:
        preserved = preserved_connection.execute(
            "SELECT value FROM important_test_data"
        ).fetchone()[0]
    finally:
        preserved_connection.close()
    assert preserved == "keep-me"


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
