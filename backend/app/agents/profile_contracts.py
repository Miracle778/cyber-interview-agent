from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ClaimCategory = Literal[
    "skill",
    "project",
    "experience",
    "education",
    "certification",
    "achievement",
    "link",
]
ProposalType = Literal["create", "update", "reject"]
ExtractionSourceKind = Literal["resume_extraction", "agent_inference"]
ProfileCardCategory = Literal[
    "skill",
    "project",
    "experience",
    "education",
    "certification",
    "achievement",
    "link",
    "summary",
    "direction",
    "highlight",
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileClaimCandidate(_StrictContract):
    category: ClaimCategory = Field(
        description=(
            "固定分类：skill 技能、project 项目经历、experience 工作经历、"
            "education 教育经历、certification 认证、achievement 成果、"
            "link 个人链接"
        )
    )
    value: dict[str, object] = Field(
        description=(
            "分类字段：skill 使用 name/notes；project 使用 name/period/"
            "background/role/responsibilities/key_actions/tech_stack/results；"
            "experience 使用 organization/title/period/location/"
            "responsibilities/achievements；education 使用 school/degree/major/"
            "period/highlights；certification 使用 name/issuer/issued_at；"
            "achievement 使用 title/description/date；link 使用 label/url"
        )
    )
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="仅表示从所引 Evidence 中提取此候选的把握，不表示用户已确认",
    )
    rationale: str = Field(min_length=1, max_length=1000)
    source_kind: ExtractionSourceKind = "resume_extraction"
    proposal_type: ProposalType = "create"
    target_claim_id: str | None = Field(default=None, max_length=128)
    base_claim_version_id: str | None = Field(default=None, max_length=128)


class ProfileExtractionOutput(_StrictContract):
    candidates: list[ProfileClaimCandidate] = Field(default_factory=list, max_length=50)


class ProfileConversationProposal(_StrictContract):
    category: ProfileCardCategory
    value: dict[str, object]
    proposal_type: Literal["create", "update"] = "create"
    target_claim_id: str | None = Field(default=None, max_length=128)
    rationale: str = Field(min_length=1, max_length=1000)


class ProfileConversationProposalOutput(_StrictContract):
    summary: str = Field(min_length=1, max_length=1000)
    proposals: list[ProfileConversationProposal] = Field(
        default_factory=list, max_length=20
    )


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
