from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ClaimCategory = Literal["skill", "project", "experience", "education", "link"]
ProposalType = Literal["create", "update", "reject"]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileClaimCandidate(_StrictContract):
    category: ClaimCategory
    value: dict[str, object]
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1000)
    proposal_type: ProposalType = "create"
    target_claim_id: str | None = Field(default=None, max_length=128)
    base_claim_version_id: str | None = Field(default=None, max_length=128)


class ProfileExtractionOutput(_StrictContract):
    candidates: list[ProfileClaimCandidate] = Field(default_factory=list, max_length=50)


class ProfileAssessmentRecommendation(_StrictContract):
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class ProfileAssessmentProposal(_StrictContract):
    material_version_id: str = Field(min_length=1, max_length=128)
    proposal_type: ProposalType
    proposed_value: dict[str, object]
    reason: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    target_claim_id: str | None = Field(default=None, max_length=128)
    base_claim_version_id: str | None = Field(default=None, max_length=128)


class ProfileAssessmentOutput(_StrictContract):
    summary: str = Field(min_length=1, max_length=4000)
    strengths: list[str] = Field(default_factory=list, max_length=50)
    gaps: list[str] = Field(default_factory=list, max_length=50)
    risks: list[str] = Field(default_factory=list, max_length=50)
    recommendations: list[ProfileAssessmentRecommendation] = Field(
        default_factory=list, max_length=50
    )
    proposal_candidates: list[ProfileAssessmentProposal] = Field(
        default_factory=list, max_length=50
    )


class ProfileActionPlanItemProposal(_StrictContract):
    item_id: str = Field(min_length=1, max_length=128)
    operation: Literal[
        "propose_claim_create",
        "propose_claim_update",
        "propose_claim_reject",
        "propose_material_derived_version",
        "set_publication_selection",
        "request_reassessment",
    ]
    target: dict[str, object]
    expected_version: int | None = Field(default=None, ge=0)
    before: dict[str, object] | None = None
    after: dict[str, object]
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class ProfileActionPlanProposal(_StrictContract):
    request_summary: str = Field(min_length=1, max_length=1000)
    items: list[ProfileActionPlanItemProposal] = Field(
        default_factory=list, max_length=50
    )
