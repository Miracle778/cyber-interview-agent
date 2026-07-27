#!/usr/bin/env python3
"""Read-only database migration and schema consistency check.

The expected schema is built from the repository's migration files, so this
script does not need a second, manually maintained table/column inventory.

Run from the repository root:

    cd backend
    uv run python ../scripts/check_database_schema.py

To inspect an isolated environment or a specific workspace:

    uv run python ../scripts/check_database_schema.py \
      --app-data-dir /path/to/app-data \
      --workspace-root /path/to/workspace
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.app_paths import resolve_app_data_dir
from app.infrastructure.runtime_database import (
    CURRENT_SCHEMA_GENERATION,
    runtime_database_path,
)

APP_MIGRATIONS_DIR = BACKEND_ROOT / "app" / "db" / "migrations" / "app"
RUNTIME_MIGRATIONS_DIR = (
    BACKEND_ROOT / "app" / "db" / "migrations" / "runtime"
)


@dataclass(frozen=True, slots=True)
class DatabaseIssue:
    message: str


@dataclass(frozen=True, slots=True)
class DatabaseCheck:
    label: str
    path: Path
    table_count: int
    migration_count: int
    issues: tuple[DatabaseIssue, ...]

    @property
    def healthy(self) -> bool:
        return not self.issues


def migration_files(directory: Path) -> list[tuple[int, Path]]:
    return sorted(
        (
            int(path.name.split("_", 1)[0]),
            path,
        )
        for path in directory.glob("[0-9][0-9][0-9]_*.sql")
    )


def build_expected_app_schema() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    for _, migration in migration_files(APP_MIGRATIONS_DIR):
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def build_expected_runtime_schema() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = OFF")
    migrations = migration_files(RUNTIME_MIGRATIONS_DIR)
    if not migrations or migrations[0][0] != 1:
        raise RuntimeError("runtime baseline migration 001 is missing")

    connection.executescript(migrations[0][1].read_text(encoding="utf-8"))
    connection.execute(
        "CREATE TABLE runtime_schema_migrations ("
        "version INTEGER PRIMARY KEY CHECK (version > 0), "
        "name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    for _, migration in migrations[1:]:
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def schema_columns(connection: sqlite3.Connection) -> dict[str, set[str]]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    return {
        table: {
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")'
            )
        }
        for table in tables
    }


def open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
        timeout=2,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 2000")
    return connection


def check_database(
    *,
    label: str,
    path: Path,
    expected: sqlite3.Connection,
    migration_table: str,
    expected_migrations: set[int],
    runtime: bool = False,
) -> DatabaseCheck:
    issues: list[DatabaseIssue] = []
    connection = open_read_only(path)
    try:
        actual_schema = schema_columns(connection)
        expected_schema = schema_columns(expected)

        for table in sorted(expected_schema.keys() - actual_schema.keys()):
            issues.append(DatabaseIssue(f"缺少表：{table}"))
        for table in sorted(expected_schema.keys() & actual_schema.keys()):
            missing_columns = expected_schema[table] - actual_schema[table]
            for column in sorted(missing_columns):
                issues.append(DatabaseIssue(f"缺少字段：{table}.{column}"))

        if migration_table in actual_schema:
            applied = {
                int(row[0])
                for row in connection.execute(
                    f"SELECT version FROM {migration_table}"
                )
            }
            for version in sorted(expected_migrations - applied):
                issues.append(DatabaseIssue(f"缺少迁移记录：{version:03d}"))
            for version in sorted(applied - expected_migrations):
                issues.append(
                    DatabaseIssue(
                        f"数据库包含当前代码未知的迁移：{version:03d}"
                    )
                )

        if runtime and "runtime_schema_metadata" in actual_schema:
            row = connection.execute(
                "SELECT generation FROM runtime_schema_metadata LIMIT 1"
            ).fetchone()
            generation = None if row is None else int(row[0])
            if generation != CURRENT_SCHEMA_GENERATION:
                issues.append(
                    DatabaseIssue(
                        "runtime generation 不匹配："
                        f"数据库={generation}，代码={CURRENT_SCHEMA_GENERATION}"
                    )
                )

        violations = connection.execute("PRAGMA foreign_key_check").fetchmany(6)
        if violations:
            shown = "；".join(
                f"{row[0]} rowid={row[1]}" for row in violations[:5]
            )
            suffix = "；另有更多" if len(violations) > 5 else ""
            issues.append(DatabaseIssue(f"外键约束异常：{shown}{suffix}"))

        return DatabaseCheck(
            label=label,
            path=path,
            table_count=len(actual_schema),
            migration_count=len(expected_migrations),
            issues=tuple(issues),
        )
    finally:
        connection.close()


def active_workspaces(app_database: Path) -> list[tuple[str, Path]]:
    connection = open_read_only(app_database)
    try:
        columns = schema_columns(connection).get("workspaces", set())
        if not {"id", "root_path"}.issubset(columns):
            return []
        lifecycle_filter = (
            "AND lifecycle_status = 'active'"
            if "lifecycle_status" in columns
            else ""
        )
        rows = connection.execute(
            "SELECT id, root_path FROM workspaces "
            f"WHERE available = 1 {lifecycle_filter} ORDER BY created_at, id"
        ).fetchall()
        return [(str(row["id"]), Path(str(row["root_path"]))) for row in rows]
    finally:
        connection.close()


def print_check(check: DatabaseCheck) -> None:
    marker = "✓" if check.healthy else "✗"
    print(f"{marker} {check.label}")
    print(f"  {check.path}")
    if check.healthy:
        print(
            f"  结构完整：{check.table_count} 张表，"
            f"{check.migration_count} 个迁移版本"
        )
        return
    for issue in check.issues:
        print(f"  - {issue.message}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读检查 app.sqlite 和 Workspace runtime.sqlite 的迁移与结构"
    )
    parser.add_argument(
        "--app-data-dir",
        type=Path,
        help="包含 app.sqlite 的应用数据目录；默认使用当前环境配置",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        action="append",
        default=[],
        help="只检查指定 Workspace，可重复传入；默认检查全部活动 Workspace",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    app_data_dir = (
        args.app_data_dir.expanduser().resolve()
        if args.app_data_dir
        else resolve_app_data_dir()
    )
    app_database = app_data_dir / "app.sqlite"
    if not app_database.is_file():
        print(f"✗ 应用数据库不存在：{app_database}", file=sys.stderr)
        return 2

    expected_app = build_expected_app_schema()
    expected_runtime = build_expected_runtime_schema()
    try:
        app_versions = {
            version for version, _ in migration_files(APP_MIGRATIONS_DIR)
        }
        runtime_versions = {
            version for version, _ in migration_files(RUNTIME_MIGRATIONS_DIR)
        }
        try:
            app_check = check_database(
                label="应用配置数据库",
                path=app_database,
                expected=expected_app,
                migration_table="schema_migrations",
                expected_migrations=app_versions,
            )
        except sqlite3.Error as error:
            print(f"✗ 无法读取应用数据库：{error}", file=sys.stderr)
            return 2

        print("数据库结构检查\n")
        print_check(app_check)

        if args.workspace_root:
            workspaces = [
                (root.expanduser().resolve().name, root.expanduser().resolve())
                for root in args.workspace_root
            ]
        elif app_check.healthy:
            workspaces = active_workspaces(app_database)
        else:
            workspaces = []
            print("\n- 应用数据库结构异常，无法安全读取 Workspace 列表")

        failed = not app_check.healthy
        for workspace_id, root in workspaces:
            database = runtime_database_path(root)
            print()
            if not database.is_file():
                print(f"- Workspace {workspace_id} 尚未初始化 runtime.sqlite，跳过")
                print(f"  {database}")
                continue
            try:
                check = check_database(
                    label=f"Workspace {workspace_id}",
                    path=database,
                    expected=expected_runtime,
                    migration_table="runtime_schema_migrations",
                    expected_migrations=runtime_versions,
                    runtime=True,
                )
            except sqlite3.Error as error:
                failed = True
                print(f"✗ Workspace {workspace_id} 无法读取：{error}")
                print(f"  {database}")
                continue
            print_check(check)
            failed = failed or not check.healthy

        print()
        if failed:
            print("结论：数据库迁移不完整，请先修复 migration 后再使用相关功能。")
            return 1
        print("结论：已检查的数据库结构完整。")
        return 0
    finally:
        expected_app.close()
        expected_runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
