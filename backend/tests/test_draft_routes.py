import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_agent_runtime, get_workspace_service
from app.db.app_database import connect_app_database
from app.knowledge.drafts import CreateDraftCommand, KnowledgeDraftService
from app.main import app
from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.service import AgentRuntime
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def draft_client(tmp_path: Path):
    roots = {"w1": tmp_path / "workspace-one", "w2": tmp_path / "workspace-two"}
    for root in roots.values():
        root.mkdir()
    runtime = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda workspace_id: roots[workspace_id],
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: tuple(roots),
    )
    connection = connect_app_database(tmp_path / "app-data")
    workspaces = WorkspaceService(connection)
    first = workspaces.register(str(roots["w1"]))
    second = workspaces.register(str(roots["w2"]))
    roots[first.id] = roots.pop("w1")
    roots[second.id] = roots.pop("w2")
    app.dependency_overrides[get_agent_runtime] = lambda: runtime
    app.dependency_overrides[get_workspace_service] = lambda: workspaces
    try:
        with TestClient(app) as client:
            yield client, runtime, roots, first.id, second.id
    finally:
        app.dependency_overrides.clear()
        asyncio.run(runtime.close())
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


def test_publish_request_returns_run_without_writing_vault(draft_client) -> None:
    client, _runtime, roots, workspace_id, _second_id = draft_client
    draft = _create_draft(roots[workspace_id], workspace_id)

    response = client.post(
        f"/api/knowledge/drafts/{draft.id}/publish-request"
    )

    assert response.status_code == 202
    body = response.json()
    assert body["sessionId"]
    assert body["runId"]
    assert body["status"] in {"running", "waiting_for_approval"}
    assert not list((roots[workspace_id] / "knowledge-vault").rglob("*.md"))
    assert str(roots[workspace_id]) not in response.text

    # The publish graph runs asynchronously; wait for the run to fully
    # reach waiting_for_approval so the fixture teardown does not abort
    # the graph task mid-flight and leak state into later tests. Polling
    # the run status (not just the action) guarantees the RunManager has
    # finished transitioning the run and the task is gone from _tasks.
    session_id = body["sessionId"]
    for _ in range(100):
        detail = client.get(f"/api/agent/sessions/{session_id}").json()
        latest_run = detail.get("latestRun")
        if latest_run and latest_run.get("status") == "waiting_for_approval":
            break
        asyncio.run(asyncio.sleep(0.01))
    else:
        raise AssertionError("publish run did not reach waiting_for_approval")


def test_unknown_draft_returns_typed_404(draft_client) -> None:
    client, _runtime, _roots, _first_id, _second_id = draft_client

    response = client.get("/api/knowledge/drafts/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "draft_not_found"
