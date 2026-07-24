from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.agents.context import AgentContext
from app.agents.profile_contracts import ProfileClaimCandidate, ProfileExtractionOutput
from app.agents.profile_contracts import (
    ProfileAssessmentOutput,
    ProfileAssessmentProposal,
    ProfileAssessmentRecommendation,
)
from app.application.session_service import ProductEventStream, ProductRepository
from app.graphs.profile_assess import create_profile_assess_graph
from app.graphs.profile_ingest import create_profile_ingest_graph
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.models import (
    CreateClaimProposalSpec,
    CreateMaterialCommand,
    DecideProposalCommand,
)
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage


class EvidenceGroundedExtractionAgent:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.calls = []

    async def extract(self, *, evidence, context, config):
        self.calls.append((evidence, context, config))
        evidence_id = "unknown-evidence" if self.invalid else evidence[0]["id"]
        return ProfileExtractionOutput(
            candidates=[
                ProfileClaimCandidate(
                    category="skill",
                    value={"text": "Python"},
                    evidence_ids=[evidence_id],
                    confidence=0.9,
                    rationale="Evidence explicitly mentions the skill",
                )
            ]
        )


class DuplicateAliasExtractionAgent:
    async def extract(self, *, evidence, context, config):
        evidence_id = evidence[0]["id"]
        return ProfileExtractionOutput(
            candidates=[
                ProfileClaimCandidate(
                    category="skill",
                    value={"text": "Python"},
                    evidence_ids=[evidence_id],
                    confidence=0.8,
                    rationale="first",
                ),
                ProfileClaimCandidate(
                    category="skill",
                    value={"name": "Python"},
                    evidence_ids=[evidence_id],
                    confidence=0.9,
                    rationale="more explicit",
                ),
            ]
        )


class AssessmentAgent:
    def __init__(self, version_id: str, evidence_id: str, *, invalid: bool = False):
        self.version_id = version_id
        self.evidence_id = "unknown-evidence" if invalid else evidence_id

    async def assess(self, *, snapshot, context, config):
        return ProfileAssessmentOutput(
            summary="Profile is evidence grounded",
            strengths=["Delivery"],
            recommendations=[
                ProfileAssessmentRecommendation(
                    title="Add scale",
                    detail="Quantify impact",
                    evidence_ids=[self.evidence_id],
                )
            ],
            proposal_candidates=[
                ProfileAssessmentProposal(
                    material_version_id=self.version_id,
                    proposal_type="create",
                    proposed_value={"category": "skill", "text": "Leadership"},
                    reason="Evidence supports leadership",
                    evidence_ids=[self.evidence_id],
                )
            ],
        )


@pytest.fixture
def profile_runtime(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    connection = connect_runtime_database(root)
    repository = ProfileRepository(connection)
    storage = MaterialStorage(root)
    yield root, connection, repository, storage
    connection.close()


def _seed(repository: ProfileRepository, storage: MaterialStorage, content: bytes):
    stored = storage.persist_upload(file_name="resume.txt", content=content)
    material = repository.create_material(
        CreateMaterialCommand(
            workspace_id="w1", type="resume", title="Resume", primary_role="resume"
        )
    )
    return repository.add_material_version(
        material_id=material.id,
        source_type="upload",
        file_name="resume.txt",
        mime_type=stored.mime_type,
        content_sha256=stored.content_sha256,
        storage_ref=stored.storage_ref,
        text_ref="",
    )


def _context(root: Path, version_id: str) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=root,
        session_id=version_id,
        run_id="execution-1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        agent_role="profile_extraction",
    )


def _seed_execution(connection: sqlite3.Connection, version_id: str) -> None:
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="profile.ingest",
        title="ingest",
        session_id=version_id,
        visibility="system",
    )
    product.create_execution(
        version_id,
        input={"versionId": version_id},
        model_bindings={},
        configuration={},
        execution_id="execution-1",
    )


@pytest.mark.asyncio
async def test_ingest_parses_redacts_extracts_and_persists_proposals(profile_runtime):
    root, connection, repository, storage = profile_runtime
    version = _seed(repository, storage, b"Python\nLed a team of five")
    _seed_execution(connection, version.id)
    product = ProductRepository(connection)
    events = ProductEventStream(product, workspace_root=root)

    agent = EvidenceGroundedExtractionAgent()
    graph = create_profile_ingest_graph(
        agent,
        repository=repository,
        storage=storage,
        publish_event=events.publish,
    )
    result = await graph.ainvoke(
        {"material_id": version.material_id, "version_id": version.id},
        config={"configurable": {"thread_id": version.id}},
        context=_context(root, version.id),
    )

    assert repository.get_material_version(version.id).processing_status == "ready"
    evidence = repository.list_evidence_for_version(version.id)
    assert evidence and all(item.sanitized_text for item in evidence)
    proposals = repository.list_proposals("w1", status="pending")
    assert len(proposals) == 1
    assert proposals[0].evidence_ids == (evidence[0].id,)
    assert [item.type for item in product.list_events(version.id, after_id=None)] == [
        "profile.ingest.parsing",
        "profile.ingest.extracting",
        "profile.claims.proposed",
    ]
    assert result["proposal_ids"] == [proposals[0].id]
    assert "Led a team of five" not in str(result)


@pytest.mark.asyncio
async def test_ingest_rejects_unknown_evidence_without_partial_proposals(profile_runtime):
    root, _connection, repository, storage = profile_runtime
    version = _seed(repository, storage, b"Python")
    graph = create_profile_ingest_graph(
        EvidenceGroundedExtractionAgent(invalid=True),
        repository=repository,
        storage=storage,
        publish_event=None,
    )

    with pytest.raises(Exception) as raised:
        await graph.ainvoke(
            {"material_id": version.material_id, "version_id": version.id},
            config={"configurable": {"thread_id": version.id}},
            context=_context(root, version.id),
        )

    assert getattr(raised.value, "code", None) == "profile_evidence_mismatch"
    assert repository.get_material_version(version.id).processing_status == "extraction_failed"
    assert repository.list_proposals("w1") == ()


@pytest.mark.asyncio
async def test_ingest_normalizes_category_fields_and_merges_exact_duplicates(profile_runtime):
    root, connection, repository, storage = profile_runtime
    version = _seed(repository, storage, b"Python")
    _seed_execution(connection, version.id)
    graph = create_profile_ingest_graph(
        DuplicateAliasExtractionAgent(),
        repository=repository,
        storage=storage,
        publish_event=None,
    )

    await graph.ainvoke(
        {"material_id": version.material_id, "version_id": version.id},
        config={"configurable": {"thread_id": version.id}},
        context=_context(root, version.id),
    )

    proposals = repository.list_proposals("w1")
    assert len(proposals) == 1
    assert proposals[0].proposed_value["name"] == "Python"
    assert "text" not in proposals[0].proposed_value
    assert proposals[0].reason == "more explicit"


@pytest.mark.asyncio
async def test_ingest_parse_failure_is_retryable_and_redacted(profile_runtime):
    root, _connection, repository, storage = profile_runtime
    version = _seed(repository, storage, b"\xff\xfe")
    graph = create_profile_ingest_graph(
        EvidenceGroundedExtractionAgent(),
        repository=repository,
        storage=storage,
        publish_event=None,
    )

    with pytest.raises(Exception) as raised:
        await graph.ainvoke(
            {"material_id": version.material_id, "version_id": version.id},
            config={"configurable": {"thread_id": version.id}},
            context=_context(root, version.id),
        )

    assert getattr(raised.value, "code", None) == "profile_parse_failed"
    assert repository.get_material_version(version.id).processing_status == "parse_failed"
    assert "\\xff" not in str(raised.value)


def _confirmed_profile(repository: ProfileRepository, storage: MaterialStorage):
    version = _seed(repository, storage, b"Led a team")
    evidence = repository.replace_version_evidence(
        version.id,
        (
            {
                "section": "experience",
                "start_offset": 0,
                "end_offset": 10,
                "sanitized_text": "Led a team",
                "content_sha256": "a" * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]
    proposal = repository.create_claim_proposals(
        version.id,
        (
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={"category": "experience", "text": "Team lead"},
                reason="grounded",
                evidence_ids=(evidence.id,),
            ),
        ),
    )[0]
    repository.decide_proposal(
        proposal.id,
        DecideProposalCommand(proposal_id=proposal.id, decision="accepted"),
    )
    return version, evidence


def _assessment_context(root: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=root,
        session_id="assessment-session",
        run_id="assessment-execution",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
        agent_role="profile_assessment",
    )


def _seed_assessment_execution(connection: sqlite3.Connection) -> None:
    product = ProductRepository(connection)
    product.create_session(
        workspace_id="w1",
        kind="profile.assess",
        title="Assessment",
        session_id="assessment-session",
    )
    product.create_execution(
        "assessment-session",
        input={},
        model_bindings={},
        configuration={},
        execution_id="assessment-execution",
    )


@pytest.mark.asyncio
async def test_assessment_persists_before_projecting_typed_card(profile_runtime):
    root, connection, repository, storage = profile_runtime
    version, evidence = _confirmed_profile(repository, storage)
    _seed_assessment_execution(connection)
    cards = []

    async def project(assessment_id, proposal_ids, summary):
        assert repository.get_assessment(assessment_id).id == assessment_id
        cards.append((assessment_id, proposal_ids, summary))

    graph = create_profile_assess_graph(
        AssessmentAgent(version.id, evidence.id),
        repository=repository,
        project_card=project,
    )
    result = await graph.ainvoke(
        {},
        config={"configurable": {"thread_id": "assessment-session"}},
        context=_assessment_context(root),
    )

    assert repository.get_assessment(result["assessment_id"]).result["summary"]
    assert len(result["proposal_ids"]) == 1
    assert cards[0][0] == result["assessment_id"]


@pytest.mark.asyncio
async def test_assessment_invalid_evidence_leaves_no_partial_state(profile_runtime):
    root, connection, repository, storage = profile_runtime
    version, evidence = _confirmed_profile(repository, storage)
    _seed_assessment_execution(connection)
    graph = create_profile_assess_graph(
        AssessmentAgent(version.id, evidence.id, invalid=True),
        repository=repository,
        project_card=None,
    )

    with pytest.raises(Exception) as raised:
        await graph.ainvoke(
            {},
            config={"configurable": {"thread_id": "assessment-session"}},
            context=_assessment_context(root),
        )

    assert getattr(raised.value, "code", None) == "profile_evidence_mismatch"
    count = connection.execute("SELECT COUNT(*) FROM profile_assessments").fetchone()[0]
    assert count == 0
