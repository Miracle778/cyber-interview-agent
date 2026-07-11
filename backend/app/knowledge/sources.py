from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


MAX_SOURCE_BYTES = 10 * 1024 * 1024


class SourceTooLargeError(ValueError):
    code = "source_too_large"


def save_source(
    workspace_root: Path, *, original_filename: str, content: bytes
) -> str:
    _validate_filename(original_filename)
    if len(content) > MAX_SOURCE_BYTES:
        raise SourceTooLargeError("source exceeds 10 MiB")

    initialize_knowledge_artifacts(workspace_root, domain="review")
    suffix = Path(original_filename).suffix.lower()
    filename = f"source_{uuid4().hex}{suffix}"
    policy = WorkspacePathPolicy(workspace_root)
    target = policy.resolve_for_create("review.sources", filename)
    temp_name = f".{filename}.{uuid4().hex}.tmp"
    temp = policy.resolve_for_create("review.sources", temp_name)
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        target = policy.resolve_for_create("review.sources", filename)
        os.replace(temp, target)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()
    return f"artifacts/review/sources/{filename}"


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or PureWindowsPath(filename).name != filename
    ):
        raise PathPolicyError("review.sources", filename)
