from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.errors import ProfileActionPlanInvalid, ProfileClaimVersionConflict
from app.profile.models import CreateClaimProposalSpec
from app.profile.repository import ProfileRepository
from app.profile.service import ProfileService
from app.profile.storage import MaterialStorage


@pytest.fixture
def service(tmp_path: Path) -> ProfileService:
    root = tmp_path / "ws"
    root.mkdir()
    initialize_knowledge_artifacts(root, domain="profile")
    connection: sqlite3.Connection = connect_runtime_database(root)
    return ProfileService(workspace_id="w1", root=root, repository=ProfileRepository(connection), storage=MaterialStorage(root), product_repository=ProductRepository(connection))


def _confirmed_profile(service: ProfileService):
    uploaded = service.upload_material(file_name="resume.txt", content=b"Python", title="Resume")
    service.record_ingest_success(uploaded.version.id)
    evidence = service.repository.replace_version_evidence(uploaded.version.id, ({"section": "skills", "start_offset": 0, "end_offset": 6, "sanitized_text": "Python", "content_sha256": "e" * 64, "sensitivity": "normal"},))[0]
    proposal = service.repository.create_claim_proposals(uploaded.version.id, (CreateClaimProposalSpec(proposal_type="create", proposed_value={"category": "skill", "text": "Python"}, reason="resume", evidence_ids=(evidence.id,)),))[0]
    service.decide_claim_proposal(proposal.id, decision="accepted", expected_version=0, idempotency_key="assessment-accept")
    return uploaded, evidence


def test_assessment_requires_current_confirmed_snapshot_and_evidence(service: ProfileService) -> None:
    with pytest.raises(ProfileClaimVersionConflict):
        service.save_assessment(base_profile_version="", result={"strengths": []})

    _uploaded, evidence = _confirmed_profile(service)
    snapshot = service.repository.profile_snapshot("w1")
    result = {"strengths": [{"text": "Python", "evidenceIds": [evidence.id]}], "gaps": [], "risks": [], "recommendations": []}
    assessment = service.save_assessment(base_profile_version=snapshot.profile_version or "", result=result)
    assert assessment.result == result

    with pytest.raises(ProfileActionPlanInvalid):
        service.save_assessment(base_profile_version=snapshot.profile_version or "", result={"strengths": ["Python"]})


def test_assessment_is_idempotent_for_the_same_execution(service: ProfileService) -> None:
    uploaded, evidence = _confirmed_profile(service)
    snapshot = service.repository.profile_snapshot("w1")
    result = {"recommendations": [{"text": "继续深入", "evidenceIds": [evidence.id]}]}
    first = service.save_assessment(base_profile_version=snapshot.profile_version or "", result=result, created_by_execution_id=uploaded.execution_id)
    replay = service.save_assessment(base_profile_version=snapshot.profile_version or "", result=result, created_by_execution_id=uploaded.execution_id)
    assert replay.id == first.id
