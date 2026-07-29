from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from test_agent_trace_retention import _service


ROOT = Path(__file__).parents[2]
CHECK = ROOT / "scripts" / "check_agent_trace_consistency.py"
REBUILD = ROOT / "scripts" / "rebuild_agent_trace_index.py"


def _run(script: Path, *arguments: str):
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_is_read_only_and_rebuild_restores_only_trace_index(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    try:
        healthy = _run(CHECK, "--workspace-root", str(tmp_path))
        assert healthy.returncode == 0
        assert '"checkedEvents": 1' in healthy.stdout

        connection.execute("DELETE FROM agent_trace_events")
        connection.execute("DELETE FROM agent_trace_operations")
        connection.execute("DELETE FROM agent_trace_executions")
        connection.execute("DELETE FROM agent_trace_files")
        connection.commit()
        rebuilt = _run(
            REBUILD,
            "--workspace-root",
            str(tmp_path),
            "--workspace-id",
            "workspace-1",
        )
        assert rebuilt.returncode == 0
        assert f"Resolved workspace target: {tmp_path.resolve()}" in rebuilt.stdout
        assert '"indexedEvents": 1' in rebuilt.stdout
        assert connection.execute(
            "SELECT status FROM agent_runs WHERE id = 'run-1'"
        ).fetchone()[0] == "completed"
    finally:
        connection.close()


def test_check_reports_stale_pointer_and_broad_targets_are_rejected(tmp_path) -> None:
    connection, _retention = _service(tmp_path)
    try:
        connection.execute(
            "UPDATE agent_trace_events SET byte_start = byte_start + 1"
        )
        connection.commit()
        broken = _run(CHECK, "--workspace-root", str(tmp_path))
        assert broken.returncode == 1
        assert "pointer outside source" in broken.stdout
        rejected = _run(CHECK, "--workspace-root", str(Path.home()))
        assert rejected.returncode != 0
        assert "不能使用 / 或用户主目录" in rejected.stderr
    finally:
        connection.close()
