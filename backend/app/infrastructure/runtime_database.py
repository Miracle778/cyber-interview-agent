from __future__ import annotations

import sqlite3
from pathlib import Path


CURRENT_GENERATION = 2
_SCHEMA_FILE = (
    Path(__file__).parents[1] / "db" / "migrations" / "runtime" / "001_current.sql"
)


class IncompatibleRuntimeDatabaseError(RuntimeError):
    pass


def runtime_database_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".cyber-interview-agent" / "runtime.sqlite"


def connect_runtime_database(workspace_root: Path) -> sqlite3.Connection:
    path = runtime_database_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        _ensure_current_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _ensure_current_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not tables:
        connection.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        return
    if "runtime_schema_metadata" not in tables:
        raise _incompatible()
    row = connection.execute(
        "SELECT generation FROM runtime_schema_metadata LIMIT 1"
    ).fetchone()
    if row is None or row[0] != CURRENT_GENERATION:
        raise _incompatible()


def _incompatible() -> IncompatibleRuntimeDatabaseError:
    return IncompatibleRuntimeDatabaseError(
        "旧版 Agent Runtime 数据库与当前不兼容；开发环境请删除 "
        ".cyber-interview-agent/runtime.sqlite 后重新启动。"
    )
