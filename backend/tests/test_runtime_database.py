import sqlite3
from dataclasses import FrozenInstanceError

import pytest

from app.db.runtime_database import connect_runtime_database
from app.runtime.models import SessionRecord


def test_runtime_database_lives_outside_vault_and_enables_safety_pragmas(tmp_path):
    connection = connect_runtime_database(tmp_path)

    assert (tmp_path / ".cyber-interview-agent" / "runtime.sqlite").exists()
    assert not (
        tmp_path / "knowledge-vault" / ".cyber-interview-agent" / "runtime.sqlite"
    ).exists()
    assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA busy_timeout").fetchone()[0] >= 5_000


def test_runtime_migration_is_idempotent_and_creates_product_tables(tmp_path):
    first = connect_runtime_database(tmp_path)
    first.close()
    connection = connect_runtime_database(tmp_path)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "runtime_schema_migrations",
        "agent_sessions",
        "agent_messages",
        "agent_runs",
        "agent_events",
    } <= tables
    assert connection.execute(
        "SELECT COUNT(*) FROM runtime_schema_migrations"
    ).fetchone()[0] == 2


def test_runtime_database_rejects_invalid_session_status(tmp_path):
    connection = connect_runtime_database(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title, status) "
            "VALUES ('s1', 'w1', 'test.echo', 1, 'Echo', 'failed')"
        )


def test_runtime_records_are_immutable():
    record = SessionRecord(
        id="s1",
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Echo",
        status="active",
        parent_session_id=None,
        summary=None,
        created_at="2026-07-11T00:00:00Z",
        updated_at="2026-07-11T00:00:00Z",
        last_run_id=None,
    )

    with pytest.raises(FrozenInstanceError):
        record.title = "Changed"  # type: ignore[misc]
