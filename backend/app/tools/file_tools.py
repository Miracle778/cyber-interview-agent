from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.security.workspace_paths import WorkspacePathPolicy
from app.tools.context import ToolExecutionContext
from app.tools.registry import ToolError


MAX_TEXT_BYTES = 256 * 1024
DIAGNOSTIC_PROBE_CONTENT = "tool-security-probe-v1"


class FileTooLargeError(ToolError):
    code = "tool_file_too_large"


class FileContentInvalidError(ToolError):
    code = "tool_file_content_invalid"


class DraftVersionChangedError(ToolError):
    code = "draft_version_changed"


class ReadTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class ReadTextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    text: str
    sha256: str
    byte_count: int


class WriteDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    expected_sha256: str | None = None


class WriteDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    byte_count: int


def read_source(
    context: ToolExecutionContext, input_data: ReadTextInput
) -> ReadTextOutput:
    return _read_text(context, "review.sources", input_data.path)


def read_active_knowledge(
    context: ToolExecutionContext, input_data: ReadTextInput
) -> ReadTextOutput:
    return _read_text(context, "knowledge.active", input_data.path)


def diagnostic_read(
    context: ToolExecutionContext, input_data: ReadTextInput
) -> ReadTextOutput:
    policy = WorkspacePathPolicy(context.workspace_root)
    probe = policy.resolve_for_create("diagnostics.security", "probe.txt")
    if not probe.exists():
        probe = policy.resolve_for_create("diagnostics.security", "probe.txt")
        try:
            with probe.open("x", encoding="utf-8") as handle:
                handle.write(DIAGNOSTIC_PROBE_CONTENT)
        except FileExistsError:
            pass
    return _read_text(context, "diagnostics.security", input_data.path)


def write_review_draft(
    context: ToolExecutionContext, input_data: WriteDraftInput
) -> WriteDraftOutput:
    policy = WorkspacePathPolicy(context.workspace_root)
    target = policy.resolve_for_create("review.drafts", input_data.path)
    _verify_expected_version(target, input_data.expected_sha256)

    encoded = input_data.content.encode("utf-8")
    temp_relative = f".{target.name}.{uuid4().hex}.tmp"
    parent_relative = Path(input_data.path).parent
    if parent_relative != Path("."):
        temp_relative = (parent_relative / temp_relative).as_posix()
    temp = policy.resolve_for_create("review.drafts", temp_relative)

    try:
        with temp.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

        target = policy.resolve_for_create("review.drafts", input_data.path)
        _verify_expected_version(target, input_data.expected_sha256)
        os.replace(temp, target)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()

    return WriteDraftOutput(
        path=input_data.path,
        sha256=sha256(encoded).hexdigest(),
        byte_count=len(encoded),
    )


def _read_text(
    context: ToolExecutionContext, scope: str, relative_path: str
) -> ReadTextOutput:
    policy = WorkspacePathPolicy(context.workspace_root)
    path = policy.resolve_for_read(scope, relative_path)
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise FileTooLargeError("Tool file exceeds the size limit")

    path = policy.resolve_for_read(scope, relative_path)
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise FileTooLargeError("Tool file exceeds the size limit")
    body = path.read_bytes()
    if len(body) > MAX_TEXT_BYTES:
        raise FileTooLargeError("Tool file exceeds the size limit")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise FileContentInvalidError("Tool file must be UTF-8 text") from error

    return ReadTextOutput(
        path=relative_path,
        text=text,
        sha256=sha256(body).hexdigest(),
        byte_count=len(body),
    )


def _verify_expected_version(target: Path, expected_sha256: str | None) -> None:
    if not target.exists():
        return
    if expected_sha256 is None or _sha256_file(target) != expected_sha256:
        raise DraftVersionChangedError("Draft version has changed")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
