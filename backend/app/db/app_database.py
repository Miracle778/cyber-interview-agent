import sqlite3
import threading
from pathlib import Path
from typing import Any

from app.core.app_paths import resolve_app_data_dir


_MIGRATIONS_DIR = Path(__file__).parent / "migrations" / "app"


class ThreadLocalAppConnection:
    """Connection-compatible app database manager with one connection per thread."""

    def __init__(
        self, path: Path, initial_connection: sqlite3.Connection
    ) -> None:
        self._path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._closed = False
        self._connections: dict[int, sqlite3.Connection] = {
            id(initial_connection): initial_connection
        }
        self._local.connection = initial_connection

    def execute(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> sqlite3.Cursor:
        return self._current().execute(sql, parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        return self._current().executescript(sql_script)

    def commit(self) -> None:
        self._current().commit()

    def rollback(self) -> None:
        self._current().rollback()

    @property
    def in_transaction(self) -> bool:
        return self._current().in_transaction

    @property
    def row_factory(self):
        return self._current().row_factory

    @row_factory.setter
    def row_factory(self, value) -> None:
        self._current().row_factory = value

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = tuple(self._connections.values())
            self._connections.clear()
        for connection in connections:
            connection.close()
        self._local.connection = None

    def __getattr__(self, name: str):
        return getattr(self._current(), name)

    def _current(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        with self._lock:
            if self._closed:
                raise sqlite3.ProgrammingError("app database connection is closed")
        connection = _open_connection(self._path)
        with self._lock:
            if self._closed:
                connection.close()
                raise sqlite3.ProgrammingError("app database connection is closed")
            self._connections[id(connection)] = connection
        self._local.connection = connection
        return connection


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


def connect_app_database(data_dir: Path | None = None) -> ThreadLocalAppConnection:
    database_dir = Path(data_dir) if data_dir is not None else resolve_app_data_dir()
    database_dir.mkdir(parents=True, exist_ok=True)

    path = database_dir / "app.sqlite"
    connection = _open_connection(path, initialize_journal=True)
    _apply_migrations(connection)
    return ThreadLocalAppConnection(path, connection)


def _open_connection(
    path: Path, *, initialize_journal: bool = False
) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if initialize_journal:
        connection.execute("PRAGMA journal_mode = WAL")
    return connection
