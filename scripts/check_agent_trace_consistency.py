#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import stat
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.infrastructure.runtime_database import runtime_database_path  # noqa: E402


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


def check(root: Path) -> dict[str, object]:
    database = runtime_database_path(root)
    if not database.is_file():
        return {"ok": False, "errors": ["runtime database is missing"], "checkedEvents": 0}
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    trace_root = root / ".cyber-interview-agent" / "agent-traces"
    errors: list[str] = []
    checked = 0
    try:
        events = connection.execute(
            "SELECT * FROM agent_trace_events ORDER BY relative_path, byte_start"
        )
        for event in events:
            if event["body_state"] == "deleted":
                continue
            path = trace_root / event["relative_path"]
            if path.is_symlink() or not path.exists():
                errors.append(f"{event['event_id']}: source missing or symlinked")
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                errors.append(f"{event['event_id']}: source is not a regular file")
                continue
            size = path.stat().st_size
            start = int(event["byte_start"])
            length = int(event["byte_length"])
            if start < 0 or length <= 0 or start + length > size:
                errors.append(f"{event['event_id']}: pointer outside source")
                continue
            with path.open("rb") as stream:
                stream.seek(start)
                raw = stream.read(length)
            try:
                row = json.loads(raw.rstrip(b"\r\n"))
            except Exception:
                errors.append(f"{event['event_id']}: corrupt indexed row")
                continue
            if (
                row.get("event_id") != event["event_id"]
                or row.get("run_id") != event["run_id"]
            ):
                errors.append(f"{event['event_id']}: stale index pointer")
                continue
            checked += 1
    finally:
        connection.close()
    return {"ok": not errors, "errors": errors, "checkedEvents": checked}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Agent Trace index consistency check"
    )
    parser.add_argument("--workspace-root", required=True, type=require_workspace_root)
    args = parser.parse_args()
    result = check(args.workspace_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
