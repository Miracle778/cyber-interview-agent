#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.infrastructure.runtime_database import connect_runtime_database  # noqa: E402
from app.observability.indexer import TraceLedgerIndexer  # noqa: E402
from app.observability.repository import TraceIndexRepository  # noqa: E402


def require_workspace_root(value: str) -> Path:
    candidate = Path(value).expanduser().resolve(strict=True)
    if (
        candidate == Path("/")
        or candidate == Path.home().resolve()
        or not candidate.is_dir()
        or not (candidate / ".cyber-interview-agent").is_dir()
    ):
        raise argparse.ArgumentTypeError(
            "必须提供明确的 Workspace 根目录，不能使用 / 或用户主目录"
        )
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild only the local Agent Trace metadata index"
    )
    parser.add_argument("--workspace-root", required=True, type=require_workspace_root)
    parser.add_argument("--workspace-id", required=True)
    args = parser.parse_args()
    print(f"Resolved workspace target: {args.workspace_root}")
    connection = connect_runtime_database(args.workspace_root)
    try:
        repository = TraceIndexRepository(connection)
        result = TraceLedgerIndexer(
            workspace_id=args.workspace_id,
            workspace_root=args.workspace_root,
            repository=repository,
        ).rebuild_workspace()
        print(
            json.dumps(
                {
                    "indexedEvents": result.indexed_events,
                    "malformedRows": result.malformed_rows,
                    "missingFiles": result.missing_files,
                    "files": len(repository.list_files()),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.malformed_rows == 0 else 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
