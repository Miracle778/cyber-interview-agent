from __future__ import annotations

import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


class ExternalDocumentChangedError(RuntimeError):
    pass


def hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(
    target: Path,
    content: str,
    *,
    expected_existing_hash: str | None,
    fsync_func: Callable[[int], object] = os.fsync,
    replace_func: Callable[[Path, Path], object] = os.replace,
) -> str:
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ExternalDocumentChangedError("target directory is not safe")
    if target.is_symlink():
        raise ExternalDocumentChangedError("target must not be a symlink")

    _verify_existing(target, expected_existing_hash)
    encoded = content.encode("utf-8")
    result_hash = sha256(encoded).hexdigest()
    temp = parent / f".{target.name}.{uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            fsync_func(handle.fileno())
        if temp.is_symlink():
            raise ExternalDocumentChangedError("temporary file was replaced")
        _verify_existing(target, expected_existing_hash)
        replace_func(temp, target)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()
    return result_hash


def _verify_existing(target: Path, expected_hash: str | None) -> None:
    if target.is_symlink():
        raise ExternalDocumentChangedError("target must not be a symlink")
    if not target.exists():
        if expected_hash is not None:
            raise ExternalDocumentChangedError("expected target is missing")
        return
    if not target.is_file():
        raise ExternalDocumentChangedError("target must be a regular file")
    if expected_hash is None or hash_file(target) != expected_hash:
        raise ExternalDocumentChangedError("target content changed externally")
