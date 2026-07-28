from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.main import app
from app.profile.models import CreateClaimProposalSpec


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


async def _prepare_workspace(
    client: AsyncClient, application: AgentApplication, workspace_id: str
) -> dict[str, str]:
    uploaded = await client.post(
        f"/api/workspaces/{workspace_id}/profile/materials",
        data={"title": "后端工程师简历", "primaryRole": "resume"},
        files={"file": ("resume.md", b"project and private contact", "text/markdown")},
        headers={"Idempotency-Key": f"context-upload-{workspace_id}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    version_id = uploaded.json()["versionId"]
    service = application.profile(workspace_id)
    normal, sensitive = service.repository.replace_version_evidence(
        version_id,
        (
            {
                "section": "project",
                "start_offset": 0,
                "end_offset": 7,
                "sanitized_text": "private project implementation details",
                "content_sha256": "a" * 64,
                "sensitivity": "normal",
            },
            {
                "section": "contact",
                "start_offset": 8,
                "end_offset": 23,
                "sanitized_text": "private@example.com",
                "content_sha256": "b" * 64,
                "sensitivity": "sensitive",
            },
        ),
    )
    project, pending_skill, private_link = service.repository.create_claim_proposals(
        version_id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": "project",
                    "name": "Interview Agent",
                    "description": "Built a recoverable workflow",
                    "email": "private@example.com",
                },
                reason="项目描述明确",
                evidence_ids=(normal.id,),
            ),
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "name": "Python"},
                reason="技能待确认",
                evidence_ids=(normal.id,),
            ),
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": "link",
                    "label": "Private profile",
                    "url": "https://example.invalid/private",
                },
                reason="联系方式",
                evidence_ids=(sensitive.id,),
            ),
        ),
    )
    accepted_project = service.decide_claim_proposal(
        project.id,
        decision="accepted",
        expected_version=0,
        idempotency_key=f"context-accept-project-{workspace_id}",
    )
    accepted_link = service.decide_claim_proposal(
        private_link.id,
        decision="accepted",
        expected_version=0,
        idempotency_key=f"context-accept-link-{workspace_id}",
    )
    return {
        "project_claim_id": accepted_project.claim_id or "",
        "project_version_id": accepted_project.claim_version_id or "",
        "link_claim_id": accepted_link.claim_id or "",
        "pending_proposal_id": pending_skill.id,
        "normal_evidence_id": normal.id,
    }


@pytest.mark.asyncio
async def test_confirmed_context_is_current_bounded_and_sensitive_safe(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        prepared = await _prepare_workspace(client, application, "w1")
        response = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={
                "purpose": "job_target_analysis",
                "claimTypes": ["project", "skill", "link"],
                "sensitiveDataPolicy": "exclude",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["purpose"] == "job_target_analysis"
        assert [item["claimId"] for item in payload["items"]] == [
            prepared["project_claim_id"]
        ]
        assert payload["items"][0]["evidenceIds"] == [
            prepared["normal_evidence_id"]
        ]
        assert payload["items"][0]["supportStatus"] == "supported"
        assert "email" not in payload["items"][0]["value"]
        assert "private project implementation details" not in response.text
        assert "private@example.com" not in response.text

        service = application.profile("w1")
        claim = service.repository.get_claim(prepared["project_claim_id"])
        current = service.repository.get_claim_version(
            claim.current_confirmed_version_id or ""
        )
        update = service.repository.create_claim_proposals(
            service.repository.get_evidence(
                prepared["normal_evidence_id"]
            ).material_version_id,
            (
                CreateClaimProposalSpec(
                    proposal_type="update",
                    target_claim_id=claim.id,
                    base_claim_version_id=current.id,
                    proposed_value={
                        "category": "project",
                        "name": "Interview Agent v2",
                    },
                    reason="用户补充",
                    evidence_ids=(prepared["normal_evidence_id"],),
                ),
            ),
        )[0]
        accepted_update = service.decide_claim_proposal(
            update.id,
            decision="accepted",
            expected_version=claim.version,
            idempotency_key="context-accept-update-w1",
        )
        refreshed = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={"purpose": "project_deep_dive", "claimIds": [claim.id]},
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["items"][0]["claimVersionId"] == (
            accepted_update.claim_version_id
        )
        assert refreshed.json()["items"][0]["value"]["name"] == "Interview Agent v2"


@pytest.mark.asyncio
async def test_confirmed_context_reflects_support_and_enforces_workspace_scope(
    client: AsyncClient, application: AgentApplication
) -> None:
    async with client:
        first = await _prepare_workspace(client, application, "w1")
        second = await _prepare_workspace(client, application, "w2")
        service = application.profile("w1")
        service.repository.connection.execute(
            "UPDATE profile_evidence SET sanitized_text = '', "
            "tombstoned_at = CURRENT_TIMESTAMP WHERE id = ?",
            (first["normal_evidence_id"],),
        )
        service.repository.connection.execute(
            "UPDATE profile_claim_sources SET status = 'source_deleted' "
            "WHERE claim_version_id = ?",
            (first["project_version_id"],),
        )
        service.repository.connection.commit()
        service.repository.mark_claim_unsupported(
            first["project_claim_id"], reason="source deleted"
        )
        unsupported = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={
                "purpose": "interview_training",
                "claimIds": [first["project_claim_id"]],
            },
        )
        assert unsupported.status_code == 200, unsupported.text
        assert unsupported.json()["items"][0]["supportStatus"] == "unsupported"

        foreign = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={
                "purpose": "job_target_analysis",
                "claimIds": [second["project_claim_id"]],
            },
        )
        assert foreign.status_code == 404
        assert foreign.json()["code"] == "profile_claim_not_found"


@pytest.mark.asyncio
async def test_confirmed_context_returns_stable_empty_and_validates_purpose(
    client: AsyncClient,
) -> None:
    async with client:
        empty = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={"purpose": "job_target_analysis"},
        )
        assert empty.status_code == 200, empty.text
        assert empty.json()["profileVersion"] is None
        assert empty.json()["items"] == []

        invalid = await client.post(
            "/api/workspaces/w1/profile/confirmed-context",
            json={"purpose": "general_chat"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "invalid_request"
