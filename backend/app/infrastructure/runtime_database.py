from __future__ import annotations

import sqlite3
from pathlib import Path


CURRENT_SCHEMA_GENERATION = 2
_MIGRATIONS_DIR = Path(__file__).parents[1] / "db" / "migrations" / "runtime"
_SCHEMA_FILE = _MIGRATIONS_DIR / "001_current.sql"
_BASELINE_MIGRATION_VERSION = 1


class RuntimeDatabaseSchemaError(RuntimeError):
    pass


def runtime_database_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".cyber-interview-agent" / "runtime.sqlite"


def connect_runtime_database(workspace_root: Path) -> sqlite3.Connection:
    path = runtime_database_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = _open_connection(path)
    try:
        schema_state = _schema_state(connection)
        if schema_state == "replaceable_development":
            connection.close()
            _backup_development_database(path)
            connection = _open_connection(path)
            schema_state = "fresh"
        elif schema_state in {"generation_mismatch", "unrecognized"}:
            detail = (
                "开发期数据库 generation 与当前代码不一致"
                if schema_state == "generation_mismatch"
                else "检测到无法识别的开发期数据库结构"
            )
            raise RuntimeDatabaseSchemaError(
                f"{detail}；为避免误删，数据库已原样保留：{path}"
            )

        connection.execute("PRAGMA journal_mode = WAL")
        if schema_state == "fresh":
            connection.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        _apply_runtime_migrations(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _apply_runtime_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS runtime_schema_migrations ("
        "version INTEGER PRIMARY KEY CHECK (version > 0), "
        "name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO runtime_schema_migrations(version, name) "
        "VALUES (?, ?)",
        (_BASELINE_MIGRATION_VERSION, _SCHEMA_FILE.name),
    )
    connection.commit()

    applied = {
        int(row[0])
        for row in connection.execute(
            "SELECT version FROM runtime_schema_migrations"
        )
    }
    for migration in sorted(_MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(migration.name.split("_", 1)[0])
        if version <= _BASELINE_MIGRATION_VERSION or version in applied:
            continue
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            script = migration.read_text(encoding="utf-8")
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                f"{script}\n"
                "INSERT INTO runtime_schema_migrations(version, name) "
                f"VALUES ({version}, '{migration.name}');\n"
                "COMMIT;"
            )
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeDatabaseSchemaError(
            "runtime migration left foreign-key violations"
        )


def _open_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _schema_state(connection: sqlite3.Connection) -> str:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not tables:
        return "fresh"
    if "runtime_schema_metadata" in tables:
        row = connection.execute(
            "SELECT generation FROM runtime_schema_metadata LIMIT 1"
        ).fetchone()
        return (
            "current"
            if row is not None and row[0] == CURRENT_SCHEMA_GENERATION
            else "generation_mismatch"
        )
    if "runtime_schema_migrations" in tables:
        return "replaceable_development"
    return "unrecognized"


def _backup_development_database(path: Path) -> Path:
    backup = _available_backup_path(path)
    for source, suffix in (
        (path, ""),
        (Path(f"{path}-wal"), "-wal"),
        (Path(f"{path}-shm"), "-shm"),
    ):
        if source.exists():
            source.replace(Path(f"{backup}{suffix}"))
    return backup


def _available_backup_path(path: Path) -> Path:
    base = path.with_name("runtime.development-backup.sqlite")
    candidate = base
    sequence = 2
    while any(
        candidate_path.exists()
        for candidate_path in (
            candidate,
            Path(f"{candidate}-wal"),
            Path(f"{candidate}-shm"),
        )
    ):
        candidate = path.with_name(f"runtime.development-backup-{sequence}.sqlite")
        sequence += 1
    return candidate
