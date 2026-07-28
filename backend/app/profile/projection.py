from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from app.profile.errors import ProfileValueInvalid
from app.profile.models import (
    ClaimType,
    ConfirmedClaimEntry,
    ProfileClaimRelationRecord,
    ProfilePresentationRecord,
)

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=2000)]


class ProfileValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectValue(ProfileValueModel):
    name: ShortText
    period: str | None = Field(default=None, max_length=100)
    background: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=500)
    responsibilities: list[ShortText] = Field(default_factory=list, max_length=30)
    key_actions: list[ShortText] = Field(default_factory=list, max_length=30)
    tech_stack: list[ShortText] = Field(default_factory=list, max_length=50)
    results: list[ShortText] = Field(default_factory=list, max_length=30)


class SkillValue(ProfileValueModel):
    name: ShortText
    self_assessment: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class ExperienceValue(ProfileValueModel):
    organization: ShortText
    title: str | None = Field(default=None, max_length=200)
    period: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    responsibilities: list[ShortText] = Field(default_factory=list, max_length=30)
    achievements: list[ShortText] = Field(default_factory=list, max_length=30)


class EducationValue(ProfileValueModel):
    school: ShortText
    degree: str | None = Field(default=None, max_length=200)
    major: str | None = Field(default=None, max_length=200)
    period: str | None = Field(default=None, max_length=100)
    highlights: list[ShortText] = Field(default_factory=list, max_length=30)


class CertificationValue(ProfileValueModel):
    name: ShortText
    issuer: str | None = Field(default=None, max_length=200)
    issued_at: str | None = Field(default=None, max_length=100)
    credential_id: str | None = Field(default=None, max_length=200)
    url: HttpUrl | None = None


class AchievementValue(ProfileValueModel):
    title: ShortText
    description: str | None = Field(default=None, max_length=2000)
    date: str | None = Field(default=None, max_length=100)


class LinkValue(ProfileValueModel):
    label: ShortText
    url: HttpUrl


class SummaryValue(ProfileValueModel):
    text: LongText


class DirectionValue(ProfileValueModel):
    name: ShortText
    description: str | None = Field(default=None, max_length=1000)


class HighlightValue(ProfileValueModel):
    text: LongText


_VALUE_MODELS: dict[str, type[ProfileValueModel]] = {
    "project": ProjectValue,
    "skill": SkillValue,
    "experience": ExperienceValue,
    "education": EducationValue,
    "certification": CertificationValue,
    "achievement": AchievementValue,
    "link": LinkValue,
    "summary": SummaryValue,
    "direction": DirectionValue,
    "highlight": HighlightValue,
}

_SOURCE_LABELS = {
    "resume_extraction": "简历提取",
    "user_input": "本人补充",
    "conversation": "画像助手对话",
    "agent_inference": "系统归纳",
}


@dataclass(frozen=True, slots=True)
class ProfileSourceView:
    source_kind: str
    label: str
    source_ref: dict[str, object]
    status: str


@dataclass(frozen=True, slots=True)
class ProfileCardReference:
    claim_id: str
    claim_type: str
    title: str


@dataclass(frozen=True, slots=True)
class UnifiedProfileCard:
    claim_id: str
    claim_version_id: str
    claim_type: str
    version: int
    support_status: str
    title: str
    subtitle: str | None
    value: dict[str, object]
    sources: tuple[ProfileSourceView, ...]
    linked_to: tuple[ProfileCardReference, ...] = ()
    used_in: tuple[ProfileCardReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionableProfileGap:
    claim_id: str
    claim_type: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class UnifiedProfile:
    workspace_id: str
    profile_version: str | None
    summary: UnifiedProfileCard | None
    directions: tuple[UnifiedProfileCard, ...]
    primary_direction_claim_id: str | None
    presentation_version: int
    highlights: tuple[UnifiedProfileCard, ...]
    experiences: tuple[UnifiedProfileCard, ...]
    projects: tuple[UnifiedProfileCard, ...]
    skills: tuple[UnifiedProfileCard, ...]
    education: tuple[UnifiedProfileCard, ...]
    certifications: tuple[UnifiedProfileCard, ...]
    achievements: tuple[UnifiedProfileCard, ...]
    links: tuple[UnifiedProfileCard, ...]
    actionable_gaps: tuple[ActionableProfileGap, ...]
    pending_count: int
    is_usable: bool


def validate_profile_value(
    claim_type: ClaimType, value: dict[str, object]
) -> dict[str, object]:
    model = _VALUE_MODELS.get(claim_type)
    if model is None:
        raise ProfileValueInvalid(f"unsupported profile category: {claim_type}")
    try:
        validated = model.model_validate(value)
    except ValidationError as exc:
        raise ProfileValueInvalid(str(exc)) from exc
    return validated.model_dump(mode="json", exclude_none=True)


def project_unified_profile(
    *,
    workspace_id: str,
    profile_version: str | None,
    claims: tuple[ConfirmedClaimEntry, ...],
    relations: tuple[ProfileClaimRelationRecord, ...],
    presentation: ProfilePresentationRecord,
    pending_count: int,
) -> UnifiedProfile:
    cards = {
        claim.claim_id: _project_card(claim)
        for claim in claims
        if claim.claim_type in _VALUE_MODELS
    }
    outgoing: dict[str, list[ProfileClaimRelationRecord]] = {}
    for relation in relations:
        outgoing.setdefault(relation.from_claim_id, []).append(relation)

    enriched: dict[str, UnifiedProfileCard] = {}
    for claim_id, card in cards.items():
        linked: list[ProfileCardReference] = []
        used_in: list[ProfileCardReference] = []
        for relation in outgoing.get(claim_id, []):
            target = cards.get(relation.to_claim_id)
            if target is None:
                continue
            reference = ProfileCardReference(
                claim_id=target.claim_id,
                claim_type=target.claim_type,
                title=target.title,
            )
            if relation.relation_type == "used_in":
                used_in.append(reference)
            else:
                linked.append(reference)
        enriched[claim_id] = UnifiedProfileCard(
            claim_id=card.claim_id,
            claim_version_id=card.claim_version_id,
            claim_type=card.claim_type,
            version=card.version,
            support_status=card.support_status,
            title=card.title,
            subtitle=card.subtitle,
            value=card.value,
            sources=card.sources,
            linked_to=tuple(linked),
            used_in=tuple(used_in),
        )

    def category(name: str) -> tuple[UnifiedProfileCard, ...]:
        return tuple(
            enriched[item.claim_id]
            for item in claims
            if item.claim_type == name and item.claim_id in enriched
        )

    summaries = category("summary")
    directions = category("direction")
    highlights = _ordered_featured(
        category("highlight"), presentation.featured_claim_ids
    )
    projects = category("project")
    experiences = category("experience")
    gaps = _actionable_gaps(projects, experiences)
    usable_types = {
        "skill",
        "project",
        "experience",
        "education",
        "certification",
        "achievement",
    }
    return UnifiedProfile(
        workspace_id=workspace_id,
        profile_version=profile_version,
        summary=_selected_card(summaries, presentation.summary_claim_id),
        directions=directions,
        primary_direction_claim_id=presentation.primary_direction_claim_id,
        presentation_version=presentation.version,
        highlights=highlights,
        experiences=experiences,
        projects=projects,
        skills=category("skill"),
        education=category("education"),
        certifications=category("certification"),
        achievements=category("achievement"),
        links=category("link"),
        actionable_gaps=gaps,
        pending_count=pending_count,
        is_usable=any(item.claim_type in usable_types for item in claims),
    )


def _project_card(claim: ConfirmedClaimEntry) -> UnifiedProfileCard:
    normalized = _normalize_existing_value(claim.claim_type, claim.value)
    title = _title_for(claim.claim_type, normalized)
    subtitle = _subtitle_for(claim.claim_type, normalized)
    sources: list[ProfileSourceView] = []
    for source in claim.sources:
        projected_status = source.status
        if (
            claim.support_status == "unsupported"
            and source.source_kind == "resume_extraction"
        ):
            projected_status = "source_deleted"
        sources.append(
            ProfileSourceView(
                source_kind=source.source_kind,
                label=(
                    "原来源已删除，本人保留"
                    if projected_status == "source_deleted"
                    else _SOURCE_LABELS.get(source.source_kind, "其他来源")
                ),
                source_ref=source.source_ref,
                status=projected_status,
            )
        )
    return UnifiedProfileCard(
        claim_id=claim.claim_id,
        claim_version_id=claim.claim_version_id,
        claim_type=claim.claim_type,
        version=claim.version_number,
        support_status=claim.support_status,
        title=title,
        subtitle=subtitle,
        value=normalized,
        sources=tuple(sources),
    )


def _normalize_existing_value(
    claim_type: str, value: dict[str, object]
) -> dict[str, object]:
    result = {str(key): item for key, item in value.items() if key != "category"}
    aliases: dict[str, dict[str, str]] = {
        "project": {
            "description": "background",
            "result": "results",
            "technology": "tech_stack",
        },
        "experience": {
            "company": "organization",
            "role": "title",
            "results": "achievements",
        },
        "education": {"institution": "school"},
        "achievement": {"name": "title"},
    }
    for source, target in aliases.get(claim_type, {}).items():
        if source in result and target not in result:
            result[target] = result[source]
    model = _VALUE_MODELS.get(claim_type)
    if model is None:
        return result
    allowed = set(model.model_fields)
    filtered = {key: item for key, item in result.items() if key in allowed}
    try:
        return model.model_validate(filtered).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        return filtered


def _title_for(claim_type: str, value: dict[str, object]) -> str:
    keys = {
        "project": "name",
        "skill": "name",
        "experience": "organization",
        "education": "school",
        "certification": "name",
        "achievement": "title",
        "link": "label",
        "summary": "text",
        "direction": "name",
        "highlight": "text",
    }
    value_title = value.get(keys.get(claim_type, "name"))
    return str(value_title or "未命名信息")


def _subtitle_for(claim_type: str, value: dict[str, object]) -> str | None:
    if claim_type == "experience":
        return _joined(value.get("title"), value.get("period"))
    if claim_type == "education":
        return _joined(value.get("degree"), value.get("major"), value.get("period"))
    if claim_type == "project":
        return _joined(value.get("role"), value.get("period"))
    if claim_type == "certification":
        return _joined(value.get("issuer"), value.get("issued_at"))
    return None


def _joined(*values: object) -> str | None:
    items = [str(value) for value in values if value]
    return " · ".join(items) if items else None


def _ordered_featured(
    cards: tuple[UnifiedProfileCard, ...], featured_ids: tuple[str, ...]
) -> tuple[UnifiedProfileCard, ...]:
    by_id = {item.claim_id: item for item in cards}
    selected = [by_id[item_id] for item_id in featured_ids if item_id in by_id]
    selected_ids = {item.claim_id for item in selected}
    return tuple(selected + [item for item in cards if item.claim_id not in selected_ids])


def _selected_card(
    cards: tuple[UnifiedProfileCard, ...], selected_id: str | None
) -> UnifiedProfileCard | None:
    if selected_id is not None:
        for card in cards:
            if card.claim_id == selected_id:
                return card
    return cards[0] if cards else None


def _actionable_gaps(
    projects: tuple[UnifiedProfileCard, ...],
    experiences: tuple[UnifiedProfileCard, ...],
) -> tuple[ActionableProfileGap, ...]:
    gaps: list[ActionableProfileGap] = []
    for project in projects:
        if not project.value.get("results"):
            gaps.append(
                ActionableProfileGap(
                    project.claim_id,
                    project.claim_type,
                    "results",
                    "项目缺少结果或量化成果",
                )
            )
        if not project.value.get("role"):
            gaps.append(
                ActionableProfileGap(
                    project.claim_id,
                    project.claim_type,
                    "role",
                    "项目缺少你的角色或职责",
                )
            )
    for experience in experiences:
        if not experience.value.get("period"):
            gaps.append(
                ActionableProfileGap(
                    experience.claim_id,
                    experience.claim_type,
                    "period",
                    "工作经历缺少起止时间",
                )
            )
    return tuple(gaps)
