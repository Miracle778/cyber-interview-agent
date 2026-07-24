from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.profile_contracts import ProfileClaimCandidate, ProfileExtractionOutput
from app.graphs.profile_ingest import _merge_incremental_extraction
from app.infrastructure.runtime_database import connect_runtime_database
from app.profile.models import CreateMaterialCommand, DecideProposalCommand
from app.profile.repository import ProfileRepository


@pytest.fixture
def repository(tmp_path: Path) -> ProfileRepository:
    return ProfileRepository(connect_runtime_database(tmp_path))


def _version(
    repository: ProfileRepository,
    *,
    material_id: str | None = None,
    content: str,
):
    if material_id is None:
        material = repository.create_material(
            CreateMaterialCommand(
                workspace_id="w1",
                type="resume",
                title="Resume",
                primary_role="resume",
            )
        )
        material_id = material.id
    version = repository.add_material_version(
        material_id=material_id,
        source_type="upload",
        file_name="resume.txt",
        mime_type="text/plain",
        content_sha256=content * 64,
        storage_ref=f"blobs/{content}.txt",
        text_ref=f"text/{content}.txt",
    )
    evidence = repository.replace_version_evidence(
        version.id,
        (
            {
                "section": "resume",
                "start_offset": 0,
                "end_offset": len(content),
                "sanitized_text": content,
                "content_sha256": content * 64,
                "sensitivity": "normal",
            },
        ),
    )[0]
    return version, evidence


def _candidate(
    evidence_id: str,
    *,
    category: str,
    value: dict[str, object],
) -> ProfileExtractionOutput:
    return ProfileExtractionOutput(
        candidates=[
            ProfileClaimCandidate(
                category=category,  # type: ignore[arg-type]
                value=value,
                evidence_ids=[evidence_id],
                confidence=0.92,
                rationale="简历中有直接依据",
            )
        ]
    )


def _accept_initial(
    repository: ProfileRepository,
    *,
    category: str,
    value: dict[str, object],
):
    version, evidence = _version(repository, content="a")
    merge = _merge_incremental_extraction(
        repository=repository,
        workspace_id="w1",
        material_version_id=version.id,
        output=_candidate(evidence.id, category=category, value=value),
        created_by_execution_id=None,
    )
    accepted = repository.decide_proposal(
        merge.proposals[0].id,
        DecideProposalCommand(
            proposal_id=merge.proposals[0].id,
            decision="accepted",
            expected_claim_version=0,
        ),
    )
    return version, accepted


def test_exact_fact_adds_resume_source_without_changing_confirmed_profile(
    repository: ProfileRepository,
) -> None:
    first_version, accepted = _accept_initial(
        repository, category="skill", value={"name": "Python"}
    )
    before = repository.profile_snapshot("w1")
    second_version, evidence = _version(
        repository, material_id=first_version.material_id, content="b"
    )

    merge = _merge_incremental_extraction(
        repository=repository,
        workspace_id="w1",
        material_version_id=second_version.id,
        output=_candidate(evidence.id, category="skill", value={"name": "Python"}),
        created_by_execution_id=None,
    )

    after = repository.profile_snapshot("w1")
    assert merge.proposals == ()
    assert merge.new_source_links == 1
    assert before.profile_version == after.profile_version
    sources = repository.list_claim_sources(accepted.claim_version_id or "")
    assert {item.source_ref["materialVersionId"] for item in sources} == {
        first_version.id,
        second_version.id,
    }


def test_changed_project_creates_update_and_preserves_unmentioned_fields(
    repository: ProfileRepository,
) -> None:
    first_version, accepted = _accept_initial(
        repository,
        category="project",
        value={
            "name": "Cyber Interview Agent",
            "role": "Owner",
            "results": ["Released v1"],
        },
    )
    before = repository.profile_snapshot("w1")
    second_version, evidence = _version(
        repository, material_id=first_version.material_id, content="c"
    )

    merge = _merge_incremental_extraction(
        repository=repository,
        workspace_id="w1",
        material_version_id=second_version.id,
        output=_candidate(
            evidence.id,
            category="project",
            value={"name": "Cyber Interview Agent", "results": ["Released v2"]},
        ),
        created_by_execution_id=None,
    )

    assert len(merge.proposals) == 1
    proposal = merge.proposals[0]
    assert proposal.proposal_type == "update"
    assert proposal.target_claim_id == accepted.claim_id
    assert proposal.base_claim_version_id == accepted.claim_version_id
    assert proposal.proposed_value["role"] == "Owner"
    assert proposal.proposed_value["results"] == ["Released v2"]
    assert proposal.source_kind == "resume_extraction"
    assert proposal.source_ref == {
        "materialVersionId": second_version.id,
        "evidenceIds": [evidence.id],
    }
    assert repository.profile_snapshot("w1").profile_version == before.profile_version


def test_omission_never_deletes_and_new_categories_remain_pending(
    repository: ProfileRepository,
) -> None:
    first_version, accepted = _accept_initial(
        repository, category="skill", value={"name": "Python"}
    )
    second_version, _evidence = _version(
        repository, material_id=first_version.material_id, content="d"
    )
    omission = _merge_incremental_extraction(
        repository=repository,
        workspace_id="w1",
        material_version_id=second_version.id,
        output=ProfileExtractionOutput(candidates=[]),
        created_by_execution_id=None,
    )
    assert omission.missing_source_gaps == 1
    assert repository.get_claim(accepted.claim_id or "")

    third_version, evidence = _version(
        repository, material_id=first_version.material_id, content="e"
    )
    output = ProfileExtractionOutput(
        candidates=[
            ProfileClaimCandidate(
                category="certification",
                value={"name": "Cloud Certificate", "issuer": "Example"},
                evidence_ids=[evidence.id],
                confidence=0.9,
                rationale="证书明确列出",
            ),
            ProfileClaimCandidate(
                category="achievement",
                value={"title": "Hackathon Winner", "date": "2025"},
                evidence_ids=[evidence.id],
                confidence=0.9,
                rationale="成果明确列出",
            ),
        ]
    )
    added = _merge_incremental_extraction(
        repository=repository,
        workspace_id="w1",
        material_version_id=third_version.id,
        output=output,
        created_by_execution_id=None,
    )
    assert [item.proposed_value["category"] for item in added.proposals] == [
        "certification",
        "achievement",
    ]
    assert repository.profile_snapshot("w1").claims[0].claim_id == accepted.claim_id
