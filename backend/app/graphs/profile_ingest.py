from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Awaitable, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.profile_agents import ProfileAgents
from app.agents.profile_contracts import ProfileClaimCandidate, ProfileExtractionOutput
from app.profile.errors import (
    ProfileDomainError,
    ProfileEvidenceMismatch,
    ProfileExtractionFailed,
)
from app.profile.models import ClaimProposalRecord, CreateClaimProposalSpec
from app.profile.parsers import ExtractedSegment, parse_document
from app.profile.repository import ProfileRepository
from app.profile.storage import MaterialStorage


ProfileEventPublisher = Callable[
    [str, str, str, dict[str, object]], Awaitable[None]
]


class ProfileIngestState(TypedDict, total=False):
    material_id: str
    version_id: str
    evidence_ids: list[str]
    evidence_count: int
    extraction: dict[str, Any]
    proposal_ids: list[str]
    new_source_links: int
    missing_source_gaps: int


@dataclass(frozen=True, slots=True)
class IncrementalIngestResult:
    proposals: tuple[ClaimProposalRecord, ...]
    new_source_links: int
    missing_source_gaps: int


_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def create_profile_ingest_graph(
    agent: ProfileAgents,
    *,
    repository: ProfileRepository,
    storage: MaterialStorage,
    publish_event: ProfileEventPublisher | None,
    checkpointer=None,
):
    async def parse(
        state: ProfileIngestState,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        version = _workspace_version(repository, state, runtime.context)
        await _publish(
            publish_event,
            runtime.context,
            "profile.ingest.parsing",
            {"versionId": version.id},
        )
        if version.processing_status in {
            "parsed",
            "extracting",
            "extraction_failed",
            "ready",
        } and version.text_ref:
            return {}
        repository.set_version_processing_status(version.id, "parsing")
        try:
            segments = parse_document(
                file_name=version.file_name,
                mime_type=version.mime_type,
                content=storage.read_blob(version.storage_ref),
            )
            text_ref = storage.write_text(
                version_id=version.id,
                text="\n\n".join(segment.text for segment in segments),
            )
            repository.mark_version_parsed(
                version.id,
                text_path=text_ref,
                content_sha256=version.content_sha256,
            )
            return {}
        except Exception:
            repository.set_version_processing_status(version.id, "parse_failed")
            raise

    async def redact_for_model(
        state: ProfileIngestState,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        version = _workspace_version(repository, state, runtime.context)
        existing = repository.list_evidence_for_version(version.id)
        if not existing:
            try:
                segments = parse_document(
                    file_name=version.file_name,
                    mime_type=version.mime_type,
                    content=storage.read_blob(version.storage_ref),
                )
                evidence_specs = _evidence_specs(segments)
                existing = repository.replace_version_evidence(
                    version.id, evidence_specs
                )
            except Exception as error:
                repository.set_version_processing_status(
                    version.id, "extraction_failed"
                )
                if isinstance(error, ProfileDomainError):
                    raise
                raise ProfileExtractionFailed(
                    "profile evidence extraction failed"
                ) from error
        repository.set_version_processing_status(version.id, "extracting")
        return {
            "evidence_ids": [item.id for item in existing],
            "evidence_count": len(existing),
        }

    async def extract_evidence_candidates(
        state: ProfileIngestState,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        version = _workspace_version(repository, state, runtime.context)
        evidence = repository.list_evidence_for_version(version.id)
        return {
            "evidence_ids": [item.id for item in evidence],
            "evidence_count": len(evidence),
        }

    async def profile_extraction(
        state: ProfileIngestState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        version = _workspace_version(repository, state, runtime.context)
        await _publish(
            publish_event,
            runtime.context,
            "profile.ingest.extracting",
            {
                "versionId": version.id,
                "evidenceCount": int(state.get("evidence_count", 0)),
            },
        )
        evidence = repository.list_evidence_for_version(version.id)
        model_evidence = tuple(
            {
                "id": item.id,
                "section": item.section,
                "startOffset": item.start_offset,
                "endOffset": item.end_offset,
                "excerpt": item.sanitized_text[:2000],
                "sensitivity": item.sensitivity,
            }
            for item in evidence[:50]
        )
        snapshot = repository.profile_snapshot(runtime.context.workspace_id)
        confirmed_profile = tuple(
            {
                "claimId": item.claim_id,
                "claimVersionId": item.claim_version_id,
                "category": item.claim_type,
                "version": item.version_number,
                "value": item.value,
                "sourceSummary": [
                    {
                        "kind": source.source_kind,
                        "status": source.status,
                    }
                    for source in item.sources
                ],
            }
            for item in snapshot.claims[:50]
        )
        try:
            output = await agent.extract(
                evidence=model_evidence,
                confirmed_profile=confirmed_profile,
                context=runtime.context,
                config=dict(config),
            )
        except Exception as error:
            repository.set_version_processing_status(
                version.id, "extraction_failed"
            )
            if isinstance(error, ProfileDomainError):
                raise
            raise ProfileExtractionFailed(
                "profile claim extraction failed"
            ) from error
        return {"extraction": output.model_dump(mode="json")}

    async def validate_and_persist_proposals(
        state: ProfileIngestState,
        runtime: Runtime[AgentContext],
    ) -> dict[str, Any]:
        version = _workspace_version(repository, state, runtime.context)
        try:
            output = _normalize_extraction(
                ProfileExtractionOutput.model_validate(state["extraction"])
            )
            valid_ids = {
                item.id for item in repository.list_evidence_for_version(version.id)
            }
            referenced = {
                evidence_id
                for candidate in output.candidates
                for evidence_id in candidate.evidence_ids
            }
            if referenced - valid_ids:
                raise ProfileEvidenceMismatch(
                    "profile extraction references unknown Evidence"
                )
            merge = _merge_incremental_extraction(
                repository=repository,
                workspace_id=runtime.context.workspace_id,
                material_version_id=version.id,
                output=output,
                created_by_execution_id=runtime.context.run_id,
            )
            repository.set_version_processing_status(version.id, "ready")
        except Exception as error:
            repository.set_version_processing_status(
                version.id, "extraction_failed"
            )
            if isinstance(error, ProfileDomainError):
                raise
            raise ProfileExtractionFailed(
                "profile claim proposal validation failed"
            ) from error
        proposal_ids = [item.id for item in merge.proposals]
        await _publish(
            publish_event,
            runtime.context,
            "profile.claims.proposed",
            {
                "versionId": version.id,
                "proposalIds": proposal_ids,
                "count": len(proposal_ids),
                "newSourceLinks": merge.new_source_links,
                "missingSourceGaps": merge.missing_source_gaps,
            },
        )
        return {
            "proposal_ids": proposal_ids,
            "new_source_links": merge.new_source_links,
            "missing_source_gaps": merge.missing_source_gaps,
        }

    graph = StateGraph(ProfileIngestState, context_schema=AgentContext)
    graph.add_node("parse", parse)
    graph.add_node("redact_for_model", redact_for_model)
    graph.add_node("extract_evidence_candidates", extract_evidence_candidates)
    graph.add_node("profile_extraction", profile_extraction)
    graph.add_node(
        "validate_and_persist_proposals", validate_and_persist_proposals
    )
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "redact_for_model")
    graph.add_edge("redact_for_model", "extract_evidence_candidates")
    graph.add_edge("extract_evidence_candidates", "profile_extraction")
    graph.add_edge("profile_extraction", "validate_and_persist_proposals")
    graph.add_edge("validate_and_persist_proposals", END)
    return graph.compile(checkpointer=checkpointer)


def _workspace_version(
    repository: ProfileRepository,
    state: ProfileIngestState,
    context: AgentContext,
):
    version_id = state.get("version_id") or state.get("versionId")
    material_id = state.get("material_id") or state.get("materialId")
    if not isinstance(version_id, str) or not isinstance(material_id, str):
        raise ValueError("profile ingest identifiers are required")
    version = repository.get_material_version(version_id)
    material = repository.get_material(
        version.material_id, workspace_id=context.workspace_id
    )
    if material.id != material_id:
        raise ValueError("profile material version mismatch")
    return version


def _evidence_specs(segments: tuple[ExtractedSegment, ...]) -> tuple[dict[str, Any], ...]:
    specs: list[dict[str, Any]] = []
    offset = 0
    for segment in segments:
        sanitized, sensitive = _sanitize(segment.text)
        end = offset + len(sanitized)
        specs.append(
            {
                "section": _section(segment),
                "start_offset": offset,
                "end_offset": end,
                "sanitized_text": sanitized,
                "content_sha256": sha256(sanitized.encode("utf-8")).hexdigest(),
                "sensitivity": "sensitive" if sensitive else "normal",
            }
        )
        offset = end + 2
    return tuple(specs)


def _normalize_extraction(output: ProfileExtractionOutput) -> ProfileExtractionOutput:
    """Canonicalize category fields and merge exact duplicate facts.

    This deliberately avoids semantic fuzzy merging: only candidates with the
    same category, canonical value and target identity are combined.
    """
    merged: dict[str, ProfileClaimCandidate] = {}
    order: list[str] = []
    for candidate in output.candidates:
        value = _canonical_claim_value(candidate.category, candidate.value)
        normalized = candidate.model_copy(update={"value": value})
        key = json.dumps(
            {
                "category": normalized.category,
                "value": normalized.value,
                "proposalType": normalized.proposal_type,
                "targetClaimId": normalized.target_claim_id,
                "baseClaimVersionId": normalized.base_claim_version_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = normalized
            order.append(key)
            continue
        evidence_ids = list(
            dict.fromkeys([*existing.evidence_ids, *normalized.evidence_ids])
        )[:50]
        higher_confidence = (
            normalized if normalized.confidence > existing.confidence else existing
        )
        merged[key] = existing.model_copy(
            update={
                "evidence_ids": evidence_ids,
                "confidence": max(existing.confidence, normalized.confidence),
                "rationale": higher_confidence.rationale,
            }
        )
    return ProfileExtractionOutput(candidates=[merged[key] for key in order])


def _merge_incremental_extraction(
    *,
    repository: ProfileRepository,
    workspace_id: str,
    material_version_id: str,
    output: ProfileExtractionOutput,
    created_by_execution_id: str | None,
) -> IncrementalIngestResult:
    snapshot = repository.profile_snapshot(workspace_id)
    existing_by_identity = {
        identity: claim
        for claim in snapshot.claims
        if (identity := _claim_identity(claim.claim_type, claim.value)) is not None
    }
    seen_identities: set[str] = set()
    source_links = 0
    proposal_specs: list[CreateClaimProposalSpec] = []

    for candidate in output.candidates:
        identity = _claim_identity(candidate.category, candidate.value)
        if identity is not None:
            seen_identities.add(identity)
        existing = existing_by_identity.get(identity) if identity is not None else None
        candidate_facts = _comparable_value(candidate.category, candidate.value)
        source_ref = {
            "materialVersionId": material_version_id,
            "evidenceIds": list(candidate.evidence_ids),
        }
        if candidate.source_kind == "agent_inference":
            source_ref["baseProfileVersion"] = snapshot.profile_version

        if existing is not None:
            current_facts = _comparable_value(existing.claim_type, existing.value)
            changed = {
                key: value
                for key, value in candidate_facts.items()
                if current_facts.get(key) != value
            }
            if not changed:
                _source, created = repository.attach_claim_source(
                    workspace_id=workspace_id,
                    claim_version_id=existing.claim_version_id,
                    source_kind=candidate.source_kind,
                    source_ref=source_ref,
                )
                source_links += int(created)
                continue
            proposed_value = {
                "category": existing.claim_type,
                **current_facts,
                **candidate_facts,
                "confidence": candidate.confidence,
            }
            proposal_specs.append(
                CreateClaimProposalSpec(
                    proposal_type="update",
                    target_claim_id=existing.claim_id,
                    base_claim_version_id=existing.claim_version_id,
                    proposed_value=proposed_value,
                    reason=candidate.rationale,
                    evidence_ids=tuple(candidate.evidence_ids),
                    source="extraction",
                    source_kind=candidate.source_kind,
                    source_ref=source_ref,
                )
            )
            continue

        proposal_specs.append(
            CreateClaimProposalSpec(
                proposal_type="create",
                proposed_value={
                    "category": candidate.category,
                    **candidate_facts,
                    "confidence": candidate.confidence,
                },
                reason=candidate.rationale,
                evidence_ids=tuple(candidate.evidence_ids),
                source="extraction",
                source_kind=candidate.source_kind,
                source_ref=source_ref,
            )
        )

    proposals = repository.create_claim_proposals(
        material_version_id,
        tuple(proposal_specs),
        idempotency_key=f"profile.ingest:{material_version_id}",
        created_by_execution_id=created_by_execution_id,
    )
    missing_source_gaps = _missing_source_gap_count(
        repository=repository,
        material_version_id=material_version_id,
        snapshot_claims=snapshot.claims,
        seen_identities=seen_identities,
    )
    return IncrementalIngestResult(
        proposals=proposals,
        new_source_links=source_links,
        missing_source_gaps=missing_source_gaps,
    )


def _missing_source_gap_count(
    *,
    repository: ProfileRepository,
    material_version_id: str,
    snapshot_claims,
    seen_identities: set[str],
) -> int:
    current_version = repository.get_material_version(material_version_id)
    count = 0
    for claim in snapshot_claims:
        identity = _claim_identity(claim.claim_type, claim.value)
        if identity is None or identity in seen_identities:
            continue
        supported_by_same_material = False
        for source in claim.sources:
            if source.source_kind != "resume_extraction":
                continue
            source_version_id = source.source_ref.get("materialVersionId")
            if not isinstance(source_version_id, str):
                continue
            try:
                source_version = repository.get_material_version(source_version_id)
            except ProfileDomainError:
                continue
            if source_version.material_id == current_version.material_id:
                supported_by_same_material = True
                break
        if supported_by_same_material:
            count += 1
    return count


def _claim_identity(category: str, value: dict[str, object]) -> str | None:
    normalized = _comparable_value(category, value)

    def text(key: str) -> str:
        candidate = normalized.get(key)
        return str(candidate).strip().casefold() if candidate else ""

    if category == "skill":
        parts = (text("name"),)
    elif category == "project":
        parts = (text("name"),)
    elif category == "experience":
        parts = (text("organization"), text("title"), text("period"))
    elif category == "education":
        parts = (text("school"), text("degree"), text("major"), text("period"))
    elif category == "certification":
        parts = (text("name"), text("issuer"))
    elif category == "achievement":
        parts = (text("title"), text("date"))
    elif category == "link":
        parts = (text("url"),)
    else:
        return None
    if not parts[0]:
        return None
    return json.dumps(
        [category, *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _comparable_value(
    category: str, raw_value: dict[str, object]
) -> dict[str, object]:
    value = _canonical_claim_value(category, raw_value)
    return {
        key: item
        for key, item in value.items()
        if key not in {"category", "confidence"} and item not in (None, "", [], {})
    }


def _canonical_claim_value(
    category: str, raw_value: dict[str, object]
) -> dict[str, object]:
    value = dict(raw_value)

    def alias(target: str, *sources: str) -> None:
        if target not in value:
            for source in sources:
                candidate = value.get(source)
                if candidate is not None and candidate != "" and candidate != [] and candidate != {}:
                    value[target] = candidate
                    break
        for source in sources:
            if source != target:
                value.pop(source, None)

    if category == "skill":
        alias("name", "name", "text", "skill")
    elif category == "project":
        alias("name", "name", "title", "project")
        alias("background", "background", "description")
        alias("role", "role", "position")
        alias("tech_stack", "tech_stack", "techStack", "technologies")
        alias("results", "results", "result", "outcomes")
    elif category == "experience":
        alias("organization", "organization", "company", "employer")
        alias("title", "title", "role", "position")
        alias("period", "period", "dates", "duration")
    elif category == "education":
        alias("school", "school", "institution", "university")
        alias("major", "major", "field")
        alias("period", "period", "dates", "duration")
    elif category == "certification":
        alias("name", "name", "title", "certificate")
        alias("issuer", "issuer", "organization")
        alias("issued_at", "issued_at", "issuedAt", "date")
    elif category == "achievement":
        alias("title", "title", "name")
        alias("date", "date", "period")
    elif category == "link":
        alias("label", "label", "name", "title")
        alias("url", "url", "href", "link")
    return value


def _sanitize(text: str) -> tuple[str, bool]:
    redacted = _EMAIL.sub("[email redacted]", text)
    redacted = _PHONE.sub("[phone redacted]", redacted)
    return redacted, redacted != text


def _section(segment: ExtractedSegment) -> str:
    return json.dumps(
        segment.locator,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


async def _publish(
    publisher: ProfileEventPublisher | None,
    context: AgentContext,
    event_type: str,
    payload: dict[str, object],
) -> None:
    if publisher is not None:
        await publisher(context.session_id, context.run_id, event_type, payload)
