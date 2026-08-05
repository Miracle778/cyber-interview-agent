from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path


_CASE_ROOT = ".agent-evaluation/cases"
_EXECUTION_ROOT = ".agent-evaluation/execution-snapshots"


def create_restorable_case_snapshot(
    *,
    workspace_root: Path,
    case_id: str,
    connection,
) -> dict[str, object]:
    case_root = workspace_root / _CASE_ROOT / case_id
    return _create_snapshot(
        workspace_root=workspace_root,
        snapshot_root=case_root,
        artifact_ref=f"{_CASE_ROOT}/{case_id}",
        connection=connection,
    )


def create_pre_execution_snapshot(
    *,
    workspace_root: Path,
    execution_id: str,
    connection,
) -> dict[str, object]:
    snapshot_root = workspace_root / _EXECUTION_ROOT / execution_id
    if snapshot_root.exists():
        return load_pre_execution_snapshot(
            workspace_root=workspace_root,
            execution_id=execution_id,
        )
    return _create_snapshot(
        workspace_root=workspace_root,
        snapshot_root=snapshot_root,
        artifact_ref=f"{_EXECUTION_ROOT}/{execution_id}",
        connection=connection,
    )


def load_pre_execution_snapshot(
    *, workspace_root: Path, execution_id: str
) -> dict[str, object]:
    snapshot_root = workspace_root / _EXECUTION_ROOT / execution_id
    if not snapshot_root.is_dir():
        raise FileNotFoundError(snapshot_root)
    hashes = _file_hashes(snapshot_root)
    return {
        "mode": "restorable",
        "capturePoint": "before_graph_execution",
        "sourceExecutionId": execution_id,
        "artifactRef": f"{_EXECUTION_ROOT}/{execution_id}",
        "fileHashes": hashes,
        "fileCount": len(hashes),
    }


def _create_snapshot(
    *,
    workspace_root: Path,
    snapshot_root: Path,
    artifact_ref: str,
    connection,
) -> dict[str, object]:
    case_root = snapshot_root
    if case_root.exists():
        raise FileExistsError(case_root)
    database_target = case_root / ".cyber-interview-agent" / "runtime.sqlite"
    database_target.parent.mkdir(parents=True)
    _backup_database(connection, database_target)
    checkpoint_source = (
        workspace_root / ".cyber-interview-agent" / "checkpoints.sqlite"
    )
    if checkpoint_source.is_file():
        checkpoint_source_connection = sqlite3.connect(checkpoint_source)
        try:
            _backup_database(
                checkpoint_source_connection,
                case_root / ".cyber-interview-agent" / "checkpoints.sqlite",
            )
        finally:
            checkpoint_source_connection.close()
    artifacts = workspace_root / "artifacts"
    if artifacts.is_dir():
        _copy_tree_without_links(artifacts, case_root / "artifacts")
    hashes = _file_hashes(case_root)
    return {
        "mode": "restorable",
        "artifactRef": artifact_ref,
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
    allowed_prefixes = (f"{_CASE_ROOT}/", f"{_EXECUTION_ROOT}/")
    if not isinstance(ref, str) or not ref.startswith(allowed_prefixes):
        raise ValueError("invalid regression snapshot artifact ref")
    source = (workspace_root / ref).resolve()
    allowed_roots = (
        (workspace_root / _CASE_ROOT).resolve(),
        (workspace_root / _EXECUTION_ROOT).resolve(),
    )
    if not any(allowed in source.parents for allowed in allowed_roots) or not source.is_dir():
        raise ValueError("regression snapshot artifact is outside case storage")
    expected = snapshot.get("fileHashes")
    if not isinstance(expected, dict) or _file_hashes(source) != expected:
        raise ValueError("regression snapshot hash mismatch")
    if sandbox_root.exists() and any(sandbox_root.iterdir()):
        raise ValueError("regression sandbox must be empty")
    sandbox_root.mkdir(parents=True, exist_ok=True)
    _copy_tree_without_links(source, sandbox_root)


def _backup_database(connection, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(target)
    try:
        connection.backup(destination)
    finally:
        destination.close()


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
