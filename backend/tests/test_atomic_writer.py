from pathlib import Path

import pytest

from app.knowledge.atomic_writer import (
    ExternalDocumentChangedError,
    atomic_write_text,
    hash_file,
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
