from pathlib import Path

import pytest

from app.infrastructure.runtime_database import connect_runtime_database
from app.db.connection import connect_index
from app.hitl.models import CreatePendingAction
from app.hitl.repository import PendingActionRepository
from app.knowledge.atomic_writer import ExternalDocumentChangedError
from app.knowledge.drafts import (
    CreateDraftCommand,
    DraftContentChangedError,
    DraftNotEditableError,
    DraftVersionChangedError,
    KnowledgeDraftService,
    UpdateDraftCommand,
)
from app.knowledge.frontmatter import (
    PublishedDocument,
    PublishedProvenance,
    render_published_document,
)
from app.knowledge.publication import PublicationRepository, PublicationService
from app.knowledge.publication_handler import KnowledgePublishActionHandler
from app.application.session_service import ProductRepository
from app.services.search_index import rescan_active_documents
from app.services.vault import initialize_vault


class RecordingEvents:
    async def publish(self, *_args, **_kwargs):
        return None


async def _resolved_action(workspace: Path, draft):
    connection = connect_runtime_database(workspace)
    repository = PendingActionRepository(workspace)
    action = await repository.create(CreatePendingAction(
        workspace_id="w1", session_id="s1", run_id="r1", action_type="knowledge.publish",
        payload={"draftId": draft.id, "draftVersion": draft.version, "contentHash": draft.content_hash, "title": draft.title, "markdown": draft.markdown},
        preview={"title": draft.title, "markdown": draft.markdown},
        editable_fields=("title", "markdown"), idempotency_key=f"publish:{draft.id}:1",
    ))
    await repository.resolve(action.id, expected_version=1, status="approved", resolution_key="approve-1", decision={"decision": "approved"})
    resolved = await repository.get(action.id)
    connection.close()
    return resolved


async def _draft(workspace: Path):
    connection = connect_runtime_database(workspace)
    runtime = ProductRepository(connection)
    runtime.create_session(workspace_id="w1", kind="knowledge.publish", title="Publish", session_id="s1")
    runtime.create_execution("s1", input={}, model_bindings={}, execution_id="r1")
    connection.close()
    service = KnowledgeDraftService(workspace, workspace_id="w1")
    return await service.create(CreateDraftCommand(
        domain="review", document_type="question", document_id="question-1", title="缓存穿透",
        markdown="# 缓存穿透\n", source_refs=("source-1",), relation_refs=(),
        session_id="s1", run_id="r1", agent_type="review",
    ))


def _rendered_publication(draft, action) -> str:
    return render_published_document(PublishedDocument(
        id=draft.document_id,
        type=draft.document_type,
        title=draft.title,
        markdown=draft.markdown,
        source_refs=draft.source_refs,
        relation_refs=draft.relation_refs,
        published_at=action.resolved_at or action.created_at,
        provenance=PublishedProvenance(
            agent_type=draft.agent_type,
            session_id=draft.session_id,
            run_id=draft.run_id,
        ),
    ))


@pytest.mark.asyncio
async def test_publish_is_idempotent_and_marks_draft_published(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    service = PublicationService(tmp_path, workspace_id="w1")

    first = await service.publish_approved_action(action)
    second = await service.publish_approved_action(action)

    assert first == second
    assert first.state == "completed"
    assert first.target_path == "10_question_bank/question-1.md"
    assert len(list((tmp_path / "knowledge-vault/10_question_bank").glob("*.md"))) == 1
    assert (await KnowledgeDraftService(tmp_path, workspace_id="w1").get(draft.id)).status == "published"


@pytest.mark.asyncio
async def test_prepared_claim_resumes_after_service_restart(
    tmp_path: Path,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    prepared = await PublicationRepository(tmp_path).prepare(
        action, draft, "10_question_bank/question-1.md"
    )

    resumed = await PublicationService(
        tmp_path, workspace_id="w1"
    ).publish_approved_action(action)

    assert resumed.id == prepared.id
    assert resumed.state == "completed"
    assert (
        tmp_path / "knowledge-vault/10_question_bank/question-1.md"
    ).is_file()


@pytest.mark.asyncio
async def test_source_mutation_after_claim_fails_before_vault_write_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    service = PublicationService(tmp_path, workspace_id="w1")
    original_prepare = service._repository.prepare
    source = tmp_path / draft.content_path

    async def prepare_then_mutate(*args, **kwargs):
        publication = await original_prepare(*args, **kwargs)
        source.write_text("# mutated after claim\n", encoding="utf-8")
        return publication

    monkeypatch.setattr(service._repository, "prepare", prepare_then_mutate)

    with pytest.raises(DraftContentChangedError):
        await service.publish_approved_action(action)

    target = tmp_path / "knowledge-vault/10_question_bank/question-1.md"
    assert not target.exists()
    assert not (
        tmp_path / "knowledge-vault/.cyber-interview-agent/index.sqlite"
    ).exists()
    connection = connect_runtime_database(tmp_path)
    assert connection.execute(
        "SELECT status FROM knowledge_drafts WHERE id = ?", (draft.id,)
    ).fetchone()[0] == "draft"
    publication = connection.execute(
        "SELECT id, state, result_hash FROM publication_runs WHERE draft_id = ?",
        (draft.id,),
    ).fetchone()
    assert tuple(publication)[1:] == ("prepared", None)
    connection.close()

    source.write_text(draft.markdown, encoding="utf-8")
    monkeypatch.setattr(service._repository, "prepare", original_prepare)
    retried = await PublicationService(
        tmp_path, workspace_id="w1"
    ).publish_approved_action(action)
    assert retried.id == publication[0]
    assert retried.state == "completed"


@pytest.mark.asyncio
async def test_mark_failure_preserves_preexisting_matching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    vault = initialize_vault(tmp_path)
    target = vault / "10_question_bank/question-1.md"
    rendered = _rendered_publication(draft, action)
    target.write_text(rendered, encoding="utf-8")
    service = PublicationService(tmp_path, workspace_id="w1")

    async def fail_mark(*_args, **_kwargs):
        raise DraftVersionChangedError("forced mark failure")

    monkeypatch.setattr(service._drafts, "mark_published", fail_mark)

    with pytest.raises(DraftVersionChangedError, match="forced mark failure"):
        await service.publish_approved_action(action)

    assert target.read_text(encoding="utf-8") == rendered
    publication = await service.latest_for_draft(draft.id)
    assert publication is not None
    assert publication.state == "prepared"
    assert publication.result_hash is None


@pytest.mark.asyncio
async def test_source_mutation_after_new_target_compensates_matching_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    service = PublicationService(tmp_path, workspace_id="w1")
    source = tmp_path / draft.content_path
    target = tmp_path / "knowledge-vault/10_question_bank/question-1.md"
    original_mark = service._drafts.mark_published

    async def mutate_source_then_mark(*args, **kwargs):
        source.write_text("# mutated after Vault write\n", encoding="utf-8")
        return await original_mark(*args, **kwargs)

    monkeypatch.setattr(
        service._drafts, "mark_published", mutate_source_then_mark
    )

    with pytest.raises(DraftContentChangedError):
        await service.publish_approved_action(action)

    assert not target.exists()
    publication = await service.latest_for_draft(draft.id)
    assert publication is not None
    assert publication.state == "prepared"
    assert publication.result_hash is None
    connection = connect_runtime_database(tmp_path)
    assert connection.execute(
        "SELECT status FROM knowledge_drafts WHERE id = ?", (draft.id,)
    ).fetchone()[0] == "draft"
    connection.close()


@pytest.mark.asyncio
async def test_compensation_preserves_new_target_when_its_hash_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    service = PublicationService(tmp_path, workspace_id="w1")
    target = tmp_path / "knowledge-vault/10_question_bank/question-1.md"

    async def replace_target_then_fail(*_args, **_kwargs):
        target.write_text("external replacement", encoding="utf-8")
        raise DraftVersionChangedError("forced mark failure")

    monkeypatch.setattr(
        service._drafts, "mark_published", replace_target_then_fail
    )

    with pytest.raises(DraftVersionChangedError, match="forced mark failure"):
        await service.publish_approved_action(action)

    assert target.read_text(encoding="utf-8") == "external replacement"
    publication = await service.latest_for_draft(draft.id)
    assert publication is not None
    assert publication.state == "failed"
    assert publication.error_code == "publication_compensation_conflict"


@pytest.mark.asyncio
async def test_publish_rejects_changed_draft_version(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    await drafts.update(draft.id, UpdateDraftCommand(expected_version=1, markdown="# changed\n"))

    with pytest.raises(DraftVersionChangedError):
        await PublicationService(tmp_path, workspace_id="w1").publish_approved_action(action)


@pytest.mark.asyncio
async def test_publish_rejects_retired_draft(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    await drafts.mark_rejected(
        draft.id,
        expected_version=draft.version,
        expected_hash=draft.content_hash,
    )

    with pytest.raises(DraftNotEditableError):
        await PublicationService(
            tmp_path, workspace_id="w1"
        ).publish_approved_action(action)


@pytest.mark.asyncio
async def test_publish_rejects_superseded_draft(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "UPDATE knowledge_drafts SET status = 'superseded' WHERE id = ?",
        (draft.id,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DraftNotEditableError):
        await PublicationService(
            tmp_path, workspace_id="w1"
        ).publish_approved_action(action)


@pytest.mark.asyncio
async def test_prepare_rechecks_draft_before_claim_when_supersession_wins(
    tmp_path: Path,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "UPDATE knowledge_drafts SET status = 'superseded', "
        "version = version + 1 WHERE id = ?",
        (draft.id,),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DraftVersionChangedError):
        await PublicationRepository(tmp_path).prepare(
            action, draft, "10_question_bank/question-1.md"
        )

    connection = connect_runtime_database(tmp_path)
    assert connection.execute(
        "SELECT COUNT(*) FROM publication_runs WHERE draft_id = ?",
        (draft.id,),
    ).fetchone()[0] == 0
    connection.close()
    assert not (tmp_path / "knowledge-vault").exists()


@pytest.mark.asyncio
async def test_publish_preserves_external_target(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    initialize_vault(tmp_path)
    target = tmp_path / "knowledge-vault/10_question_bank/question-1.md"
    target.write_text("external", encoding="utf-8")

    with pytest.raises(ExternalDocumentChangedError):
        await PublicationService(tmp_path, workspace_id="w1").publish_approved_action(action)

    assert target.read_text(encoding="utf-8") == "external"


@pytest.mark.asyncio
async def test_index_failure_keeps_markdown_and_marks_index_stale(tmp_path: Path) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)

    def fail_index(*_args):
        raise RuntimeError("index unavailable")

    result = await PublicationService(tmp_path, workspace_id="w1", index_document=fail_index).publish_approved_action(action)

    assert result.state == "index_stale"
    assert result.error_code == "publication_index_failed"
    assert (tmp_path / "knowledge-vault" / result.target_path).is_file()

    vault = tmp_path / "knowledge-vault"
    connection = connect_index(vault / ".cyber-interview-agent/index.sqlite")
    rescan_active_documents(connection, vault)
    connection.close()
    repaired = await PublicationService(
        tmp_path, workspace_id="w1"
    ).repair_index_stale_after_rescan()
    assert repaired == 1


@pytest.mark.asyncio
async def test_publish_handler_projects_the_final_published_draft(
    tmp_path: Path,
) -> None:
    draft = await _draft(tmp_path)
    action = await _resolved_action(tmp_path, draft)
    projected = []

    async def after_publication(final_draft, publication):
        projected.append((final_draft, publication))

    handler = KnowledgePublishActionHandler(
        drafts=KnowledgeDraftService(tmp_path, workspace_id="w1"),
        publications=PublicationService(tmp_path, workspace_id="w1"),
        event_stream=RecordingEvents(),
        after_publication=after_publication,
    )

    await handler.after_resolution(action, None)  # type: ignore[arg-type]

    assert len(projected) == 1
    final_draft, publication = projected[0]
    assert final_draft.status == "published"
    assert final_draft.id == draft.id
    assert publication.state == "completed"
