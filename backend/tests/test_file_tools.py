from hashlib import sha256
from pathlib import Path

import pytest

from app.security.workspace_paths import WorkspacePathPolicy
from app.tools.context import ToolExecutionContext
from app.tools.defaults import create_default_tool_registry
from app.tools.file_tools import (
    DraftVersionChangedError,
    FileContentInvalidError,
    FileTooLargeError,
    MAX_TEXT_BYTES,
)
from app.tools.registry import ToolRegistry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    for relative in (
        "artifacts/review/sources",
        "artifacts/review/drafts",
        "knowledge-vault",
        ".cyber-interview-agent/diagnostics",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_id="w1",
        workspace_root=workspace,
        session_id="s1",
        run_id="r1",
        graph_id="test.files",
        graph_version=1,
        allowed_tools=frozenset(
            {
                "read_source",
                "read_active_knowledge",
                "write_review_draft",
                "diagnostic_read",
            }
        ),
        allowed_scopes=frozenset(
            {
                "review.sources",
                "review.drafts",
                "knowledge.active",
                "diagnostics.security",
            }
        ),
    )


@pytest.fixture
def registry() -> ToolRegistry:
    return create_default_tool_registry()


def test_reads_utf8_source_with_hash_and_byte_count(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    content = "赛博面试记录"
    encoded = content.encode("utf-8")
    (workspace / "artifacts/review/sources/notes.md").write_bytes(encoded)

    result = registry.invoke("read_source", context, {"path": "notes.md"})

    assert result == {
        "path": "notes.md",
        "text": content,
        "sha256": sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
    }


def test_reads_active_knowledge_without_write_capability(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    page = workspace / "knowledge-vault/topic.md"
    page.write_text("knowledge", encoding="utf-8")

    result = registry.invoke(
        "read_active_knowledge", context, {"path": "topic.md"}
    )

    assert result["text"] == "knowledge"
    assert "write_active_knowledge" not in context.allowed_tools


def test_rejects_oversized_text_before_reading_body(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    source = workspace / "artifacts/review/sources/large.md"
    source.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))

    with pytest.raises(FileTooLargeError) as caught:
        registry.invoke("read_source", context, {"path": "large.md"})

    assert caught.value.code == "tool_file_too_large"


def test_rejects_non_utf8_text(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    (workspace / "artifacts/review/sources/binary.md").write_bytes(b"\xff\xfe")

    with pytest.raises(FileContentInvalidError) as caught:
        registry.invoke("read_source", context, {"path": "binary.md"})

    assert caught.value.code == "tool_file_content_invalid"


def test_writes_new_draft_atomically(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    result = registry.invoke(
        "write_review_draft",
        context,
        {"path": "draft.md", "content": "first"},
    )

    encoded = b"first"
    assert result == {
        "path": "draft.md",
        "sha256": sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
    }
    assert (workspace / "artifacts/review/drafts/draft.md").read_bytes() == encoded
    assert list((workspace / "artifacts/review/drafts").glob("*.tmp")) == []


@pytest.mark.parametrize("expected_sha256", [None, "stale"])
def test_existing_draft_requires_matching_hash(
    registry: ToolRegistry,
    context: ToolExecutionContext,
    workspace: Path,
    expected_sha256: str | None,
) -> None:
    target = workspace / "artifacts/review/drafts/draft.md"
    target.write_text("first", encoding="utf-8")

    raw_input: dict[str, object] = {"path": "draft.md", "content": "second"}
    if expected_sha256 is not None:
        raw_input["expected_sha256"] = expected_sha256

    with pytest.raises(DraftVersionChangedError) as caught:
        registry.invoke("write_review_draft", context, raw_input)

    assert caught.value.code == "draft_version_changed"
    assert target.read_text(encoding="utf-8") == "first"


def test_overwrites_existing_draft_with_matching_hash(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    target = workspace / "artifacts/review/drafts/draft.md"
    target.write_bytes(b"first")

    result = registry.invoke(
        "write_review_draft",
        context,
        {
            "path": "draft.md",
            "content": "second",
            "expected_sha256": sha256(b"first").hexdigest(),
        },
    )

    assert result["sha256"] == sha256(b"second").hexdigest()
    assert target.read_bytes() == b"second"


def test_read_revalidates_path_immediately_before_io(
    registry: ToolRegistry,
    context: ToolExecutionContext,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "artifacts/review/sources/notes.md").write_text(
        "safe", encoding="utf-8"
    )
    original = WorkspacePathPolicy.resolve_for_read
    calls: list[str] = []

    def tracking_resolve(
        self: WorkspacePathPolicy, scope: str, relative_path: str
    ) -> Path:
        calls.append(relative_path)
        return original(self, scope, relative_path)

    monkeypatch.setattr(WorkspacePathPolicy, "resolve_for_read", tracking_resolve)

    registry.invoke("read_source", context, {"path": "notes.md"})

    assert calls == ["notes.md", "notes.md"]


def test_diagnostic_probe_stays_outside_business_directories(
    registry: ToolRegistry, context: ToolExecutionContext, workspace: Path
) -> None:
    result = registry.invoke("diagnostic_read", context, {"path": "probe.txt"})

    assert result["path"] == "probe.txt"
    assert result["text"] == "tool-security-probe-v1"
    assert (
        workspace / ".cyber-interview-agent/diagnostics/probe.txt"
    ).is_file()
    assert list((workspace / "artifacts/review/sources").iterdir()) == []
    assert list((workspace / "artifacts/review/drafts").iterdir()) == []
    assert list((workspace / "knowledge-vault").iterdir()) == []


def test_diagnostic_probe_revalidates_path_before_create(
    registry: ToolRegistry,
    context: ToolExecutionContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = WorkspacePathPolicy.resolve_for_create
    calls: list[str] = []

    def tracking_resolve(
        self: WorkspacePathPolicy, scope: str, relative_path: str
    ) -> Path:
        calls.append(relative_path)
        return original(self, scope, relative_path)

    monkeypatch.setattr(
        WorkspacePathPolicy, "resolve_for_create", tracking_resolve
    )

    registry.invoke("diagnostic_read", context, {"path": "probe.txt"})

    assert calls == ["probe.txt", "probe.txt"]
