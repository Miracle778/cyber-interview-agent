from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
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
from app.review.curation_planner import plan_curation_discovery
from app.review.curation_scheduler import (
    CurationWaveResult,
    curation_error_code,
    is_curation_overload_error,
    run_curation_wave,
)
from app.review.curation_sections import SourceSection, section_sources
from app.review.question_similarity import question_similarity, same_question
from app.review.repository import ReviewRepository


class CurationWaveFailed(RuntimeError):
    def __init__(self, error_code: str) -> None:
        self.code = error_code
        super().__init__("curation work wave failed")


class QuestionCurationInput(TypedDict, total=False):
    batch_id: str
    revision_candidate_id: str | None


class QuestionCurationState(TypedDict, total=False):
    batch_id: str
    revision_candidate_id: str | None
    discovery_work_item_ids: list[str]
    enrichment_work_item_ids: list[str]
    generation_phase: Literal["discovery", "enrichment"]
    completed_units: int
    total_units: int
    generated_candidate_count: int
    candidates: list[dict[str, Any]]
    warnings: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class CurationInvocationInput:
    source_excerpts: tuple[str, ...]
    similar_questions: tuple[str, ...]
    rewrite_feedback: str | None


class CurationInvocationInputProvider:
    """Execution-scoped access to immutable input kept outside Graph state."""

    def __init__(self, repository: ReviewRepository) -> None:
        self._repository = repository
        self._loaded: dict[str, CurationInvocationInput] = {}

    def load(self, batch_id: str) -> CurationInvocationInput:
        cached = self._loaded.get(batch_id)
        if cached is not None:
            return cached
        raw = self._repository.curation_batch_input(batch_id)
        source_excerpts = raw.get("source_excerpts")
        similar_questions = raw.get("similar_questions", [])
        rewrite_feedback = raw.get("rewrite_feedback")
        if not isinstance(source_excerpts, list) or not all(
            isinstance(value, str) for value in source_excerpts
        ):
            raise ValueError("question curation source input is missing")
        if not isinstance(similar_questions, list) or not all(
            isinstance(value, str) for value in similar_questions
        ):
            raise ValueError("question curation similar-title input is invalid")
        if rewrite_feedback is not None and not isinstance(rewrite_feedback, str):
            raise ValueError("question curation rewrite feedback is invalid")
        loaded = CurationInvocationInput(
            source_excerpts=tuple(source_excerpts),
            similar_questions=tuple(similar_questions),
            rewrite_feedback=rewrite_feedback,
        )
        self._loaded[batch_id] = loaded
        return loaded

    def discard(self, batch_id: str) -> None:
        self._loaded.pop(batch_id, None)


def create_question_curation_graph(
    agents: QuestionCurationAgents,
    *,
    repository: ReviewRepository,
    checkpointer=None,
):
    invocation_inputs = CurationInvocationInputProvider(repository)

    async def revise_one(
        state: QuestionCurationInput,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        invocation_input = invocation_inputs.load(_batch_id(state))
        output = await agents.revise(
            source_excerpts=invocation_input.source_excerpts,
            rewrite_feedback=(
                invocation_input.rewrite_feedback or "按审核意见改进题目"
            ),
            context=runtime.context,
            config=dict(config),
        )
        invocation_inputs.discard(_batch_id(state))
        return {
            "candidates": [output.candidate.model_dump(mode="json")],
            "generation_phase": "enrichment",
            "completed_units": 1,
            "total_units": 1,
            "generated_candidate_count": 1,
            "warnings": [],
        }

    async def plan_sections(state: QuestionCurationInput) -> dict[str, object]:
        batch_id = _batch_id(state)
        invocation_input = invocation_inputs.load(batch_id)
        plan = plan_curation_discovery(
            section_sources(invocation_input.source_excerpts)
        )
        items = []
        for unit in plan.deterministic_units:
            item = repository.plan_curation_work_item(
                batch_id=batch_id,
                stage="discovery",
                unit_index=unit.unit_index,
                input_digest=unit.input_digest,
                source_refs=unit.source_refs,
                processor_kind="deterministic",
            )
            if item.status != "completed":
                item = repository.complete_deterministic_curation_work_item(
                    item.id,
                    output=QuestionSeedChunk(seeds=list(unit.seeds)).model_dump(
                        mode="json"
                    ),
                )
            items.append(item)
        for unit in plan.model_units:
            items.append(repository.plan_curation_work_item(
                batch_id=batch_id,
                stage="discovery",
                unit_index=unit.unit_index,
                input_digest=unit.input_digest,
                source_refs=tuple(section.ref for section in unit.sections),
                processor_kind="model",
            ))
        items.sort(key=lambda item: item.unit_index)
        return {
            "discovery_work_item_ids": [item.id for item in items],
            "generation_phase": "discovery",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "generated_candidate_count": _completed_candidate_count(
                repository, batch_id
            ),
            "warnings": [],
        }

    async def discover_wave(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        batch_id = _batch_id(state)
        plan = plan_curation_discovery(
            _sections_for_batch(invocation_inputs, batch_id)
        )
        units = {unit.unit_index: unit for unit in plan.model_units}
        limit = repository.get_batch(batch_id).concurrency_limit
        pending_ids = tuple(
            item_id
            for item_id in state.get("discovery_work_item_ids", [])
            if (
                (item := repository.get_curation_work_item(item_id)).processor_kind
                == "model"
                and item.status != "completed"
            )
        )[:limit]

        async def worker(work_item_id: str) -> None:
            running = repository.start_curation_work_item(work_item_id)
            if running.status == "completed":
                return
            unit = units[running.unit_index]
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
            except asyncio.CancelledError:
                repository.interrupt_running_curation_work_items(
                    batch_id, error_code="curation_interrupted"
                )
                raise
            except Exception as error:
                if repository.get_curation_work_item(running.id).status == "running":
                    repository.fail_curation_work_item(
                        running.id, error_code=curation_error_code(error)
                    )
                raise

        result = await run_curation_wave(
            pending_ids,
            limit=limit,
            worker=worker,
        )
        _raise_wave_failure(repository, batch_id, result)
        items = repository.list_curation_work_items(batch_id, stage="discovery")
        return {
            "generation_phase": "discovery",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "generated_candidate_count": _completed_candidate_count(
                repository, batch_id
            ),
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
            source_refs = tuple(dict.fromkeys(
                ref for seed in chunk for ref in seed.source_refs
            ))
            items.append(repository.plan_curation_work_item(
                batch_id=batch_id,
                stage="enrichment",
                unit_index=unit_index,
                input_digest=sha256(encoded.encode("utf-8")).hexdigest(),
                source_refs=source_refs,
                processor_kind="model",
            ))
        return {
            "enrichment_work_item_ids": [item.id for item in items],
            "generation_phase": "enrichment",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "generated_candidate_count": _completed_candidate_count(
                repository, batch_id
            ),
            "warnings": warnings,
        }

    async def enrich_wave(
        state: QuestionCurationState,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        batch_id = _batch_id(state)
        all_seeds = _completed_seeds(repository, batch_id)[:200]
        by_ref = {
            section.ref: section
            for section in _sections_for_batch(invocation_inputs, batch_id)
        }
        similar_titles = _similar_titles_for_batch(invocation_inputs, batch_id)
        limit = repository.get_batch(batch_id).concurrency_limit
        pending_ids = tuple(
            item_id
            for item_id in state.get("enrichment_work_item_ids", [])
            if repository.get_curation_work_item(item_id).status != "completed"
        )[:limit]

        async def worker(work_item_id: str) -> None:
            running = repository.start_curation_work_item(work_item_id)
            if running.status == "completed":
                return
            seeds = all_seeds[
                running.unit_index * 3 : running.unit_index * 3 + 3
            ]
            section_refs = tuple(dict.fromkeys(
                ref for seed in seeds for ref in seed.source_refs
            ))
            sections = tuple(by_ref[ref] for ref in section_refs)
            known_questions = _prefilter_similar_titles(seeds, similar_titles)
            try:
                output = await agents.enrich(
                    seeds,
                    sections=sections,
                    known_questions=known_questions,
                    context=runtime.context,
                    config=dict(config),
                    unit_index=running.unit_index,
                )
                repository.complete_curation_work_item(
                    running.id, output=output.model_dump(mode="json")
                )
            except asyncio.CancelledError:
                repository.interrupt_running_curation_work_items(
                    batch_id, error_code="curation_interrupted"
                )
                raise
            except Exception as error:
                if repository.get_curation_work_item(running.id).status == "running":
                    repository.fail_curation_work_item(
                        running.id, error_code=curation_error_code(error)
                    )
                raise

        result = await run_curation_wave(
            pending_ids,
            limit=limit,
            worker=worker,
        )
        _raise_wave_failure(repository, batch_id, result)
        items = repository.list_curation_work_items(batch_id, stage="enrichment")
        return {
            "generation_phase": "enrichment",
            "completed_units": sum(item.status == "completed" for item in items),
            "total_units": len(items),
            "generated_candidate_count": _completed_candidate_count(
                repository, batch_id
            ),
        }

    async def reduce_candidates(state: QuestionCurationState) -> dict[str, object]:
        candidates: list[QuestionCandidate] = []
        for item in repository.list_curation_work_items(
            _batch_id(state), stage="enrichment"
        ):
            if item.status != "completed" or item.output is None:
                continue
            for candidate in QuestionCandidateChunk.model_validate(
                item.output
            ).candidates:
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
                    "source_refs": list(dict.fromkeys([
                        *existing.source_refs, *candidate.source_refs
                    ])),
                    "key_points": list(dict.fromkeys([
                        *existing.key_points, *candidate.key_points
                    ])),
                    "follow_ups": list(dict.fromkeys([
                        *existing.follow_ups, *candidate.follow_ups
                    ])),
                })
        batch = QuestionCandidateBatch(candidates=candidates[:200])
        total = len(state.get("enrichment_work_item_ids", []))
        generated_candidate_count = _completed_candidate_count(
            repository, _batch_id(state)
        )
        invocation_inputs.discard(_batch_id(state))
        return {
            "candidates": batch.model_dump(mode="json")["candidates"],
            "generation_phase": "enrichment",
            "completed_units": total,
            "total_units": total,
            "generated_candidate_count": generated_candidate_count,
        }

    def route_mode(state: QuestionCurationInput) -> str:
        return "revision" if state.get("revision_candidate_id") else "curate"

    def discovery_route(state: QuestionCurationState) -> str:
        return (
            "pending"
            if any(
                repository.get_curation_work_item(item_id).status != "completed"
                for item_id in state.get("discovery_work_item_ids", [])
            )
            else "done"
        )

    def enrichment_route(state: QuestionCurationState) -> str:
        return (
            "pending"
            if any(
                repository.get_curation_work_item(item_id).status != "completed"
                for item_id in state.get("enrichment_work_item_ids", [])
            )
            else "done"
        )

    graph = StateGraph(
        QuestionCurationState,
        context_schema=AgentContext,
        input_schema=QuestionCurationInput,
    )
    graph.add_node(
        "revise_one", revise_one, input_schema=QuestionCurationInput
    )
    graph.add_node(
        "plan_sections", plan_sections, input_schema=QuestionCurationInput
    )
    graph.add_node("discover_wave", discover_wave)
    graph.add_node("plan_enrichment", plan_enrichment)
    graph.add_node("enrich_wave", enrich_wave)
    graph.add_node("reduce_candidates", reduce_candidates)
    graph.add_conditional_edges(
        START, route_mode, {"revision": "revise_one", "curate": "plan_sections"}
    )
    graph.add_edge("revise_one", END)
    graph.add_edge("plan_sections", "discover_wave")
    graph.add_conditional_edges(
        "discover_wave",
        discovery_route,
        {"pending": "discover_wave", "done": "plan_enrichment"},
    )
    graph.add_edge("plan_enrichment", "enrich_wave")
    graph.add_conditional_edges(
        "enrich_wave",
        enrichment_route,
        {"pending": "enrich_wave", "done": "reduce_candidates"},
    )
    graph.add_edge("reduce_candidates", END)
    return graph.compile(checkpointer=checkpointer).with_config(
        {"recursion_limit": 1024}
    )


def _batch_id(state: QuestionCurationState | QuestionCurationInput) -> str:
    batch_id = str(state.get("batch_id", ""))
    if not batch_id:
        raise ValueError("question curation batch is missing")
    return batch_id


def _sections_for_batch(
    invocation_inputs: CurationInvocationInputProvider,
    batch_id: str,
) -> tuple[SourceSection, ...]:
    return section_sources(invocation_inputs.load(batch_id).source_excerpts)


def _similar_titles_for_batch(
    invocation_inputs: CurationInvocationInputProvider,
    batch_id: str,
) -> tuple[str, ...]:
    return invocation_inputs.load(batch_id).similar_questions


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


def _completed_candidate_count(
    repository: ReviewRepository, batch_id: str
) -> int:
    return sum(
        len(QuestionCandidateChunk.model_validate(item.output).candidates)
        for item in repository.list_curation_work_items(
            batch_id, stage="enrichment"
        )
        if item.status == "completed" and item.output is not None
    )


def _prefilter_similar_titles(
    seeds: list[QuestionSeed], titles: tuple[str, ...], *, limit: int = 20
) -> tuple[str, ...]:
    unique_titles = tuple(dict.fromkeys(
        title.strip() for title in titles if title.strip()
    ))
    ranked = sorted(
        enumerate(unique_titles),
        key=lambda entry: (
            -max(
                (
                    question_similarity(seed.question_text, entry[1])
                    for seed in seeds
                ),
                default=0.0,
            ),
            entry[0],
        ),
    )
    return tuple(title for _index, title in ranked[:limit])


def _raise_wave_failure(
    repository: ReviewRepository,
    batch_id: str,
    result: CurationWaveResult,
) -> None:
    if not result.failed:
        return
    error_codes = tuple(error_code for _item_id, error_code in result.failed)
    overload = next(
        (code for code in error_codes if is_curation_overload_error(code)), None
    )
    if overload is not None:
        repository.reduce_curation_concurrency(batch_id, error_code=overload)
    raise CurationWaveFailed(error_codes[0])
