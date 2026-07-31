from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path


_CASE_ROOT = ".agent-evaluation/cases"


def create_restorable_case_snapshot(
    *,
    workspace_root: Path,
    case_id: str,
    connection,
) -> dict[str, object]:
    case_root = workspace_root / _CASE_ROOT / case_id
    if case_root.exists():
        raise FileExistsError(case_root)
    database_target = case_root / ".cyber-interview-agent" / "runtime.sqlite"
    database_target.parent.mkdir(parents=True)
    destination = sqlite3.connect(database_target)
    try:
        connection.backup(destination)
    finally:
        destination.close()
    artifacts = workspace_root / "artifacts"
    if artifacts.is_dir():
        _copy_tree_without_links(artifacts, case_root / "artifacts")
    hashes = _file_hashes(case_root)
    return {
        "mode": "restorable",
        "artifactRef": f"{_CASE_ROOT}/{case_id}",
        "fileHashes": hashes,
        "fileCount": len(hashes),
    }


def restore_case_snapshot(
    *,
    workspace_root: Path,
    snapshot: dict[str, object],
    sandbox_root: Path,
) -> None:
    if snapshot.get("mode") != "restorable":
        raise ValueError("regression case domain snapshot is not restorable")
    ref = snapshot.get("artifactRef")
    if not isinstance(ref, str) or not ref.startswith(f"{_CASE_ROOT}/"):
        raise ValueError("invalid regression snapshot artifact ref")
    source = (workspace_root / ref).resolve()
    allowed = (workspace_root / _CASE_ROOT).resolve()
    if allowed not in source.parents or not source.is_dir():
        raise ValueError("regression snapshot artifact is outside case storage")
    expected = snapshot.get("fileHashes")
    if not isinstance(expected, dict) or _file_hashes(source) != expected:
        raise ValueError("regression snapshot hash mismatch")
    if sandbox_root.exists() and any(sandbox_root.iterdir()):
        raise ValueError("regression sandbox must be empty")
    sandbox_root.mkdir(parents=True, exist_ok=True)
    _copy_tree_without_links(source, sandbox_root)


def _copy_tree_without_links(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_symlink():
            raise ValueError(f"snapshot source contains symlink: {item.name}")
        destination = target / item.name
        if item.is_dir():
            _copy_tree_without_links(item, destination)
        elif item.is_file():
            shutil.copy2(item, destination)


def _file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"snapshot contains symlink: {path.name}")
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result
