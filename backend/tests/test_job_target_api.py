from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.main import app


def _graph_factory(_kind: str, **dependencies):
    graph = StateGraph(dict)
    graph.add_node("complete", lambda state: state)
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


@pytest_asyncio.fixture
async def application(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    app.dependency_overrides[get_agent_application] = lambda: value
    try:
        yield value
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await value.close()


@pytest.mark.asyncio
async def test_target_jd_requirement_and_lifecycle_api(application):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/workspaces/w1/job-targets",
            json={
                "roleName": "高级后端工程师",
                "seniority": "5-8 年",
                "companyName": "示例公司",
            },
            headers={"Idempotency-Key": "create-target-api-1"},
        )
        assert created.status_code == 201, created.text
        target = created.json()

        version = await client.post(
            f"/api/job-targets/{target['id']}/document-versions",
            json={
                "workspaceId": "w1",
                "sourceKind": "jd_text",
                "body": "负责高并发服务设计",
            },
            headers={"Idempotency-Key": "create-document-api-1"},
        )
        assert version.status_code == 201, version.text
        confirmed = await client.post(
            f"/api/job-targets/{target['id']}/document-versions/"
            f"{version.json()['id']}/confirm",
            json={
                "workspaceId": "w1",
                "expectedVersion": target["version"],
            },
            headers={"Idempotency-Key": "confirm-document-api-1"},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["currentDocumentVersionId"] == version.json()["id"]

        recycled = await client.post(
            f"/api/job-targets/{target['id']}/recycle",
            json={
                "workspaceId": "w1",
                "expectedVersion": confirmed.json()["version"],
            },
            headers={"Idempotency-Key": "recycle-target-api-1"},
        )
        assert recycled.status_code == 200, recycled.text
        assert recycled.json()["lifecycleStatus"] == "recycled"

        restored = await client.post(
            f"/api/job-targets/{target['id']}/restore",
            json={
                "workspaceId": "w1",
                "expectedVersion": recycled.json()["version"],
            },
            headers={"Idempotency-Key": "restore-target-api-1"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["lifecycleStatus"] == "active"

        listed = await client.get(
            "/api/workspaces/w1/job-targets",
            params={"includeArchived": "true"},
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [target["id"]]
