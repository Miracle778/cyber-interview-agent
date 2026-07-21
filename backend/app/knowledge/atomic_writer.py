from __future__ import annotations

import os
import stat
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


def quarantine_remove_owned_file(
    target: Path,
    expected_hash: str,
    *,
    quarantine: Path,
    path_hash_func: Callable[[Path], str] = hash_file,
) -> str:
    """Remove only the same regular file that was opened and hashed."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "conflict"
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return "conflict"
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != expected_hash:
            return "conflict"
        try:
            if path_hash_func(target) != expected_hash:
                return "conflict"
            if quarantine.exists() or quarantine.is_symlink():
                return "conflict"
            os.replace(target, quarantine)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "conflict"
        moved = os.stat(quarantine, follow_symlinks=False)
        if (moved.st_dev, moved.st_ino) != (opened.st_dev, opened.st_ino):
            _restore_quarantine(
                quarantine,
                target,
                expected_identity=(moved.st_dev, moved.st_ino),
            )
            return "conflict"
        quarantine.unlink()
        return "removed"
    finally:
        os.close(descriptor)


def reconcile_quarantined_file(
    target: Path,
    quarantine: Path,
    expected_hash: str,
) -> str:
    """Reconcile a deterministic quarantine left by an interrupted removal."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(quarantine, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "conflict"
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return "conflict"
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        identity = (opened.st_dev, opened.st_ino)
        try:
            current = os.stat(quarantine, follow_symlinks=False)
        except OSError:
            return "conflict"
        if (current.st_dev, current.st_ino) != identity:
            return "conflict"
        if digest.hexdigest() == expected_hash:
            target_conflict = target.exists() or target.is_symlink()
            try:
                quarantine.unlink()
            except OSError:
                return "conflict"
            return "conflict" if target_conflict else "owned_removed"
        if _restore_quarantine(
            quarantine,
            target,
            expected_identity=identity,
        ):
            return "external_restored"
        return "conflict"
    finally:
        os.close(descriptor)


def _restore_quarantine(
    quarantine: Path,
    target: Path,
    *,
    expected_identity: tuple[int, int],
) -> bool:
    try:
        os.link(quarantine, target, follow_symlinks=False)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        restored = os.stat(target, follow_symlinks=False)
        if (restored.st_dev, restored.st_ino) != expected_identity:
            return False
        quarantine.unlink()
    except OSError:
        return False
    return True


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
