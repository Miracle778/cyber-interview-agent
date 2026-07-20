from pathlib import Path

import pytest

from app.security.workspace_paths import PathPolicyError, WorkspacePathPolicy


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    for relative in (
        "artifacts/review/sources",
        "artifacts/review/drafts",
        "artifacts/profile/materials",
        "knowledge-vault",
        ".cyber-interview-agent/diagnostics",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def policy(workspace: Path) -> WorkspacePathPolicy:
    return WorkspacePathPolicy(workspace)


@pytest.mark.parametrize(
    "relative_path",
    ["", ".", "./", "/etc/passwd", "../secret.txt", "a/../secret.txt", "a\x00b"],
)
def test_rejects_invalid_relative_paths(
    policy: WorkspacePathPolicy, relative_path: str
) -> None:
    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read("review.sources", relative_path)

    assert caught.value.code == "workspace_path_denied"
    assert "/etc" not in str(caught.value)


def test_rejects_unknown_scope(policy: WorkspacePathPolicy) -> None:
    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read("unknown.scope", "notes.md")

    assert caught.value.code == "workspace_path_denied"


def test_resolves_existing_regular_unicode_file(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    source = workspace / "artifacts/review/sources/面试记录.md"
    source.write_text("内容", encoding="utf-8")

    resolved = policy.resolve_for_read("review.sources", "面试记录.md")

    assert resolved == source.resolve()


def test_read_requires_existing_regular_file(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    (workspace / "artifacts/review/sources/folder").mkdir()

    for relative_path in ("missing.md", "folder"):
        with pytest.raises(PathPolicyError) as caught:
            policy.resolve_for_read("review.sources", relative_path)
        assert caught.value.code == "workspace_path_denied"


def test_create_requires_existing_parent_and_missing_or_regular_target(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    drafts = workspace / "artifacts/review/drafts"
    (drafts / "existing.md").write_text("draft", encoding="utf-8")
    (drafts / "folder").mkdir()

    assert policy.resolve_for_create("review.drafts", "new.md") == drafts / "new.md"
    assert (
        policy.resolve_for_create("review.drafts", "existing.md")
        == drafts / "existing.md"
    )

    for relative_path in ("missing/new.md", "folder"):
        with pytest.raises(PathPolicyError) as caught:
            policy.resolve_for_create("review.drafts", relative_path)
        assert caught.value.code == "workspace_path_denied"


def test_rejects_symlink_target(
    policy: WorkspacePathPolicy, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    target = workspace / "artifacts/review/sources/link.md"
    target.symlink_to(outside)

    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read("review.sources", "link.md")

    assert caught.value.code == "workspace_path_denied"


def test_rejects_symlink_parent(
    policy: WorkspacePathPolicy, workspace: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    link = workspace / "artifacts/review/sources/escape"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read("review.sources", "escape/secret.md")

    assert caught.value.code == "workspace_path_denied"


def test_error_does_not_expose_workspace_absolute_path(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read("review.sources", "missing.md")

    assert str(workspace) not in str(caught.value)
    assert "review.sources" in str(caught.value)
    assert "missing.md" in str(caught.value)


def test_profile_materials_scope_resolves_private_blob(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    blobs = workspace / "artifacts/profile/materials/blobs/ab"
    blobs.mkdir(parents=True)
    blob = blobs / "abc123.txt"
    blob.write_text("resume bytes", encoding="utf-8")

    resolved = policy.resolve_for_read(
        "profile.materials", "blobs/ab/abc123.txt"
    )

    assert resolved == blob.resolve()


def test_profile_materials_scope_rejects_traversal_to_vault(
    policy: WorkspacePathPolicy, workspace: Path
) -> None:
    (workspace / "knowledge-vault/50_profile/secret.md").parent.mkdir(parents=True)
    (workspace / "knowledge-vault/50_profile/secret.md").write_text("no", encoding="utf-8")

    with pytest.raises(PathPolicyError) as caught:
        policy.resolve_for_read(
            "profile.materials", "../../knowledge-vault/50_profile/secret.md"
        )

    assert caught.value.code == "workspace_path_denied"
