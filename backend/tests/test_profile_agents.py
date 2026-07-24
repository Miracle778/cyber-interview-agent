from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.agents.context import AgentContext
from app.agents.profile_agents import ProfileAgents
from app.agents.profile_contracts import (
    ProfileAssessmentOutput,
    ProfileClaimCandidate,
    ProfileExtractionOutput,
)
from app.agents.prompts.profile_prompts import (
    PROFILE_ACTION_PLANNER_PROMPT,
    PROFILE_CHAT_PROMPT,
)
from app.application.graph_factory import ProductionGraphFactory
from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage
from app.tools.profile_tools import PROFILE_TOOL_NAMES


class StubRunnable:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []

    async def ainvoke(self, value, config=None, *, context=None):
        self.calls.append((value, config, context))
        return {"structured_response": self.response}


class RecordingFactory:
    def __init__(self) -> None:
        self.specs = []
        self.runnables = []

    def create(self, spec, **_kwargs):
        self.specs.append(spec)
        if spec.execution_name == "profile_extraction":
            response = ProfileExtractionOutput(candidates=[])
        elif spec.execution_name == "profile_assessment":
            response = ProfileAssessmentOutput(summary="ok")
        else:
            response = ProfileAssessmentOutput(summary="ok")
        runnable = StubRunnable(response)
        self.runnables.append(runnable)
        return runnable


def _context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="version-1",
        run_id="execution-1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def test_profile_agents_have_explicit_roles_names_outputs_and_no_write_tools():
    factory = RecordingFactory()

    ProfileAgents.create(factory, model_bindings={})

    assert [(spec.role, spec.execution_name) for spec in factory.specs] == [
        ("profile_extraction", "profile_extraction"),
        ("profile_assessment", "profile_assessment"),
        ("agent_chat", "profile_chat"),
        ("profile_assessment", "profile_action_planner"),
        ("profile_assessment", "profile_conversation_proposal"),
    ]
    extraction, assessment, chat, planner, conversation_proposal = factory.specs
    assert extraction.response_format is ProfileExtractionOutput
    assert assessment.response_format is ProfileAssessmentOutput
    assert extraction.tools == ()
    assert assessment.tools == ()
    assert planner.tools == ()
    assert conversation_proposal.tools == ()
    assert chat.tools == ()
    assert all(spec.prompt.id.startswith("profile-") for spec in factory.specs)


def test_profile_extraction_prompt_defines_category_boundaries_and_multi_label_evidence():
    factory = RecordingFactory()

    ProfileAgents.create(factory, model_bindings={})

    prompt = factory.specs[0].prompt.system
    assert all(
        label in prompt
        for label in (
            "技能",
            "项目经历",
            "工作经历",
            "教育经历",
            "认证",
            "成果",
            "个人链接",
        )
    )
    assert "同一条 Evidence" in prompt
    assert "多个互补候选" in prompt
    assert "新版简历没有出现旧事实时不要输出 reject" in prompt


def test_profile_chat_prompt_hides_internal_schema_terms_from_user_answers():
    assert "snake_case" in PROFILE_CHAT_PROMPT.system
    assert "不得暴露" in PROFILE_CHAT_PROMPT.system


def test_profile_action_planner_prompt_defines_exact_mutation_contract():
    assert '{"claimId": 快照中的 id}' in PROFILE_ACTION_PLANNER_PROMPT.system
    assert "versionNumber" in PROFILE_ACTION_PLANNER_PROMPT.system
    assert "不要输出分析过程" in PROFILE_ACTION_PLANNER_PROMPT.system


@pytest.mark.asyncio
async def test_extraction_uses_isolated_material_version_thread(tmp_path: Path):
    factory = RecordingFactory()
    agents = ProfileAgents.create(factory, model_bindings={})
    evidence = ({"id": "ev-1", "section": "experience", "excerpt": "Led team"},)

    result = await agents.extract(
        evidence=evidence,
        context=_context(tmp_path),
        config={"configurable": {"thread_id": "version-1"}},
    )

    assert result == ProfileExtractionOutput(candidates=[])
    _value, config, _context_value = factory.runnables[0].calls[0]
    assert config["configurable"]["thread_id"] == "version-1:profile_extraction"


def test_extraction_contract_requires_evidence_grounding():
    with pytest.raises(Exception):
        ProfileClaimCandidate(
            category="skill",
            value={"text": "Python"},
            evidence_ids=[],
            confidence=0.8,
            rationale="mentioned",
        )


def test_production_graph_factory_explicitly_wires_profile_graphs(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    connection = connect_runtime_database(root)

    class GraphAgentFactory(RecordingFactory):
        def resolve_context_limit(self, _role, **_kwargs):
            return 128000

        def resolve_model(self, _role, **_kwargs):
            return GenericFakeChatModel(messages=iter([AIMessage(content="summary")]))

    profile_repository = ProfileRepository(connection)
    profile_storage = MaterialStorage(root)
    product_repository = ProductRepository(connection)
    dependencies = {
        "model_bindings": {
            "profile_extraction": "m1",
            "profile_assessment": "m2",
            "agent_chat": "m3",
            "report_summarization": "m4",
        },
        "projection": object(),
        "audit": object(),
        "observability": object(),
        "checkpointer": None,
        "profile_repository": profile_repository,
        "profile_storage": profile_storage,
        "product_repository": product_repository,
        "profile_service": ProfileService(
            workspace_id="w1",
            root=root,
            repository=profile_repository,
            storage=profile_storage,
            product_repository=product_repository,
        ),
        "publish_event": None,
        "project_profile_card": None,
        "project_profile_action_plan_card": None,
    }
    factory = ProductionGraphFactory(GraphAgentFactory())
    try:
        ingest = factory("profile.ingest", **dependencies)
        assess = factory("profile.assess", **dependencies)
        manage = factory("profile.manage", **dependencies)
    finally:
        connection.close()

    assert set(ingest.get_graph().nodes) == {
        "__start__",
        "parse",
        "redact_for_model",
        "extract_evidence_candidates",
        "profile_extraction",
        "validate_and_persist_proposals",
        "__end__",
    }
    assert set(assess.get_graph().nodes) == {
        "__start__",
        "lock_snapshot",
        "profile_assessment",
        "validate_persist_and_project",
        "__end__",
    }
    assert set(manage.get_graph().nodes) == {
        "__start__",
        "assemble_context",
        "classify_intent",
        "chat",
        "assess",
        "propose",
        "single_change",
        "plan",
        "clarify",
        "__end__",
    }
    production_chat_specs = [
        spec for spec in factory._agents.specs if spec.execution_name == "profile_chat"
    ]
    assert production_chat_specs
    assert {tool.name for tool in production_chat_specs[-1].tools} == set(
        PROFILE_TOOL_NAMES
    )
