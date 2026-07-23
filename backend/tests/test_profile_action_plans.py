from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.application.session_service import ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.knowledge.workspace_layout import initialize_knowledge_artifacts
from app.profile.errors import ProfileActionPlanInvalid, ProfileDomainError
from app.profile.models import ActionPlanItemSpec, CreateActionPlanCommand, CreateClaimProposalSpec
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
    accepted = service.decide_claim_proposal(proposal.id, decision="accepted", expected_version=0, idempotency_key="plan-accept")
    return uploaded, evidence, accepted


def _command(service: ProfileService, *items: ActionPlanItemSpec) -> CreateActionPlanCommand:
    return CreateActionPlanCommand(workspace_id="w1", session_id=None, execution_id=None, request_summary="更新画像", base_profile_version=service.repository.profile_snapshot("w1").profile_version or "", items=tuple(items))


def test_plan_rejects_unknown_operation_before_persistence(service: ProfileService) -> None:
    _uploaded, evidence, _accepted = _confirmed_profile(service)
    with pytest.raises(ProfileActionPlanInvalid):
        service.create_action_plan(_command(service, ActionPlanItemSpec(item_id="i1", ordinal=1, operation="run_python", target={}, after={}, evidence_ids=(evidence.id,))))
    assert service.connection.execute("SELECT COUNT(*) FROM profile_action_plans").fetchone()[0] == 0


def test_confirmed_plan_creates_traceable_proposal_and_replays_receipt(service: ProfileService) -> None:
    _uploaded, evidence, accepted = _confirmed_profile(service)
    claim = service.repository.get_claim(accepted.claim_id)
    current = service.repository.get_claim_version(accepted.claim_version_id)
    events = []
    service._publish_event = lambda session_id, execution_id, event_type, payload: events.append((event_type, payload))
    session = service.product_repository.create_session(workspace_id="w1", kind="profile.manage", title="Manage")
    execution = service.product_repository.create_execution(session.id, input={}, model_bindings={}, configuration={})
    command = replace(_command(service, ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_claim_update", target={"claimId": claim.id}, expected_version=claim.version, before=current.value, after={"category": "skill", "text": "Python 3"}, evidence_ids=(evidence.id,))), session_id=session.id, execution_id=execution.id)
    plan = service.create_action_plan(command)
    completed = service.confirm_action_plan(plan.id, expected_version=plan.version)
    replay = service.confirm_action_plan(plan.id, expected_version=plan.version)
    assert completed.status == "completed"
    assert replay.items[0].receipt_id == completed.items[0].receipt_id
    assert len(service.repository.list_proposals("w1", status="pending")) == 1
    assert events == [
        ("profile.action_plan.created", {"planId": plan.id, "itemCount": 1, "status": "validated"}),
        ("profile.action_plan.item_completed", {"planId": plan.id, "itemId": "i1", "operation": "propose_claim_update", "ordinal": 1, "status": "completed"}),
    ]


def test_partial_failure_retry_skips_completed_items(service: ProfileService, monkeypatch: pytest.MonkeyPatch) -> None:
    _uploaded, evidence, _accepted = _confirmed_profile(service)
    plan = service.create_action_plan(_command(service,
        ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_claim_create", target={}, after={"category": "skill", "text": "FastAPI"}, evidence_ids=(evidence.id,)),
        ActionPlanItemSpec(item_id="i2", ordinal=2, operation="propose_claim_create", target={}, after={"category": "skill", "text": "LangGraph"}, evidence_ids=(evidence.id,)),
    ))
    original = service.repository.create_claim_proposals
    calls = 0
    def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProfileDomainError("temporary")
        return original(*args, **kwargs)
    monkeypatch.setattr(service.repository, "create_claim_proposals", flaky)
    partial = service.confirm_action_plan(plan.id, expected_version=plan.version)
    assert [item.status for item in partial.items] == ["completed", "failed"]
    first_receipt = partial.items[0].receipt_id
    monkeypatch.setattr(service.repository, "create_claim_proposals", original)
    completed = service.retry_action_plan(plan.id)
    assert completed.status == "completed"
    assert completed.items[0].receipt_id == first_receipt
    assert len(service.repository.list_proposals("w1", status="pending")) == 2


def test_derived_resume_retry_reuses_version_and_becomes_current(service: ProfileService, monkeypatch: pytest.MonkeyPatch) -> None:
    uploaded, _evidence, _accepted = _confirmed_profile(service)
    material = service.get_material(uploaded.material.id)
    plan = service.create_action_plan(_command(service, ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_material_derived_version", target={"materialId": material.id, "sourceVersionId": uploaded.version.id}, after={"fileName": "resume-polished.md", "content": "# Polished\nPython"})))
    original_write = service.storage.write_text
    calls = 0
    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary")
        return original_write(*args, **kwargs)
    monkeypatch.setattr(service.storage, "write_text", fail_once)
    failed = service.confirm_action_plan(plan.id, expected_version=plan.version)
    assert failed.status == "failed"
    assert service.repository.count_material_versions(material.id) == 2
    monkeypatch.setattr(service.storage, "write_text", original_write)
    completed = service.retry_action_plan(plan.id)
    derived = service.repository.get_material_version(completed.items[0].receipt_id)
    assert derived.source_type == "derived_draft"
    assert derived.derived_from_version_id == uploaded.version.id
    assert service.get_material(material.id).current_version_id == derived.id
    assert service.repository.count_material_versions(material.id) == 2


def test_cancelled_plan_does_not_apply_items(service: ProfileService) -> None:
    _uploaded, evidence, _accepted = _confirmed_profile(service)
    plan = service.create_action_plan(_command(service, ActionPlanItemSpec(item_id="i1", ordinal=1, operation="propose_claim_create", target={}, after={"category": "skill", "text": "Rust"}, evidence_ids=(evidence.id,))))
    cancelled = service.cancel_action_plan(plan.id, expected_version=plan.version)
    assert cancelled.status == "cancelled"
    assert service.repository.list_proposals("w1", status="pending") == ()
