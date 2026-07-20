from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from app.profile.errors import (
    ProfileFileNameInvalid,
    ProfileStorageError,
    ProfileUnsupportedFileType,
    ProfileUploadTooLarge,
)
from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy

MAX_MATERIAL_BYTES = 10 * 1024 * 1024

_EXTENSION_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}

_PROFILE_SCOPE = "profile.materials"


@dataclass(frozen=True, slots=True)
class StoredBlob:
    storage_ref: str
    content_sha256: str
    extension: str
    mime_type: str
    size_bytes: int


class MaterialStorage:
    """Private content-addressed storage for resume material bytes and
    extracted text. Lives under ``artifacts/profile/materials`` and never inside
    the knowledge vault. All paths go through :class:`WorkspacePathPolicy`."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root
        self._policy = WorkspacePathPolicy(workspace_root)

    def persist_upload(self, *, file_name: str, content: bytes) -> StoredBlob:
        extension = _validate_file_name(file_name)
        if len(content) > MAX_MATERIAL_BYTES:
            raise ProfileUploadTooLarge("upload exceeds 10 MiB limit")
        digest = hashlib.sha256(content).hexdigest()
        storage_ref = f"blobs/{digest[:2]}/{digest}{extension}"

        if not self.blob_exists(storage_ref):
            self._ensure_blob_dir(digest[:2])
            self._atomic_write_bytes(storage_ref, content)
            # Verify the write matches the content hash (detects short writes).
            written = self.read_blob(storage_ref)
            if hashlib.sha256(written).hexdigest() != digest:
                raise ProfileStorageError("blob hash verification failed")

        return StoredBlob(
            storage_ref=storage_ref,
            content_sha256=digest,
            extension=extension,
            mime_type=_EXTENSION_MIME[extension],
            size_bytes=len(content),
        )

    def write_text(self, *, version_id: str, text: str) -> str:
        _validate_version_id(version_id)
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        text_ref = f"text/{version_id}.txt"
        self._atomic_write_text(text_ref, normalized)
        return text_ref

    def read_blob(self, storage_ref: str) -> bytes:
        path = self._policy.resolve_for_read(_PROFILE_SCOPE, storage_ref)
        return path.read_bytes()

    def read_text(self, text_ref: str) -> str:
        path = self._policy.resolve_for_read(_PROFILE_SCOPE, text_ref)
        return path.read_text(encoding="utf-8")

    def blob_exists(self, storage_ref: str) -> bool:
        try:
            path = self._policy.resolve_for_read(_PROFILE_SCOPE, storage_ref)
        except PathPolicyError:
            return False
        return path.is_file()

    def delete_ref(self, ref: str) -> None:
        try:
            path = self._policy.resolve_for_read(_PROFILE_SCOPE, ref)
        except PathPolicyError:
            return
        if path.is_symlink() or not path.is_file():
            return
        path.unlink()

    def _ensure_blob_dir(self, prefix: str) -> None:
        blobs_root = self._policy.scope_root(_PROFILE_SCOPE) / "blobs"
        target = blobs_root / prefix
        if target.exists() or target.is_symlink():
            mode = target.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise PathPolicyError(_PROFILE_SCOPE, f"blobs/{prefix}")
            return
        target.mkdir()

    def _atomic_write_bytes(self, ref: str, content: bytes) -> None:
        target = self._policy.resolve_for_create(_PROFILE_SCOPE, ref)
        temp = self._policy.resolve_for_create(
            _PROFILE_SCOPE, f".{target.name}.{uuid4().hex}.tmp"
        )
        try:
            with temp.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if temp.is_symlink():
                raise PathPolicyError(_PROFILE_SCOPE, ref)
            os.replace(temp, target)
        finally:
            if temp.exists() or temp.is_symlink():
                temp.unlink()

    def _atomic_write_text(self, ref: str, text: str) -> None:
        target = self._policy.resolve_for_create(_PROFILE_SCOPE, ref)
        temp = self._policy.resolve_for_create(
            _PROFILE_SCOPE, f".{target.name}.{uuid4().hex}.tmp"
        )
        encoded = text.encode("utf-8")
        try:
            with temp.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if temp.is_symlink():
                raise PathPolicyError(_PROFILE_SCOPE, ref)
            os.replace(temp, target)
        finally:
            if temp.exists() or temp.is_symlink():
                temp.unlink()


def _validate_file_name(file_name: str) -> str:
    if (
        not file_name
        or file_name in {".", ".."}
        or Path(file_name).name != file_name
        or PureWindowsPath(file_name).name != file_name
    ):
        raise ProfileFileNameInvalid("filename must be a plain file name")
    extension = Path(file_name).suffix.lower()
    if extension not in _EXTENSION_MIME:
        raise ProfileUnsupportedFileType("unsupported file type")
    return extension


def _validate_version_id(version_id: str) -> None:
    if (
        not version_id
        or "/" in version_id
        or "\\" in version_id
        or Path(version_id).name != version_id
    ):
        raise ProfileFileNameInvalid("invalid version id")
