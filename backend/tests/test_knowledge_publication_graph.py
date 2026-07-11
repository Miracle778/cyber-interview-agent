from pathlib import Path

import pytest

from app.hitl.models import ResolveActionCommand
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.knowledge.publication import PublicationService
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.service import AgentRuntime


async def _runtime_and_draft(tmp_path: Path):
    runtime = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    drafts = KnowledgeDraftService(tmp_path, workspace_id="w1")
    draft = await drafts.create(CreateDraftCommand(
        domain="review", document_type="question", document_id="q1",
        title="Original", markdown="# Original\n", source_refs=(), relation_refs=(),
    ))
    return runtime, drafts, draft


@pytest.mark.asyncio
async def test_publish_graph_waits_for_approval_then_completes(tmp_path: Path) -> None:
    runtime, drafts, draft = await _runtime_and_draft(tmp_path)
    run = await runtime.request_draft_publication(draft.id)
    waiting = await runtime.wait_run(run.id)
    action = (await runtime.list_actions("w1", status="pending"))[0]

    assert waiting.status == "waiting_for_approval"
    assert action.action_type == "knowledge.publish"
    await runtime.approve_action(action.id, ResolveActionCommand(version=action.version, idempotency_key="approve-1"))
    completed = await runtime.wait_run(run.id)

    assert completed.status == "completed"
    assert (await drafts.get(draft.id)).status == "published"
    assert (tmp_path / "knowledge-vault/10_question_bank/q1.md").is_file()
    await runtime.close()


@pytest.mark.asyncio
async def test_publish_graph_rejection_does_not_write_vault(tmp_path: Path) -> None:
    runtime, drafts, draft = await _runtime_and_draft(tmp_path)
    run = await runtime.request_draft_publication(draft.id)
    await runtime.wait_run(run.id)
    action = (await runtime.list_actions("w1", status="pending"))[0]

    await runtime.reject_action(action.id, ResolveActionCommand(version=action.version, idempotency_key="reject-1", reason="不发布"))
    completed = await runtime.wait_run(run.id)

    assert completed.status == "completed"
    assert (await drafts.get(draft.id)).status == "draft"
    assert not list((tmp_path / "knowledge-vault").rglob("*.md"))
    await runtime.close()


@pytest.mark.asyncio
async def test_edited_approval_publishes_new_draft_version_once(tmp_path: Path) -> None:
    runtime, drafts, draft = await _runtime_and_draft(tmp_path)
    run = await runtime.request_draft_publication(draft.id)
    await runtime.wait_run(run.id)
    action = (await runtime.list_actions("w1", status="pending"))[0]

    await runtime.approve_action(action.id, ResolveActionCommand(
        version=action.version, idempotency_key="approve-edit-1",
        edited_payload={"title": "Edited", "markdown": "# Edited\n"},
    ))
    await runtime.wait_run(run.id)
    updated = await drafts.get(draft.id)

    assert updated.version == 2
    assert updated.status == "published"
    assert updated.title == "Edited"
    assert "# Edited" in (tmp_path / "knowledge-vault/10_question_bank/q1.md").read_text(encoding="utf-8")
    await runtime.close()


@pytest.mark.asyncio
async def test_repeated_request_reuses_waiting_run(tmp_path: Path) -> None:
    runtime, _drafts, draft = await _runtime_and_draft(tmp_path)
    first = await runtime.request_draft_publication(draft.id)
    await runtime.wait_run(first.id)

    second = await runtime.request_draft_publication(draft.id)

    assert second.id == first.id
    assert len(await runtime.list_actions("w1", status="pending")) == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_failed_delivery_is_recovered_without_reapplying_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, drafts, draft = await _runtime_and_draft(tmp_path)
    run = await runtime.request_draft_publication(draft.id)
    await runtime.wait_run(run.id)
    action = (await runtime.list_actions("w1", status="pending"))[0]
    original_publish = PublicationService.publish_approved_action

    async def fail_publish(self, resolved_action):
        del self, resolved_action
        raise RuntimeError("simulated delivery failure")

    monkeypatch.setattr(
        PublicationService, "publish_approved_action", fail_publish
    )
    with pytest.raises(RuntimeError, match="simulated delivery failure"):
        await runtime.approve_action(
            action.id,
            ResolveActionCommand(
                version=action.version,
                idempotency_key="approve-retry-1",
                edited_payload={"title": "Edited", "markdown": "# Edited\n"},
            ),
        )
    assert (await drafts.get(draft.id)).version == 2
    await runtime.close()

    monkeypatch.setattr(
        PublicationService, "publish_approved_action", original_publish
    )
    recovered = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    await recovered.recover_interrupted_runs()
    completed = await recovered.wait_run(run.id)

    assert completed.status == "completed"
    assert (await drafts.get(draft.id)).version == 2
    assert (tmp_path / "knowledge-vault/10_question_bank/q1.md").is_file()
    await recovered.close()
