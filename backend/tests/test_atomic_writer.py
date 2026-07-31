import os
from pathlib import Path

import pytest

from app.knowledge.atomic_writer import (
    ExternalDocumentChangedError,
    atomic_write_text,
    hash_file,
    quarantine_remove_owned_file,
    reconcile_quarantined_file,
)


def test_atomic_write_flushes_and_replaces_target(tmp_path: Path) -> None:
    target = tmp_path / "question.md"
    fsync_calls: list[int] = []

    result_hash = atomic_write_text(
        target,
        "# Question\n",
        expected_existing_hash=None,
        fsync_func=fsync_calls.append,
    )

    assert target.read_text(encoding="utf-8") == "# Question\n"
    assert result_hash == hash_file(target)
    assert len(fsync_calls) == 1
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_replaces_expected_existing_version(tmp_path: Path) -> None:
    target = tmp_path / "question.md"
    target.write_text("old", encoding="utf-8")
    expected = hash_file(target)

    atomic_write_text(target, "new", expected_existing_hash=expected)

    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_preserves_external_edit_on_hash_conflict(
    tmp_path: Path,
) -> None:
    target = tmp_path / "question.md"
    target.write_text("external", encoding="utf-8")

    with pytest.raises(ExternalDocumentChangedError):
        atomic_write_text(target, "replacement", expected_existing_hash="stale")

    assert target.read_text(encoding="utf-8") == "external"
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_cleans_temp_file_when_replace_fails(
    tmp_path: Path,
) -> None:
    target = tmp_path / "question.md"

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(
            target,
            "content",
            expected_existing_hash=None,
            replace_func=fail_replace,
        )

    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_atomic_write_rejects_symlink_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    target = tmp_path / "question.md"
    target.symlink_to(outside)

    with pytest.raises(ExternalDocumentChangedError):
        atomic_write_text(
            target,
            "replacement",
            expected_existing_hash=hash_file(outside),
        )

    assert outside.read_text(encoding="utf-8") == "outside"


def test_quarantine_uses_binary_mode_and_closes_before_windows_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "question.md"
    target.write_bytes(b"line one\r\nline two\r\n")
    quarantine = tmp_path / ".question.md.quarantine"
    expected_hash = hash_file(target)
    binary_flag = 1 << 29
    real_open = os.open
    real_close = os.close
    real_replace = os.replace
    native_binary_flag = getattr(os, "O_BINARY", 0)
    open_descriptors: set[int] = set()
    observed_flags: list[int] = []

    monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)

    def tracked_open(path, flags, mode=0o777):
        observed_flags.append(flags)
        descriptor = real_open(
            path,
            (flags & ~binary_flag) | native_binary_flag,
            mode,
        )
        open_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor):
        open_descriptors.discard(descriptor)
        real_close(descriptor)

    def windows_replace(source, destination):
        if open_descriptors:
            raise PermissionError("Windows sharing violation")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    monkeypatch.setattr(os, "replace", windows_replace)

    result = quarantine_remove_owned_file(
        target,
        expected_hash,
        quarantine=quarantine,
    )

    assert result == "removed"
    assert any(flags & binary_flag for flags in observed_flags)
    assert not target.exists()
    assert not quarantine.exists()


def test_reconcile_closes_descriptor_before_windows_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "question.md"
    quarantine = tmp_path / ".question.md.quarantine"
    quarantine.write_bytes(b"owned content\r\n")
    expected_hash = hash_file(quarantine)
    real_open = os.open
    real_close = os.close
    real_unlink = os.unlink
    open_descriptors: set[int] = set()

    def tracked_open(path, flags, mode=0o777):
        descriptor = real_open(path, flags, mode)
        open_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor):
        open_descriptors.discard(descriptor)
        real_close(descriptor)

    def windows_unlink(path, *args, **kwargs):
        if open_descriptors:
            raise PermissionError("Windows sharing violation")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    monkeypatch.setattr(os, "unlink", windows_unlink)

    result = reconcile_quarantined_file(target, quarantine, expected_hash)

    assert result == "owned_removed"
    assert not quarantine.exists()
