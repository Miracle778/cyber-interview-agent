from __future__ import annotations

import stat
from pathlib import Path

from app.security.workspace_paths import PathPolicyError


_SUPPORTED_DOMAINS = frozenset({"review", "profile"})

_DOMAIN_SUBDIRS = {
    "review": ("sources", "drafts"),
    "profile": ("materials/blobs", "materials/text"),
}


def initialize_knowledge_artifacts(
    workspace_root: Path, *, domain: str
) -> Path:
    if domain not in _SUPPORTED_DOMAINS:
        raise PathPolicyError("workspace", domain)

    root = workspace_root.expanduser()
    if root.is_symlink() or not root.is_dir():
        raise PathPolicyError("workspace")

    current = root
    for part in ("artifacts", domain):
        target = current / part
        _ensure_directory(target)
        current = target

    domain_root = current
    for part in _DOMAIN_SUBDIRS[domain]:
        _ensure_directory(domain_root / part)

    return domain_root


def _ensure_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise PathPolicyError("workspace", str(path.name))
        return
    path.mkdir()
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise PathPolicyError("workspace", str(path.name))
