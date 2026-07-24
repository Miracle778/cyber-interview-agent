from __future__ import annotations

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
    roots = {"w1": tmp_path / "w1", "w2": tmp_path / "w2"}
    for root in roots.values():
        root.mkdir()
    value = AgentApplication(
        workspace_resolver=lambda workspace_id: roots[workspace_id],
        workspace_ids=lambda: ("w1", "w2"),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )
    app.dependency_overrides[get_agent_application] = lambda: value
    try:
        yield value
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await value.close()


@pytest.fixture
def client(application):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create(
    client: AsyncClient,
    *,
    category: str,
    value: dict[str, object],
    key: str,
    relations: list[dict[str, str]] | None = None,
):
    return await client.post(
        "/api/workspaces/w1/profile/cards",
        json={
            "workspaceId": "w1",
            "category": category,
            "value": value,
            "expectedVersion": 0,
            "relations": relations or [],
        },
        headers={"Idempotency-Key": key},
    )


@pytest.mark.asyncio
async def test_manual_card_lifecycle_is_versioned_and_profile_has_no_raw_evidence(
    client: AsyncClient,
) -> None:
    async with client:
        empty = await client.get("/api/workspaces/w1/profile")
        assert empty.status_code == 200
        assert empty.json()["isUsable"] is False

        created = await _create(
            client,
            category="project",
            value={"name": "Interview Agent", "role": "Owner"},
            key="api-project-create",
        )
        replay = await _create(
            client,
            category="project",
            value={"name": "Interview Agent", "role": "Owner"},
            key="api-project-create",
        )
        assert created.status_code == 201, created.text
        assert replay.json() == created.json()
        claim_id = created.json()["claimId"]
        first_version_id = created.json()["claimVersionId"]

        profile = await client.get("/api/workspaces/w1/profile")
        payload = profile.json()
        assert payload["projects"][0]["title"] == "Interview Agent"
        assert payload["projects"][0]["sources"][0]["label"] == "本人补充"
        assert all(
            forbidden not in profile.text
            for forbidden in ("sanitizedText", "storageRef", "textRef", "excerpt")
        )

        updated = await client.patch(
            f"/api/profile/cards/{claim_id}",
            json={
                "workspaceId": "w1",
                "category": "project",
                "value": {
                    "name": "Interview Agent",
                    "role": "Owner",
                    "results": ["Released"],
                },
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "api-project-update"},
        )
        stale = await client.patch(
            f"/api/profile/cards/{claim_id}",
            json={
                "workspaceId": "w1",
                "category": "project",
                "value": {"name": "Stale"},
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "api-project-stale"},
        )
        assert updated.status_code == 200, updated.text
        assert stale.status_code == 409
        assert stale.json()["code"] == "profile_claim_version_conflict"

        history = await client.get(
            f"/api/profile/cards/{claim_id}/versions",
            params={"workspaceId": "w1"},
        )
        assert [item["version"] for item in history.json()] == [2, 1]

        restored = await client.post(
            f"/api/profile/cards/{claim_id}/restore",
            json={
                "workspaceId": "w1",
                "sourceVersionId": first_version_id,
                "expectedVersion": 2,
            },
            headers={"Idempotency-Key": "api-project-restore"},
        )
        sources = await client.get(
            f"/api/profile/cards/{claim_id}/sources",
            params={"workspaceId": "w1"},
        )
        assert restored.json()["version"] == 3
        assert sources.json()[0]["label"] == "本人补充"

        deleted = await client.request(
            "DELETE",
            f"/api/profile/cards/{claim_id}",
            json={"workspaceId": "w1", "expectedVersion": 3},
            headers={"Idempotency-Key": "api-project-delete"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"
        assert (await client.get("/api/workspaces/w1/profile")).json()["projects"] == []


@pytest.mark.asyncio
async def test_relations_presentation_and_workspace_isolation(
    client: AsyncClient,
) -> None:
    async with client:
        experience = await _create(
            client,
            category="experience",
            value={"organization": "Example", "title": "Backend Engineer"},
            key="api-experience-create",
        )
        project = await _create(
            client,
            category="project",
            value={"name": "Interview Agent"},
            relations=[
                {
                    "relationType": "belongs_to",
                    "targetClaimId": experience.json()["claimId"],
                }
            ],
            key="api-related-project",
        )
        skill = await _create(
            client,
            category="skill",
            value={"name": "Python"},
            relations=[
                {
                    "relationType": "used_in",
                    "targetClaimId": project.json()["claimId"],
                }
            ],
            key="api-related-skill",
        )
        direction = await _create(
            client,
            category="direction",
            value={"name": "Agent 应用工程"},
            key="api-direction-create",
        )
        highlight = await _create(
            client,
            category="highlight",
            value={"text": "构建可恢复的 Agent 工作流"},
            key="api-highlight-create",
        )
        presentation = await client.patch(
            "/api/workspaces/w1/profile/presentation",
            json={
                "workspaceId": "w1",
                "primaryDirectionClaimId": direction.json()["claimId"],
                "featuredClaimIds": [highlight.json()["claimId"]],
                "expectedVersion": 0,
            },
            headers={"Idempotency-Key": "api-presentation-update"},
        )
        assert presentation.status_code == 200, presentation.text

        profile = (await client.get("/api/workspaces/w1/profile")).json()
        assert profile["primaryDirectionClaimId"] == direction.json()["claimId"]
        assert profile["highlights"][0]["claimId"] == highlight.json()["claimId"]
        assert profile["projects"][0]["linkedTo"][0]["claimId"] == experience.json()[
            "claimId"
        ]
        assert profile["skills"][0]["usedIn"][0]["claimId"] == project.json()[
            "claimId"
        ]

        foreign = await client.patch(
            f"/api/profile/cards/{skill.json()['claimId']}",
            json={
                "workspaceId": "w2",
                "category": "skill",
                "value": {"name": "Python"},
                "expectedVersion": 1,
            },
            headers={"Idempotency-Key": "api-foreign-update"},
        )
        assert foreign.status_code == 404
