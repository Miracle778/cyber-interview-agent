from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.agents.profile_contracts import (
    ProfileActionPlanItemProposal,
    ProfileActionPlanProposal,
)
from app.application.session_service import ProductRepository
from app.graphs.profile_manage import (
    classify_profile_manage_intent,
    create_profile_manage_graph,
)
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.models import CreateClaimProposalSpec, DecideProposalCommand
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage
from app.tools.profile_tools import PROFILE_TOOL_NAMES, PROFILE_TOOL_SCOPES


class FakeAssessmentGraph:
    async def ainvoke(self, _value, config=None, *, context=None):
        return {"assessment_id": "assessment-1", "proposal_ids": ["proposal-1"]}


class RecordingAgents:
    def __init__(self, plan: ProfileActionPlanProposal | None = None) -> None:
        self.plan_output = plan
        self.answer_calls = []
        self.plan_calls = []

    async def answer(self, **values):
        self.answer_calls.append(values)
        return "有证据支持这项经历。"

    async def plan(self, **values):
        self.plan_calls.append(values)
        assert self.plan_output is not None
        return self.plan_output


class BlockingAgents(RecordingAgents):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def answer(self, **values):
        self.started.set()
        await asyncio.Future()


@pytest.fixture
def profile_runtime(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    connection: sqlite3.Connection = connect_runtime_database(root)
    product = ProductRepository(connection)
    repository = ProfileRepository(connection)
    service = ProfileService(
        workspace_id="w1",
        root=root,
        repository=repository,
        storage=MaterialStorage(root),
        product_repository=product,
    )
    uploaded = service.upload_material(
        file_name="resume.txt", content=b"Python", title="Resume"
    )
    service.record_ingest_success(uploaded.version.id)
    evidence = repository.replace_version_evidence(
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
    proposal = repository.create_claim_proposals(
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
    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted"),
    )
    session = product.create_session(
        workspace_id="w1", kind="profile.manage", title="Profile", session_id="s1"
    )
    product.create_execution(
        session.id,
        input={},
        model_bindings={},
        configuration={},
        execution_id="run-1",
    )
    yield root, product, repository, service, evidence
    connection.close()


def _context(root: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=root,
        session_id="s1",
        run_id="run-1",
        allowed_tools=frozenset(PROFILE_TOOL_NAMES),
        allowed_scopes=frozenset(PROFILE_TOOL_SCOPES.values()),
        agent_role="profile_chat",
    )


def _graph(agents, product, repository, service, cards=None):
    async def project(plan):
        if cards is not None and all(item.id != plan.id for item in cards):
            cards.append(plan)

    return create_profile_manage_graph(
        agents,
        repository=repository,
        service=service,
        assessment_graph=FakeAssessmentGraph(),
        project_action_plan_card=project,
    )


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("评估一下我的画像优势和风险", "assess"),
        ("添加 FastAPI 技能", "single_change"),
        ("修改技能并且优化简历", "plan"),
        ("帮我改一下", "clarify"),
        ("我的项目经历有证据吗", "chat"),
    ],
)
def test_intent_classification_is_deterministic(message: str, intent: str) -> None:
    assert classify_profile_manage_intent(message) == intent


@pytest.mark.asyncio
async def test_chat_uses_fresh_snapshot_focus_and_intent_tool_allowlist(
    profile_runtime,
) -> None:
    root, product, repository, service, _evidence = profile_runtime
    product.append_message("s1", execution_id=None, role="user", content="之前的问题")
    claim_id = repository.profile_snapshot("w1").claims[0].claim_id
    agents = RecordingAgents()

    result = await _graph(agents, product, repository, service).ainvoke(
        {
            "message": "我的简历原文证据是什么？",
            "focus": {"claimId": claim_id},
        },
        context=_context(root),
    )

    assert result["response"] == "有证据支持这项经历。"
    call = agents.answer_calls[0]
    assembled = call["profile_context"]["assembledContext"]
    assert "profileVersion" in assembled
    assert claim_id in assembled
    assert "之前的问题" not in assembled
    assert "read_personal_evidence" in call["context"].allowed_tools
    assert "compare_material_versions" not in call["context"].allowed_tools


@pytest.mark.asyncio
async def test_assessment_and_clarification_take_explicit_routes(
    profile_runtime,
) -> None:
    root, product, repository, service, _evidence = profile_runtime
    agents = RecordingAgents()
    graph = _graph(agents, product, repository, service)

    assessed = await graph.ainvoke(
        {"message": "评估一下我的画像风险"}, context=_context(root)
    )
    clarified = await graph.ainvoke(
        {"message": "帮我改一下"}, context=_context(root)
    )

    assert assessed["assessment_id"] == "assessment-1"
    assert assessed["proposal_ids"] == ["proposal-1"]
    assert "希望修改哪一项" in clarified["response"]
    assert agents.answer_calls == [] and agents.plan_calls == []


@pytest.mark.asyncio
async def test_single_change_persists_validated_plan_and_projects_card(
    profile_runtime,
) -> None:
    root, product, repository, service, evidence = profile_runtime
    agents = RecordingAgents(
        ProfileActionPlanProposal(
            request_summary="添加 FastAPI 技能",
            items=[
                ProfileActionPlanItemProposal(
                    item_id="item-1",
                    operation="propose_claim_create",
                    target={},
                    after={"category": "skill", "text": "FastAPI"},
                    evidence_ids=[evidence.id],
                )
            ],
        )
    )
    cards = []

    graph = _graph(agents, product, repository, service, cards)
    result = await graph.ainvoke(
        {"message": "添加 FastAPI 技能"}, context=_context(root)
    )
    replay = await graph.ainvoke(
        {"message": "添加 FastAPI 技能"}, context=_context(root)
    )

    plan = repository.get_action_plan(result["action_plan_id"])
    assert plan.status == "validated"
    assert plan.session_id == "s1" and plan.execution_id == "run-1"
    assert cards == [plan]
    assert agents.plan_calls[0]["context"].allowed_tools == frozenset()
    assert replay["action_plan_id"] == plan.id
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM profile_action_plans"
    ).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_multi_change_routes_to_ordered_plan(profile_runtime) -> None:
    root, product, repository, service, evidence = profile_runtime
    agents = RecordingAgents(
        ProfileActionPlanProposal(
            request_summary="添加两项技能",
            items=[
                ProfileActionPlanItemProposal(
                    item_id=item_id,
                    operation="propose_claim_create",
                    target={},
                    after={"category": "skill", "text": value},
                    evidence_ids=[evidence.id],
                )
                for item_id, value in (("one", "FastAPI"), ("two", "LangGraph"))
            ],
        )
    )

    result = await _graph(agents, product, repository, service).ainvoke(
        {"message": "添加 FastAPI 并且添加 LangGraph"}, context=_context(root)
    )

    plan = repository.get_action_plan(result["action_plan_id"])
    assert [item.ordinal for item in plan.items] == [1, 2]
    assert [item.after["text"] for item in plan.items] == ["FastAPI", "LangGraph"]


@pytest.mark.asyncio
async def test_invalid_single_change_never_persists_partial_plan(
    profile_runtime,
) -> None:
    root, product, repository, service, evidence = profile_runtime
    item = lambda item_id: ProfileActionPlanItemProposal(
        item_id=item_id,
        operation="propose_claim_create",
        target={},
        after={"category": "skill", "text": item_id},
        evidence_ids=[evidence.id],
    )
    agents = RecordingAgents(
        ProfileActionPlanProposal(
            request_summary="invalid", items=[item("one"), item("two")]
        )
    )

    result = await _graph(agents, product, repository, service).ainvoke(
        {"message": "添加一项技能"}, context=_context(root)
    )

    assert "包含多个" in result["response"]
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM profile_action_plans"
    ).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_cancellation_propagates_without_persisting_agent_output(
    profile_runtime,
) -> None:
    root, product, repository, service, _evidence = profile_runtime
    agents = BlockingAgents()
    task = asyncio.create_task(
        _graph(agents, product, repository, service).ainvoke(
            {"message": "我的画像是什么？"}, context=_context(root)
        )
    )
    await agents.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert repository.connection.execute(
        "SELECT COUNT(*) FROM profile_action_plans"
    ).fetchone()[0] == 0
