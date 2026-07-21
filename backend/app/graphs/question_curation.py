from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.context import AgentContext
from app.agents.question_curation_agent import QuestionCurationAgents
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
    QuestionCandidateChunk,
    QuestionSeed,
    QuestionSeedChunk,
)
from app.review.curation_sections import (
    SourceSection,
    pack_discovery_units,
    section_sources,
)
from app.review.question_similarity import same_question
from app.review.repository import ReviewRepository


class QuestionCurationState(TypedDict, total=False):
    batch_id: str
    source_excerpts: list[str]
    similar_questions: list[str]
    rewrite_feedback: str | None
    revision_candidate_id: str | None
    discovery_work_item_ids: list[str]
    enrichment_work_item_ids: list[str]
    current_unit_index: int
    generation_phase: Literal["discovery", "enrichment"]
    completed_units: int
    total_units: int
    candidates: list[dict[str, Any]]
    warnings: list[dict[str, object]]


def create_question_curation_graph(
    agents: QuestionCurationAgents,
    *,
    repository: ReviewRepository,
    checkpointer=None,
):
    async def revise_one(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        output = await agents.revise(
            source_excerpts=tuple(state.get("source_excerpts", ())),
            rewrite_feedback=state.get("rewrite_feedback") or "按审核意见改进题目",
            context=runtime.context,
            config=dict(config),
        )
        return {
            "candidates": [output.candidate.model_dump(mode="json")],
            "generation_phase": "enrichment",
            "completed_units": 1,
            "total_units": 1,
            "warnings": [],
        }

    async def plan_sections(state: QuestionCurationState) -> dict[str, object]:
        batch_id = _batch_id(state)
        units = _discovery_units(state)
        items = [
            repository.plan_curation_work_item(
                batch_id=batch_id,
                stage="discovery",
                unit_index=unit.unit_index,
                input_digest=unit.input_digest,
                source_refs=tuple(section.ref for section in unit.sections),
            )
            for unit in units
        ]
        return {
            "discovery_work_item_ids": [item.id for item in items],
            "current_unit_index": 0,
            "generation_phase": "discovery",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "warnings": [],
        }

    async def discover_next(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        ids = state.get("discovery_work_item_ids", [])
        index = int(state.get("current_unit_index", 0))
        if index >= len(ids):
            return {"completed_units": len(ids), "total_units": len(ids)}
        item = repository.get_curation_work_item(ids[index])
        if item.status != "completed":
            running = repository.start_curation_work_item(item.id)
            unit = _discovery_units(state)[running.unit_index]
            try:
                output = await agents.discover(
                    unit.sections,
                    context=runtime.context,
                    config=dict(config),
                    unit_index=running.unit_index,
                )
                repository.complete_curation_work_item(
                    running.id, output=output.model_dump(mode="json")
                )
            except Exception as error:
                repository.fail_curation_work_item(
                    running.id, error_code=_error_code(error)
                )
                raise
        completed = sum(
            candidate.status == "completed"
            for candidate in repository.list_curation_work_items(
                _batch_id(state), stage="discovery"
            )
        )
        return {
            "current_unit_index": index + 1,
            "generation_phase": "discovery",
            "completed_units": completed,
            "total_units": len(ids),
        }

    async def plan_enrichment(state: QuestionCurationState) -> dict[str, object]:
        batch_id = _batch_id(state)
        seeds = _completed_seeds(repository, batch_id)
        warnings = list(state.get("warnings", []))
        if len(seeds) > 200:
            seeds = seeds[:200]
            warning = {"code": "candidate_limit_reached", "limit": 200}
            if warning not in warnings:
                warnings.append(warning)
        items = []
        for unit_index, start in enumerate(range(0, len(seeds), 3)):
            chunk = seeds[start : start + 3]
            encoded = json.dumps(
                [seed.model_dump(mode="json") for seed in chunk],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            items.append(repository.plan_curation_work_item(
                batch_id=batch_id,
                stage="enrichment",
                unit_index=unit_index,
                input_digest=sha256(encoded.encode("utf-8")).hexdigest(),
                source_refs=tuple(seed.source_ref for seed in chunk),
            ))
        return {
            "enrichment_work_item_ids": [item.id for item in items],
            "current_unit_index": 0,
            "generation_phase": "enrichment",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "warnings": warnings,
        }

    async def enrich_next(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        ids = state.get("enrichment_work_item_ids", [])
        index = int(state.get("current_unit_index", 0))
        if index >= len(ids):
            return {"completed_units": len(ids), "total_units": len(ids)}
        item = repository.get_curation_work_item(ids[index])
        if item.status != "completed":
            running = repository.start_curation_work_item(item.id)
            all_seeds = _completed_seeds(repository, _batch_id(state))[:200]
            seeds = all_seeds[running.unit_index * 3 : running.unit_index * 3 + 3]
            by_ref = {section.ref: section for section in _sections(state)}
            sections = tuple(by_ref[seed.source_ref] for seed in seeds)
            prior_questions = list(state.get("similar_questions", []))
            for previous in repository.list_curation_work_items(
                _batch_id(state), stage="enrichment"
            ):
                if previous.status != "completed" or previous.output is None:
                    continue
                prior_questions.extend(
                    candidate.question_text
                    for candidate in QuestionCandidateChunk.model_validate(
                        previous.output
                    ).candidates
                )
            try:
                output = await agents.enrich(
                    seeds,
                    sections=sections,
                    known_questions=tuple(prior_questions),
                    context=runtime.context,
                    config=dict(config),
                    unit_index=running.unit_index,
                )
                repository.complete_curation_work_item(
                    running.id, output=output.model_dump(mode="json")
                )
            except Exception as error:
                repository.fail_curation_work_item(
                    running.id, error_code=_error_code(error)
                )
                raise
        completed = sum(
            candidate.status == "completed"
            for candidate in repository.list_curation_work_items(
                _batch_id(state), stage="enrichment"
            )
        )
        return {
            "current_unit_index": index + 1,
            "generation_phase": "enrichment",
            "completed_units": completed,
            "total_units": len(ids),
        }

    async def reduce_candidates(state: QuestionCurationState) -> dict[str, object]:
        candidates: list[QuestionCandidate] = []
        for item in repository.list_curation_work_items(
            _batch_id(state), stage="enrichment"
        ):
            if item.status != "completed" or item.output is None:
                continue
            for candidate in QuestionCandidateChunk.model_validate(item.output).candidates:
                existing_index = next(
                    (
                        position
                        for position, existing in enumerate(candidates)
                        if same_question(
                            existing.question_text,
                            candidate.question_text,
                            left_topics=existing.topics,
                            right_topics=candidate.topics,
                        )
                    ),
                    None,
                )
                if existing_index is None:
                    candidates.append(candidate)
                    continue
                existing = candidates[existing_index]
                candidates[existing_index] = existing.model_copy(update={
                    "source_refs": list(dict.fromkeys([*existing.source_refs, *candidate.source_refs])),
                    "key_points": list(dict.fromkeys([*existing.key_points, *candidate.key_points])),
                    "follow_ups": list(dict.fromkeys([*existing.follow_ups, *candidate.follow_ups])),
                })
        batch = QuestionCandidateBatch(candidates=candidates[:200])
        return {
            "candidates": batch.model_dump(mode="json")["candidates"],
            "generation_phase": "enrichment",
            "completed_units": len(state.get("enrichment_work_item_ids", [])),
            "total_units": len(state.get("enrichment_work_item_ids", [])),
        }

    def route_mode(state: QuestionCurationState) -> str:
        return "revision" if state.get("revision_candidate_id") else "curate"

    def discovery_route(state: QuestionCurationState) -> str:
        return (
            "done"
            if int(state.get("current_unit_index", 0))
            >= len(state.get("discovery_work_item_ids", []))
            else "pending"
        )

    def enrichment_route(state: QuestionCurationState) -> str:
        return (
            "done"
            if int(state.get("current_unit_index", 0))
            >= len(state.get("enrichment_work_item_ids", []))
            else "pending"
        )

    graph = StateGraph(QuestionCurationState, context_schema=AgentContext)
    graph.add_node("revise_one", revise_one)
    graph.add_node("plan_sections", plan_sections)
    graph.add_node("discover_next", discover_next)
    graph.add_node("plan_enrichment", plan_enrichment)
    graph.add_node("enrich_next", enrich_next)
    graph.add_node("reduce_candidates", reduce_candidates)
    graph.add_conditional_edges(
        START, route_mode, {"revision": "revise_one", "curate": "plan_sections"}
    )
    graph.add_edge("revise_one", END)
    graph.add_edge("plan_sections", "discover_next")
    graph.add_conditional_edges(
        "discover_next",
        discovery_route,
        {"pending": "discover_next", "done": "plan_enrichment"},
    )
    graph.add_edge("plan_enrichment", "enrich_next")
    graph.add_conditional_edges(
        "enrich_next",
        enrichment_route,
        {"pending": "enrich_next", "done": "reduce_candidates"},
    )
    graph.add_edge("reduce_candidates", END)
    return graph.compile(checkpointer=checkpointer).with_config(
        {"recursion_limit": 1024}
    )


def _batch_id(state: QuestionCurationState) -> str:
    batch_id = str(state.get("batch_id", ""))
    if not batch_id:
        raise ValueError("question curation batch is missing")
    return batch_id


def _sections(state: QuestionCurationState) -> tuple[SourceSection, ...]:
    return section_sources(tuple(state.get("source_excerpts", ())))


def _discovery_units(state: QuestionCurationState):
    return pack_discovery_units(_sections(state))


def _completed_seeds(
    repository: ReviewRepository, batch_id: str
) -> list[QuestionSeed]:
    seeds: list[QuestionSeed] = []
    seen: set[str] = set()
    for item in repository.list_curation_work_items(batch_id, stage="discovery"):
        if item.status != "completed" or item.output is None:
            continue
        for seed in QuestionSeedChunk.model_validate(item.output).seeds:
            normalized = re.sub(r"\s+", "", seed.question_text).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            seeds.append(seed)
    return seeds


def _error_code(error: Exception) -> str:
    raw = str(getattr(error, "code", "curation_work_item_failed")).lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")[:100]
    return normalized if re.match(r"^[a-z]", normalized) else "curation_work_item_failed"
