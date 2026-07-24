#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infrastructure.runtime_database import runtime_database_path
from app.profile.storage import MaterialStorage

_ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "waiting_for_input",
    "waiting_for_approval",
)


class ProfileResetRefused(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProfileResetPlan:
    workspace_id: str
    table_counts: dict[str, int]
    session_ids: tuple[str, ...]
    material_refs: tuple[str, ...]
    preserved_counts: dict[str, int]


def open_runtime_database(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    migration = connection.execute(
        "SELECT 1 FROM runtime_schema_migrations WHERE version = 29"
    ).fetchone()
    if migration is None:
        connection.close()
        raise ProfileResetRefused("runtime database has not applied migration 029")
    return connection


def validate_paths(database: Path, workspace_root: Path) -> tuple[Path, Path]:
    if not database.is_absolute() or not workspace_root.is_absolute():
        raise ProfileResetRefused("database and workspace root must be absolute paths")
    resolved_database = database.resolve()
    resolved_root = workspace_root.resolve()
    if resolved_database != runtime_database_path(resolved_root).resolve():
        raise ProfileResetRefused(
            "database does not belong to the supplied workspace root"
        )
    if not resolved_database.is_file():
        raise ProfileResetRefused(f"runtime database does not exist: {resolved_database}")
    return resolved_database, resolved_root


def build_reset_plan(
    connection: sqlite3.Connection, workspace_id: str
) -> ProfileResetPlan:
    if not workspace_id.strip():
        raise ProfileResetRefused("workspace id is required")

    material_rows = connection.execute(
        "SELECT id FROM profile_materials WHERE workspace_id = ?",
        (workspace_id,),
    ).fetchall()
    material_ids = tuple(row["id"] for row in material_rows)
    version_rows = _rows_for_ids(
        connection,
        "SELECT id, storage_ref, text_ref FROM profile_material_versions "
        "WHERE material_id IN ({}) ORDER BY id",
        material_ids,
    )
    version_ids = tuple(row["id"] for row in version_rows)
    refs = tuple(
        sorted(
            {
                ref
                for row in version_rows
                for ref in (row["storage_ref"], row["text_ref"])
                if ref
            }
        )
    )

    profile_sessions = connection.execute(
        "SELECT id FROM agent_sessions "
        "WHERE workspace_id = ? AND graph_id = 'profile.manage'",
        (workspace_id,),
    ).fetchall()
    session_ids = {row["id"] for row in profile_sessions}
    if version_ids:
        placeholders = ",".join("?" for _ in version_ids)
        ingest_sessions = connection.execute(
            "SELECT id FROM agent_sessions "
            f"WHERE workspace_id = ? AND visibility = 'system' "
            f"AND id IN ({placeholders})",
            (workspace_id, *version_ids),
        ).fetchall()
        session_ids.update(row["id"] for row in ingest_sessions)

    table_counts = {
        "profile_materials": _count_where(
            connection, "profile_materials", "workspace_id = ?", (workspace_id,)
        ),
        "profile_material_versions": len(version_ids),
        "profile_evidence": _count_for_ids(
            connection, "profile_evidence", "material_version_id", version_ids
        ),
        "profile_claims": _count_where(
            connection, "profile_claims", "workspace_id = ?", (workspace_id,)
        ),
        "profile_claim_proposals": _count_where(
            connection,
            "profile_claim_proposals",
            "workspace_id = ?",
            (workspace_id,),
        ),
        "profile_assessments": _count_where(
            connection, "profile_assessments", "workspace_id = ?", (workspace_id,)
        ),
        "profile_action_plans": _count_where(
            connection, "profile_action_plans", "workspace_id = ?", (workspace_id,)
        ),
        "profile_publications": _count_where(
            connection, "profile_publications", "workspace_id = ?", (workspace_id,)
        ),
        "profile_sessions": len(session_ids),
    }
    if not any(table_counts.values()):
        raise ProfileResetRefused(
            f"workspace has no profile data and cannot be reset: {workspace_id}"
        )

    preserved_counts = {
        "review_tables": _count_table_family(connection, "review_%"),
        "other_workspace_profile_materials": _count_where(
            connection, "profile_materials", "workspace_id <> ?", (workspace_id,)
        ),
        "other_workspace_profile_claims": _count_where(
            connection, "profile_claims", "workspace_id <> ?", (workspace_id,)
        ),
        "other_workspace_sessions": _count_where(
            connection, "agent_sessions", "workspace_id <> ?", (workspace_id,)
        ),
    }
    return ProfileResetPlan(
        workspace_id=workspace_id,
        table_counts=table_counts,
        session_ids=tuple(sorted(session_ids)),
        material_refs=refs,
        preserved_counts=preserved_counts,
    )


def execute_reset(
    connection: sqlite3.Connection,
    *,
    workspace_root: Path,
    workspace_id: str,
    confirmation: str,
) -> tuple[ProfileResetPlan, tuple[str, ...]]:
    expected = f"RESET PROFILE {workspace_id}"
    if confirmation != expected:
        raise ProfileResetRefused(f'confirmation must equal "{expected}"')

    connection.execute("BEGIN IMMEDIATE")
    try:
        plan = build_reset_plan(connection, workspace_id)
        if plan.session_ids:
            placeholders = ",".join("?" for _ in plan.session_ids)
            active = connection.execute(
                "SELECT r.id FROM agent_runs r "
                f"WHERE r.session_id IN ({placeholders}) "
                f"AND r.status IN ({','.join('?' for _ in _ACTIVE_RUN_STATUSES)}) "
                "LIMIT 1",
                (*plan.session_ids, *_ACTIVE_RUN_STATUSES),
            ).fetchone()
            if active is not None:
                raise ProfileResetRefused(
                    "workspace has an active Profile run; stop it before reset"
                )

        claim_ids = _select_ids(
            connection,
            "SELECT id FROM profile_claims WHERE workspace_id = ?",
            (workspace_id,),
        )
        selection_ids = _select_ids(
            connection,
            "SELECT id FROM profile_publication_selections WHERE workspace_id = ?",
            (workspace_id,),
        )
        material_ids = _select_ids(
            connection,
            "SELECT id FROM profile_materials WHERE workspace_id = ?",
            (workspace_id,),
        )
        version_ids = _select_for_ids(
            connection,
            "SELECT id FROM profile_material_versions WHERE material_id IN ({})",
            material_ids,
        )

        connection.execute(
            "DELETE FROM profile_action_plans WHERE workspace_id = ?", (workspace_id,)
        )
        connection.execute(
            "DELETE FROM profile_assessments WHERE workspace_id = ?", (workspace_id,)
        )
        connection.execute(
            "DELETE FROM profile_publications WHERE workspace_id = ?", (workspace_id,)
        )
        _delete_for_ids(
            connection,
            "profile_publication_selection_items",
            "selection_id",
            selection_ids,
        )
        connection.execute(
            "DELETE FROM profile_publication_selections WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_claim_conflicts WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_claim_proposals WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_claim_relations WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_claim_sources WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_presentations WHERE workspace_id = ?",
            (workspace_id,),
        )
        _delete_for_ids(connection, "profile_claims", "id", claim_ids)
        _delete_for_ids(
            connection, "profile_evidence", "material_version_id", version_ids
        )
        _delete_for_ids(
            connection, "profile_material_versions", "material_id", material_ids
        )
        connection.execute(
            "DELETE FROM profile_deletion_plans WHERE workspace_id = ?",
            (workspace_id,),
        )
        connection.execute(
            "DELETE FROM profile_materials WHERE workspace_id = ?", (workspace_id,)
        )
        connection.execute(
            "DELETE FROM profile_agent_context WHERE workspace_id = ?", (workspace_id,)
        )
        connection.execute(
            "DELETE FROM profile_idempotency_receipts WHERE workspace_id = ?",
            (workspace_id,),
        )
        _delete_for_ids(connection, "agent_sessions", "id", plan.session_ids)

        unreferenced = tuple(
            ref
            for ref in plan.material_refs
            if connection.execute(
                "SELECT COUNT(*) AS total FROM profile_material_versions "
                "WHERE storage_ref = ? OR text_ref = ?",
                (ref, ref),
            ).fetchone()["total"]
            == 0
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    storage = MaterialStorage(workspace_root)
    deleted_refs = tuple(
        ref
        for ref in unreferenced
        if storage.delete_ref(ref, remaining_references=0)
    )
    return plan, deleted_refs


def _count_where(
    connection: sqlite3.Connection,
    table: str,
    where: str,
    parameters: tuple[object, ...],
) -> int:
    return int(
        connection.execute(
            f"SELECT COUNT(*) AS total FROM {table} WHERE {where}", parameters
        ).fetchone()["total"]
    )


def _count_for_ids(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    ids: Sequence[str],
) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    return _count_where(connection, table, f"{column} IN ({placeholders})", tuple(ids))


def _count_table_family(connection: sqlite3.Connection, pattern: str) -> int:
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE ?",
        (pattern,),
    ).fetchall()
    return sum(
        int(
            connection.execute(f"SELECT COUNT(*) AS total FROM {row['name']}").fetchone()[
                "total"
            ]
        )
        for row in tables
    )


def _select_ids(
    connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...]
) -> tuple[str, ...]:
    return tuple(row["id"] for row in connection.execute(sql, parameters).fetchall())


def _select_for_ids(
    connection: sqlite3.Connection, sql: str, ids: Sequence[str]
) -> tuple[str, ...]:
    return tuple(row["id"] for row in _rows_for_ids(connection, sql, ids))


def _rows_for_ids(
    connection: sqlite3.Connection, sql: str, ids: Sequence[str]
) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return connection.execute(sql.format(placeholders), tuple(ids)).fetchall()


def _delete_for_ids(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    ids: Sequence[str],
) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    connection.execute(
        f"DELETE FROM {table} WHERE {column} IN ({placeholders})", tuple(ids)
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run or reset Profile data for one exact Workspace"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--workspace-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        database, workspace_root = validate_paths(
            args.database, args.workspace_root
        )
        connection = open_runtime_database(database)
        try:
            if args.dry_run:
                plan = build_reset_plan(connection, args.workspace_id)
                result = {"mode": "dry-run", **asdict(plan)}
            else:
                plan, deleted_refs = execute_reset(
                    connection,
                    workspace_root=workspace_root,
                    workspace_id=args.workspace_id,
                    confirmation=args.confirm,
                )
                result = {
                    "mode": "executed",
                    **asdict(plan),
                    "deleted_refs": deleted_refs,
                }
        finally:
            connection.close()
    except (ProfileResetRefused, sqlite3.Error) as exc:
        print(f"reset refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
