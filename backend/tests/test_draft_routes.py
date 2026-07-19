import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_agent_application, get_workspace_service
from app.application.graph_factory import ProductionGraphFactory
from app.application.workspace_runtime import AgentApplication
from app.db.app_database import connect_app_database
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.main import app
from app.review.models import QuestionSnapshot
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def draft_client(tmp_path: Path):
    roots = {"w1": tmp_path / "workspace-one", "w2": tmp_path / "workspace-two"}
    for root in roots.values():
        root.mkdir()
    application = AgentApplication(
        workspace_resolver=lambda workspace_id: roots[workspace_id],
        model_bindings=lambda _workspace_id: {},
        workspace_ids=lambda: tuple(roots),
        graph_factory=ProductionGraphFactory(None),
    )
    connection = connect_app_database(tmp_path / "app-data")
    workspaces = WorkspaceService(connection)
    first = workspaces.register(str(roots["w1"]))
    second = workspaces.register(str(roots["w2"]))
    roots[first.id] = roots.pop("w1")
    roots[second.id] = roots.pop("w2")
    app.dependency_overrides[get_agent_application] = lambda: application
    app.dependency_overrides[get_workspace_service] = lambda: workspaces
    try:
        with TestClient(app) as client:
            yield client, application, roots, first.id, second.id
    finally:
        app.dependency_overrides.clear()
        asyncio.run(application.close())
        connection.close()


def _create_draft(root: Path, workspace_id: str, *, title: str = "Original"):
    return asyncio.run(
        KnowledgeDraftService(root, workspace_id=workspace_id).create(
            CreateDraftCommand(
                domain="review",
                document_type="question",
                document_id=f"question-{workspace_id}",
                title=title,
                markdown=f"# {title}\n",
                source_refs=(),
                relation_refs=(),
            )
        )
    )


def test_list_filters_by_workspace_and_detail_returns_body(draft_client) -> None:
    client, _runtime, roots, first_id, second_id = draft_client
    first = _create_draft(roots[first_id], first_id, title="First")
    _create_draft(roots[second_id], second_id, title="Second")

    listed = client.get(
        "/api/knowledge/drafts", params={"workspaceId": first_id}
    )
    detail = client.get(f"/api/knowledge/drafts/{first.id}")

    assert listed.status_code == 200
    assert [item["title"] for item in listed.json()] == ["First"]
    assert detail.status_code == 200
    assert detail.json()["markdown"] == "# First\n"
    assert str(roots[first_id]) not in listed.text + detail.text


def test_patch_updates_version_and_stale_version_is_typed_conflict(
    draft_client,
) -> None:
    client, _runtime, roots, workspace_id, _second_id = draft_client
    draft = _create_draft(roots[workspace_id], workspace_id)

    updated = client.patch(
        f"/api/knowledge/drafts/{draft.id}",
        json={"version": 1, "title": "Edited", "markdown": "# Edited\n"},
    )
    stale = client.patch(
        f"/api/knowledge/drafts/{draft.id}",
        json={"version": 1, "markdown": "# Stale\n"},
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["title"] == "Edited"
    assert stale.status_code == 409
    assert stale.json()["code"] == "draft_version_changed"


def test_publish_request_returns_ready_action_without_writing_vault(draft_client) -> None:
    client, _runtime, roots, workspace_id, _second_id = draft_client
    draft = _create_draft(roots[workspace_id], workspace_id)

    response = client.post(
        f"/api/knowledge/drafts/{draft.id}/publish-request"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["sessionId"]
    assert body["executionId"]
    assert body["status"] == "waiting_for_approval"
    assert body["reused"] is False
    assert body["action"]["executionId"] == body["executionId"]
    assert body["action"]["status"] == "pending"
    assert not list((roots[workspace_id] / "knowledge-vault").rglob("*.md"))
    assert str(roots[workspace_id]) not in response.text

    session_id = body["sessionId"]
    detail = client.get(f"/api/agent/sessions/{session_id}").json()
    assert detail["latestExecution"]["status"] == "waiting_for_approval"

    pending = client.get(f"/api/knowledge/drafts/{draft.id}")
    assert pending.json()["status"] == "review_pending"


def test_repeated_publish_request_reuses_existing_pending_action(draft_client) -> None:
    client, _runtime, roots, workspace_id, _second_id = draft_client
    draft = _create_draft(roots[workspace_id], workspace_id)

    first = client.post(f"/api/knowledge/drafts/{draft.id}/publish-request")
    second = client.post(f"/api/knowledge/drafts/{draft.id}/publish-request")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["reused"] is True
    assert second.json()["executionId"] == first.json()["executionId"]
    assert second.json()["action"]["id"] == first.json()["action"]["id"]


def test_approval_exposes_vault_publication_result(draft_client) -> None:
    client, _runtime, _roots, workspace_id, _second_id = draft_client
    draft = _create_draft(_roots[workspace_id], workspace_id)

    requested = client.post(
        f"/api/knowledge/drafts/{draft.id}/publish-request"
    ).json()
    for _ in range(100):
        actions = client.get(
            "/api/agent/actions",
            params={"workspaceId": workspace_id, "status": "pending"},
        ).json()
        action = next(
            (item for item in actions if item["executionId"] == requested["executionId"]),
            None,
        )
        if action is not None:
            break
        asyncio.run(asyncio.sleep(0.01))
    else:
        raise AssertionError("publication action did not appear")

    approved = client.post(
        f"/api/agent/actions/{action['id']}/approve",
        json={
            "version": action["version"],
            "idempotencyKey": "publish-route-approve",
        },
    )
    detail = client.get(f"/api/knowledge/drafts/{draft.id}")

    assert approved.status_code == 200
    assert detail.json()["status"] == "published"
    assert detail.json()["publication"] == {
        "state": "completed",
        "targetPath": f"10_question_bank/question-{workspace_id}.md",
        "errorCode": None,
    }


def test_rejection_marks_the_bound_draft_rejected(draft_client) -> None:
    client, runtime, roots, workspace_id, _second_id = draft_client
    draft = _create_draft(roots[workspace_id], workspace_id)
    curation_session = asyncio.run(
        runtime.create_session(
            workspace_id=workspace_id,
            kind="question.curate",
            title="题目整理",
        )
    )
    review = runtime.review(workspace_id)
    batch = review.repository.create_batch(
        workspace_id=workspace_id,
        session_id=curation_session.id,
        run_id=None,
        source_refs=(),
    )
    candidate = review.repository.save_candidate(
        batch_id=batch.id,
        draft_id=draft.id,
        status="review_pending",
        question=QuestionSnapshot(
            question_id="question-rejected",
            document_id=draft.document_id,
            content_hash=draft.content_hash,
            title=draft.title,
            question_text="为什么需要退回？",
            reference_answer="内容需要修正。",
            topics=("review",),
            difficulty="medium",
            key_points=("退回原因",),
            follow_ups=(),
        ),
    )
    requested = client.post(
        f"/api/knowledge/drafts/{draft.id}/publish-request"
    ).json()
    action = requested["action"]

    rejected = client.post(
        f"/api/agent/actions/{action['id']}/reject",
        json={
            "version": action["version"],
            "idempotencyKey": "publish-route-reject",
            "reason": "内容不准确",
        },
    )
    detail = client.get(f"/api/knowledge/drafts/{draft.id}")
    candidate_detail = client.get(
        f"/api/review/question-candidates/{candidate.id}"
    )

    assert rejected.status_code == 200
    assert detail.json()["status"] == "rejected"
    assert candidate_detail.json()["status"] == "rejected"
    assert candidate_detail.json()["rejectionReason"] == "内容不准确"
    assert candidate_detail.json()["rejectedAt"]
    assert candidate_detail.json()["rejectionActionId"] == action["id"]
    assert detail.json()["publication"] is None
    assert not list((roots[workspace_id] / "knowledge-vault").rglob("*.md"))

    revised = client.patch(
        f"/api/review/question-candidates/{candidate.id}",
        json={
            "version": draft.version,
            "title": "修正后的题目",
            "questionText": "如何修正后重新审批？",
            "referenceAnswer": "保存新版本后重新提交。",
            "keyPoints": ["新版本"],
        },
    )
    requested_again = client.post(
        f"/api/knowledge/drafts/{draft.id}/publish-request"
    )

    assert revised.status_code == 200
    assert revised.json()["status"] == "review_pending"
    assert revised.json()["draft"]["status"] == "review_pending"
    assert revised.json()["draft"]["version"] == draft.version + 1
    assert revised.json()["rejectionReason"] is None
    assert requested_again.status_code == 202
    assert requested_again.json()["action"]["id"] != action["id"]


def test_unknown_draft_returns_typed_404(draft_client) -> None:
    client, _runtime, _roots, _first_id, _second_id = draft_client

    response = client.get("/api/knowledge/drafts/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "draft_not_found"
