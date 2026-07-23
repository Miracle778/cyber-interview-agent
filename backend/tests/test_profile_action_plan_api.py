from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from langgraph.graph import END, START, StateGraph

from app.api.dependencies import get_agent_application
from app.application.workspace_runtime import AgentApplication
from app.main import app
from app.profile.models import (
    ActionPlanItemSpec,
    CreateActionPlanCommand,
    CreateClaimProposalSpec,
)


def _graph_factory(_kind: str, **dependencies):
    graph = StateGraph(dict)
    graph.add_node("complete", lambda _state: {"response": "ok"})
    graph.add_edge(START, "complete")
    graph.add_edge("complete", END)
    return graph.compile(checkpointer=dependencies.get("checkpointer"))


def _application(root: Path) -> AgentApplication:
    return AgentApplication(
        workspace_resolver=lambda _workspace_id: root,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=_graph_factory,
    )


@pytest_asyncio.fixture
async def action_plan_application(tmp_path: Path):
    root = tmp_path / "w1"
    root.mkdir()
    application = _application(root)
    app.dependency_overrides[get_agent_application] = lambda: application
    try:
        yield application
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await application.close()


async def _confirmed_profile(application: AgentApplication):
    service = application.profile("w1")
    uploaded = service.upload_material(
        file_name="resume.txt", content=b"Python", title="Resume"
    )
    await application._context("w1").executions.wait(uploaded.execution_id)
    service.record_ingest_success(uploaded.version.id)
    evidence = service.repository.replace_version_evidence(
        uploaded.version.id,
        (
            {
                "section": "skills",
                "start_offset": 0,
                "end_offset": 6,
                "sanitized_text": "Python",
                "content_sha256": "e" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]
    proposal = service.repository.create_claim_proposals(
        uploaded.version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "Python"},
                reason="resume",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-python",
    )
    session = await application.create_profile_session(
        workspace_id="w1", title="Plan"
    )
    execution = service.product_repository.create_execution(
        session.id, input={}, model_bindings={}, configuration={}
    )
    return service, uploaded, evidence, session, execution


def _plan(service, evidence, session, execution, *, text="FastAPI"):
    return service.create_action_plan(
        CreateActionPlanCommand(
            workspace_id="w1",
            session_id=session.id,
            execution_id=execution.id,
            request_summary=f"添加 {text}",
            base_profile_version=(
                service.repository.profile_snapshot("w1").profile_version or ""
            ),
            items=(
                ActionPlanItemSpec(
                    item_id="item-1",
                    ordinal=1,
                    operation="propose_claim_create",
                    target={},
                    after={"category": "skill", "text": text},
                    evidence_ids=(evidence.id,),
                ),
            ),
        )
    )


@pytest.mark.asyncio
async def test_action_plan_detail_confirm_cancel_and_assessment_resources(
    action_plan_application: AgentApplication,
) -> None:
    service, _uploaded, evidence, session, execution = await _confirmed_profile(
        action_plan_application
    )
    plan = _plan(service, evidence, session, execution)
    assessment = service.save_assessment(
        base_profile_version=plan.base_profile_version,
        result={
            "summary": "基础扎实",
            "recommendations": [{"evidenceIds": [evidence.id]}],
        },
        created_by_execution_id=execution.id,
    )
    service.product_repository.transition_execution(
        execution.id, expected=("running",), target="completed"
    )
    second_execution = service.product_repository.create_execution(
        session.id, input={}, model_bindings={}, configuration={}
    )
    cancellable = _plan(
        service, evidence, session, second_execution, text="LangGraph"
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        detail = await client.get(
            f"/api/profile/action-plans/{plan.id}",
            params={"workspaceId": "w1"},
        )
        confirmed = await client.post(
            f"/api/profile/action-plans/{plan.id}/confirm",
            json={"workspaceId": "w1", "expectedVersion": plan.version},
        )
        cancelled = await client.post(
            f"/api/profile/action-plans/{cancellable.id}/cancel",
            json={
                "workspaceId": "w1",
                "expectedVersion": cancellable.version,
            },
        )
        assessment_response = await client.get(
            f"/api/profile/assessments/{assessment.id}",
            params={"workspaceId": "w1"},
        )

    assert detail.status_code == 200
    assert detail.json()["items"][0]["evidenceIds"] == [evidence.id]
    assert detail.json()["canConfirm"] is True
    assert confirmed.json()["status"] == "completed"
    assert confirmed.json()["items"][0]["receiptId"]
    assert cancelled.json()["status"] == "cancelled"
    assert assessment_response.json()["result"]["summary"] == "基础扎实"


@pytest.mark.asyncio
async def test_stale_plan_returns_409_and_cross_workspace_resources_are_hidden(
    action_plan_application: AgentApplication,
) -> None:
    service, uploaded, evidence, session, execution = await _confirmed_profile(
        action_plan_application
    )
    plan = _plan(service, evidence, session, execution)
    proposal = service.repository.create_claim_proposals(
        uploaded.version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "skill", "text": "SQL"},
                reason="resume",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    service.decide_claim_proposal(
        proposal.id,
        decision="accepted",
        expected_version=0,
        idempotency_key="accept-sql",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        stale_detail = await client.get(
            f"/api/profile/action-plans/{plan.id}",
            params={"workspaceId": "w1"},
        )
        stale_confirm = await client.post(
            f"/api/profile/action-plans/{plan.id}/confirm",
            json={"workspaceId": "w1", "expectedVersion": plan.version},
        )
        hidden = await client.get(
            f"/api/profile/action-plans/{plan.id}",
            params={"workspaceId": "w2"},
        )

    assert stale_detail.json()["stale"] is True
    assert stale_detail.json()["canConfirm"] is False
    assert stale_confirm.status_code == 409
    assert stale_confirm.json()["code"] == "profile_snapshot_changed"
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_plan_confirmation_and_receipt_survive_application_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "restart-w1"
    root.mkdir()
    first = _application(root)
    service, _uploaded, evidence, session, execution = await _confirmed_profile(first)
    plan = _plan(service, evidence, session, execution)
    await first.close()

    second = _application(root)
    app.dependency_overrides[get_agent_application] = lambda: second
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            confirmed = await client.post(
                f"/api/profile/action-plans/{plan.id}/confirm",
                json={"workspaceId": "w1", "expectedVersion": plan.version},
            )
        receipt_id = confirmed.json()["items"][0]["receiptId"]
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await second.close()

    third = _application(root)
    app.dependency_overrides[get_agent_application] = lambda: third
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            detail = await client.get(
                f"/api/profile/action-plans/{plan.id}",
                params={"workspaceId": "w1"},
            )
        assert detail.json()["status"] == "completed"
        assert detail.json()["items"][0]["receiptId"] == receipt_id
    finally:
        app.dependency_overrides.pop(get_agent_application, None)
        await third.close()
