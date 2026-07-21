from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, Awaitable, Callable, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.profile_agents import ProfileAgents
from app.agents.profile_contracts import ProfileExtractionOutput
from app.profile.errors import (
    ProfileDomainError,
    ProfileEvidenceMismatch,
    ProfileExtractionFailed,
)
from app.profile.models import CreateClaimProposalSpec
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
        try:
            output = await agent.extract(
                evidence=model_evidence,
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
            output = ProfileExtractionOutput.model_validate(state["extraction"])
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
            proposals = repository.create_claim_proposals(
                version.id,
                tuple(
                    CreateClaimProposalSpec(
                        proposal_type=candidate.proposal_type,
                        target_claim_id=candidate.target_claim_id,
                        base_claim_version_id=candidate.base_claim_version_id,
                        proposed_value={
                            "category": candidate.category,
                            **candidate.value,
                            "confidence": candidate.confidence,
                        },
                        reason=candidate.rationale,
                        evidence_ids=tuple(candidate.evidence_ids),
                        source="extraction",
                    )
                    for candidate in output.candidates
                ),
                idempotency_key=f"profile.ingest:{version.id}",
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
        proposal_ids = [item.id for item in proposals]
        await _publish(
            publish_event,
            runtime.context,
            "profile.claims.proposed",
            {
                "versionId": version.id,
                "proposalIds": proposal_ids,
                "count": len(proposal_ids),
            },
        )
        return {"proposal_ids": proposal_ids}

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
