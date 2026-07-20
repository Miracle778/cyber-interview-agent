from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.errors import (
    ProfileFileNameInvalid,
    ProfileUnsupportedFileType,
    ProfileUploadTooLarge,
)
from app.profile.storage import MaterialStorage


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    return root


@pytest.fixture
def storage(workspace: Path) -> MaterialStorage:
    return MaterialStorage(workspace)


def test_persist_upload_stores_blob_with_content_hash(storage: MaterialStorage) -> None:
    blob = storage.persist_upload(
        file_name="resume.txt", content=b"hello resume"
    )

    assert blob.extension == ".txt"
    assert blob.mime_type == "text/plain"
    assert blob.size_bytes == len(b"hello resume")
    assert blob.content_sha256 == _sha256(b"hello resume")
    assert blob.storage_ref.startswith("blobs/")
    assert blob.storage_ref.endswith(".txt")

    assert storage.read_blob(blob.storage_ref) == b"hello resume"


def test_persist_upload_rejects_oversized_upload(storage: MaterialStorage) -> None:
    content = b"x" * (10 * 1024 * 1024 + 1)
    with pytest.raises(ProfileUploadTooLarge) as caught:
        storage.persist_upload(file_name="big.pdf", content=content)
    assert caught.value.code == "profile_upload_too_large"
    assert "/ws" not in str(caught.value)


def test_persist_upload_rejects_unsupported_extension(storage: MaterialStorage) -> None:
    with pytest.raises(ProfileUnsupportedFileType):
        storage.persist_upload(file_name="resume.exe", content=b"nope")
    with pytest.raises(ProfileUnsupportedFileType):
        storage.persist_upload(file_name="noext", content=b"nope")


def test_persist_upload_rejects_filename_traversal(storage: MaterialStorage) -> None:
    for name in ("../escape.txt", "a/b.txt", "..\\escape.txt", ".hidden"):
        with pytest.raises((ProfileFileNameInvalid, Exception)):
            storage.persist_upload(file_name=name, content=b"x")


def test_duplicate_content_reuses_blob(storage: MaterialStorage) -> None:
    first = storage.persist_upload(file_name="resume.pdf", content=b"same bytes")
    second = storage.persist_upload(file_name="other.pdf", content=b"same bytes")

    assert first.storage_ref == second.storage_ref
    assert first.content_sha256 == second.content_sha256


def test_different_content_creates_distinct_blob(storage: MaterialStorage) -> None:
    first = storage.persist_upload(file_name="a.pdf", content=b"aaaa")
    second = storage.persist_upload(file_name="b.pdf", content=b"bbbb")

    assert first.storage_ref != second.storage_ref


def test_write_text_atomic_and_readable(storage: MaterialStorage) -> None:
    text_ref = storage.write_text(version_id="v1", text="normalized\ntext\n")

    assert text_ref == "text/v1.txt"
    assert storage.read_text(text_ref) == "normalized\ntext\n"


def test_write_text_normalizes_line_endings_without_rewriting_source(
    storage: MaterialStorage,
) -> None:
    text_ref = storage.write_text(version_id="v2", text="line1\r\nline2\r\n")

    assert storage.read_text(text_ref) == "line1\nline2\n"


def test_delete_ref_removes_blob(storage: MaterialStorage) -> None:
    blob = storage.persist_upload(file_name="r.txt", content=b"temp")
    storage.delete_ref(blob.storage_ref)
    assert not storage.blob_exists(blob.storage_ref)


def test_delete_ref_is_idempotent_for_missing(storage: MaterialStorage) -> None:
    storage.delete_ref("blobs/ab/missing.txt")  # no error


def test_storage_rejects_symlink_blob(
    storage: MaterialStorage, workspace: Path, tmp_path: Path
) -> None:
    blob = storage.persist_upload(file_name="r.txt", content=b"real")
    blob_path = workspace / "artifacts/profile/materials" / blob.storage_ref
    blob_path.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    blob_path.symlink_to(outside)

    with pytest.raises(Exception):
        storage.read_blob(blob.storage_ref)


def test_error_messages_do_not_leak_absolute_paths(
    storage: MaterialStorage, workspace: Path
) -> None:
    with pytest.raises(ProfileUploadTooLarge) as caught:
        storage.persist_upload(file_name="x.pdf", content=b"x" * (10 * 1024 * 1024 + 1))
    assert str(workspace) not in str(caught.value)
    assert str(workspace) not in repr(caught.value)


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()
