#!/usr/bin/env python3
"""Repair profile Claim support after resume material/version deletion."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.profile.repository import ProfileRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mark stale resume sources as deleted and recompute current Claim support "
            "from all remaining live Evidence."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--workspace",
        action="append",
        default=[],
        help="Workspace ID to repair; repeat for multiple workspaces. Defaults to all.",
    )
    args = parser.parse_args()

    database = args.database.expanduser().resolve()
    if not database.is_file():
        parser.error(f"database does not exist: {database}")

    connection = sqlite3.connect(database, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    repository = ProfileRepository(connection)
    try:
        workspace_ids = tuple(dict.fromkeys(args.workspace))
        if not workspace_ids:
            workspace_ids = tuple(
                row["workspace_id"]
                for row in connection.execute(
                    "SELECT DISTINCT workspace_id FROM profile_claims "
                    "ORDER BY workspace_id"
                ).fetchall()
            )
        result = {
            workspace_id: repository.recompute_claim_support(workspace_id)
            for workspace_id in workspace_ids
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
