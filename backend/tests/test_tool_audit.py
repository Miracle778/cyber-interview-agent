from pathlib import Path

import pytest

from app.db.runtime_database import connect_runtime_database
from app.runtime.repository import RuntimeRepository
from app.tools.audit import ToolAuditRepository
from app.tools.context import ToolExecutionContext


def _context(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_id="w1",
        workspace_root=workspace,
        session_id="s1",
        run_id="r1",
        graph_id="test.files",
        graph_version=1,
        allowed_tools=frozenset({"read_source"}),
        allowed_scopes=frozenset({"review.sources"}),
    )


def _database(tmp_path: Path):
    connection = connect_runtime_database(tmp_path)
    runtime = RuntimeRepository(connection)
    runtime.create_session(
        workspace_id="w1",
        graph_id="test.files",
        graph_version=1,
        title="Files",
        session_id="s1",
    )
    runtime.create_run(
        "s1", input={}, model_bindings={}, run_id="r1", initial_status="running"
    )
    return connection


def test_runtime_migration_creates_tool_audit_table(tmp_path: Path) -> None:
    connection = connect_runtime_database(tmp_path)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    versions = connection.execute(
        "SELECT version FROM runtime_schema_migrations ORDER BY version"
    ).fetchall()

    assert "tool_audits" in tables
    assert [row[0] for row in versions] == [1, 2, 3, 4]
    connection.close()


@pytest.mark.asyncio
async def test_audit_repository_tracks_safe_lifecycle(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = ToolAuditRepository(tmp_path)

    started = await repository.start(
        _context(tmp_path),
        tool_name="read_source",
        resource_scope="review.sources",
        resource_path="notes.md",
    )
    completed = await repository.complete(
        started.id,
        latency_ms=7,
        resource_sha256="abc123",
    )

    assert started.status == "started"
    assert completed.status == "completed"
    assert completed.latency_ms == 7
    assert completed.resource_sha256 == "abc123"
    assert await repository.list_for_run("r1") == (completed,)
    connection.close()


@pytest.mark.asyncio
async def test_audit_repository_records_stable_failure_only(tmp_path: Path) -> None:
    connection = _database(tmp_path)
    repository = ToolAuditRepository(tmp_path)
    started = await repository.start(
        _context(tmp_path), tool_name="shell", resource_scope=None, resource_path=None
    )

    failed = await repository.fail(
        started.id, error_code="tool_not_allowed", latency_ms=1
    )

    assert failed.status == "failed"
    assert failed.error_code == "tool_not_allowed"
    assert "secret" not in str(failed)
    connection.close()
