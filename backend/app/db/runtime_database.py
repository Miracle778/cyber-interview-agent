import sqlite3
from pathlib import Path


_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "runtime"


def _migration_files() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in _MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"):
        migrations.append((int(path.name.split("_", 1)[0]), path))
    return sorted(migrations)


def _apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    applied = {
        row["version"]
        for row in connection.execute(
            "SELECT version FROM runtime_schema_migrations"
        )
    }
    for version, path in _migration_files():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            "INSERT INTO runtime_schema_migrations(version, applied_at) "
            f"VALUES ({version}, CURRENT_TIMESTAMP);\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


def runtime_database_path(workspace_root: Path) -> Path:
    return Path(workspace_root) / ".cyber-interview-agent" / "runtime.sqlite"


def connect_runtime_database(workspace_root: Path) -> sqlite3.Connection:
    database_path = runtime_database_path(workspace_root)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    _apply_migrations(connection)
    return connection
