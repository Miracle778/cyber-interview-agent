from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.application.session_service import ProductRepository
from app.application.workspace_runtime import AgentApplication
from app.knowledge.drafts import (
    CreateDraftCommand,
    DraftContentChangedError,
    DraftVersionChangedError,
    KnowledgeDraftService,
    UpdateDraftCommand,
    stage_draft,
)
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.review.repository import ReviewRepository
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


def _curation_stage_fixture(workspace: Path):
    connection = connect_runtime_database(workspace)
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="question.curate",
        title="Curation",
        session_id="s1",
    )
    product.create_execution(
        "s1", input={}, model_bindings={}, execution_id="r1"
    )
    repository = ReviewRepository(connection)
    repository.create_curation_session(
        workspace_id="w1", session_id="s1", source_refs=("source-1",)
    )
    batch = repository.create_batch(
        workspace_id="w1",
        session_id="s1",
        run_id="r1",
        source_refs=("source-1",),
        batch_id="batch-stage",
    )
    repository.update_curation_progress(
        "s1",
        stage="generating",
        completed_units=0,
        total_units=1,
        active_batch_id=batch.id,
    )
    repository.claim_curation_finalization(batch.id, "r1")
    command = CreateDraftCommand(
        domain="review",
        document_type="question",
        title="缓存穿透",
        markdown="# 缓存穿透\n",
        source_refs=("source-1",),
        relation_refs=(),
        session_id="s1",
        run_id="r1",
        agent_type="question.curate",
        draft_id="staged-draft",
        document_id="staged-document",
    )
    return (
        KnowledgeDraftService(workspace, workspace_id="w1"),
        repository,
        connection,
        batch,
        command,
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


def test_stage_draft_is_idempotent_without_creating_formal_row(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    command = CreateDraftCommand(
        domain="review",
        document_type="question",
        title="缓存穿透",
        markdown="# 缓存穿透\n",
        source_refs=("source-1",),
        relation_refs=(),
        session_id=None,
        run_id=None,
        draft_id="staged-draft",
        document_id="staged-document",
    )

    first = stage_draft(
        tmp_path, workspace_id="w1", command=command
    )
    replayed = stage_draft(
        tmp_path, workspace_id="w1", command=command
    )

    assert first == replayed
    assert (tmp_path / first.content_path).is_file()
    connection = connect_runtime_database(tmp_path)
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE id = ?", (first.id,)
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.asyncio
async def test_curation_stage_is_private_and_cleanup_removes_losing_file(
    tmp_path: Path,
) -> None:
    service, repository, connection, batch, command = (
        _curation_stage_fixture(tmp_path)
    )
    staged = await service.stage_curation_draft(batch.id, command)
    replayed = await service.stage_curation_draft(batch.id, command)
    repository.request_batch_control(
        batch.id,
        operation="pause",
        idempotency_key="pause-before-finalization",
        expected_version=batch.version,
    )

    removed = await service.cleanup_curation_staging(
        batch_id=batch.id, execution_id="r1"
    )

    assert staged == replayed
    assert removed == 1
    assert not (tmp_path / staged.content_path).exists()
    assert connection.execute(
        "SELECT COUNT(*) FROM review_curation_staged_drafts "
        "WHERE draft_id = ?",
        (staged.id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM knowledge_drafts WHERE id = ?", (staged.id,)
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.asyncio
async def test_curation_cleanup_preserves_formally_referenced_file(
    tmp_path: Path,
) -> None:
    service, _repository, connection, batch, command = (
        _curation_stage_fixture(tmp_path)
    )
    staged = await service.stage_curation_draft(batch.id, command)
    connection.execute(
        "INSERT INTO knowledge_drafts "
        "(id, workspace_id, session_id, run_id, agent_type, domain, "
        "document_type, document_id, title, content_path, source_refs_json, "
        "relation_refs_json, status, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', "
        "'review_pending', ?)",
        (
            staged.id,
            staged.workspace_id,
            staged.session_id,
            staged.run_id,
            staged.agent_type,
            staged.domain,
            staged.document_type,
            staged.document_id,
            staged.title,
            staged.content_path,
            staged.content_hash,
        ),
    )
    connection.commit()

    removed = await service.cleanup_curation_staging(
        batch_id=batch.id, execution_id="r1"
    )

    assert removed == 0
    assert (tmp_path / staged.content_path).is_file()
    assert connection.execute(
        "SELECT COUNT(*) FROM review_curation_staged_drafts "
        "WHERE draft_id = ?",
        (staged.id,),
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.asyncio
async def test_curation_cleanup_preserves_hash_mismatch_for_diagnosis(
    tmp_path: Path,
) -> None:
    service, _repository, connection, batch, command = (
        _curation_stage_fixture(tmp_path)
    )
    staged = await service.stage_curation_draft(batch.id, command)
    path = tmp_path / staged.content_path
    path.write_text("external change", encoding="utf-8")

    removed = await service.cleanup_curation_staging(
        batch_id=batch.id, execution_id="r1"
    )

    assert removed == 0
    assert path.read_text(encoding="utf-8") == "external change"
    assert connection.execute(
        "SELECT COUNT(*) FROM review_curation_staged_drafts "
        "WHERE draft_id = ?",
        (staged.id,),
    ).fetchone()[0] == 1
    connection.close()


@pytest.mark.asyncio
async def test_startup_reconciliation_removes_abandoned_staging(
    tmp_path: Path,
) -> None:
    service, _repository, connection, batch, command = (
        _curation_stage_fixture(tmp_path)
    )
    staged = await service.stage_curation_draft(batch.id, command)
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "UPDATE review_question_batches SET status = 'failed' WHERE id = ?",
        (batch.id,),
    )
    connection.commit()

    removed = await service.reconcile_curation_staging()

    assert removed == 1
    assert not (tmp_path / staged.content_path).exists()
    assert connection.execute(
        "SELECT COUNT(*) FROM review_curation_staged_drafts"
    ).fetchone()[0] == 0
    connection.close()


@pytest.mark.asyncio
async def test_application_recovery_reconciles_abandoned_staging(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service, _repository, connection, batch, command = (
        _curation_stage_fixture(workspace)
    )
    staged = await service.stage_curation_draft(batch.id, command)
    connection.execute(
        "UPDATE agent_runs SET status = 'interrupted' WHERE id = 'r1'"
    )
    connection.execute(
        "UPDATE review_question_batches SET status = 'failed' WHERE id = ?",
        (batch.id,),
    )
    connection.commit()
    connection.close()
    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=lambda _kind, **_dependencies: None,
    )

    try:
        await application.recover()
    finally:
        await application.close()

    assert not (workspace / staged.content_path).exists()


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
