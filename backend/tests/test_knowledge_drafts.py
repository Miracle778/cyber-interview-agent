from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.drafts import (
    CreateDraftCommand,
    DraftContentChangedError,
    DraftVersionChangedError,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.security.workspace_paths import PathPolicyError


def _service(workspace: Path) -> KnowledgeDraftService:
    initialize_knowledge_artifacts(workspace, domain="review")
    connect_runtime_database(workspace).close()
    return KnowledgeDraftService(workspace, workspace_id="w1")


def _command(*, title: str = "缓存穿透") -> CreateDraftCommand:
    return CreateDraftCommand(
        domain="review",
        document_type="question",
        title=title,
        markdown=f"# {title}\n",
        source_refs=("source-1",),
        relation_refs=(),
    )


def test_initialize_artifacts_creates_sources_and_drafts(tmp_path: Path) -> None:
    initialize_knowledge_artifacts(tmp_path, domain="review")

    assert (tmp_path / "artifacts/review/sources").is_dir()
    assert (tmp_path / "artifacts/review/drafts").is_dir()


def test_initialize_artifacts_rejects_symlinked_domain(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "review").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathPolicyError):
        initialize_knowledge_artifacts(tmp_path, domain="review")

    assert not (outside / "sources").exists()
    assert not (outside / "drafts").exists()


@pytest.mark.asyncio
async def test_create_draft_writes_outside_vault(tmp_path: Path) -> None:
    service = _service(tmp_path)

    draft = await service.create(_command())

    assert draft.workspace_id == "w1"
    assert draft.content_path == f"artifacts/review/drafts/{draft.id}.md"
    assert (tmp_path / draft.content_path).read_text(encoding="utf-8") == (
        "# 缓存穿透\n"
    )
    assert draft.markdown == "# 缓存穿透\n"
    assert draft.version == 1
    assert draft.status == "draft"
    assert draft.source_refs == ("source-1",)
    assert not list((tmp_path / "knowledge-vault").rglob("*.md"))


@pytest.mark.asyncio
async def test_list_and_get_restore_markdown_from_disk(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = await service.create(_command(title="first"))
    second = await service.create(_command(title="second"))

    assert await service.get(first.id) == first
    assert await service.list() == (first, second)


@pytest.mark.asyncio
async def test_update_increments_version_and_rejects_stale_version(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    created = await service.create(_command())

    updated = await service.update(
        created.id,
        UpdateDraftCommand(
            expected_version=created.version,
            title="缓存击穿",
            markdown="# 缓存击穿\n",
        ),
    )

    assert updated.version == 2
    assert updated.title == "缓存击穿"
    assert updated.markdown == "# 缓存击穿\n"
    assert updated.content_hash != created.content_hash
    with pytest.raises(DraftVersionChangedError):
        await service.update(
            created.id,
            UpdateDraftCommand(
                expected_version=created.version,
                markdown="# stale\n",
            ),
        )


@pytest.mark.asyncio
async def test_update_rejects_draft_file_changed_outside_service(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    created = await service.create(_command())
    path = tmp_path / created.content_path
    path.write_text("# external edit\n", encoding="utf-8")

    with pytest.raises(DraftContentChangedError):
        await service.update(
            created.id,
            UpdateDraftCommand(
                expected_version=created.version,
                markdown="# replacement\n",
            ),
        )

    assert path.read_text(encoding="utf-8") == "# external edit\n"
