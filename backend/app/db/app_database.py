import sqlite3
from pathlib import Path

from app.core.app_paths import resolve_app_data_dir


_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "app"


def _migration_files() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in _MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"):
        migrations.append((int(path.name.split("_", 1)[0]), path))
    return sorted(migrations)


def _apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()

    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, path in _migration_files():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            "INSERT INTO schema_migrations(version, applied_at) "
            f"VALUES ({version}, CURRENT_TIMESTAMP);\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise


def connect_app_database(data_dir: Path | None = None) -> sqlite3.Connection:
    database_dir = Path(data_dir) if data_dir is not None else resolve_app_data_dir()
    database_dir.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        database_dir / "app.sqlite",
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    _apply_migrations(connection)
    return connection
