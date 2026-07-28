from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Literal, TypedDict

from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.question_curation_agent import (
    ModelOutputTruncatedError,
    QuestionCurationAgents,
)
from app.agents.question_curation_normalization import (
    normalize_provider_candidate_observation,
)
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
    QuestionSeedBatch,
    QuestionSeedChunk,
)
from app.review.curation_planner import (
    pack_model_sections,
    plan_curation_discovery,
)
from app.review.curation_seed_reconciliation import reconcile_curation_seed_tasks
from app.review.curation_scheduler import (
    CurationWaveResult,
    curation_error_code,
    is_curation_overload_error,
    run_curation_invocation_wave,
    run_curation_wave,
)
from app.review.curation_sections import SourceSection, section_sources
from app.review.models import CurationSeedTaskRecord, QuestionCandidateRecord
from app.review.question_similarity import question_similarity, same_question
from app.review.repository import ReviewRepository


class CurationWaveFailed(RuntimeError):
    def __init__(self, error_code: str) -> None:
        self.code = error_code
        super().__init__("curation work wave failed")


class QuestionCurationInput(TypedDict, total=False):
    batch_id: str
    revision_candidate_id: str | None
    manual_seed_task_id: str | None
    manual_seed_expected_version: int
    manual_seed_retry_key: str


class QuestionCurationState(TypedDict, total=False):
    batch_id: str
    revision_candidate_id: str | None
    discovery_work_item_ids: list[str]
    enrichment_work_item_ids: list[str]
    seed_task_ids: list[str]
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


async def _discover_bounded(
    agents: QuestionCurationAgents,
    sections: tuple[SourceSection, ...],
    *,
    context: AgentContext,
    config: dict[str, Any],
    parent_unit_index: int,
) -> QuestionSeedBatch:
    """Recover legacy dense work items without changing their durable identity."""
    call_ordinal = 0

    async def invoke(partition: tuple[SourceSection, ...]) -> list:
        nonlocal call_ordinal
        invocation_index = (
            parent_unit_index
            if len(sections) == len(partition)
            else 1_000_000 + parent_unit_index * 10_000 + call_ordinal
        )
        call_ordinal += 1
        try:
            chunk = await agents.discover(
                partition,
                context=context,
                config=config,
                unit_index=invocation_index,
            )
        except ModelOutputTruncatedError:
            if len(partition) == 1:
                raise
            midpoint = len(partition) // 2
            return [
                *await invoke(partition[:midpoint]),
                *await invoke(partition[midpoint:]),
            ]
        return list(chunk.seeds)

    seeds = []
    for partition in pack_model_sections(sections):
        seeds.extend(await invoke(partition))

    deduplicated = []
    seen_primary_refs: set[str] = set()
    for seed in seeds:
        if seed.source_ref in seen_primary_refs:
            continue
        seen_primary_refs.add(seed.source_ref)
        deduplicated.append(seed)
    return QuestionSeedBatch(seeds=deduplicated)


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
        batch_id = _batch_id(state)
        invocation_input = invocation_inputs.load(batch_id)
        candidate_id = str(state.get("revision_candidate_id") or "")
        try:
            original = repository.get_candidate(candidate_id)
        except LookupError:
            # Compatibility for isolated graph consumers without product records.
            output = await agents.revise(
                source_excerpts=invocation_input.source_excerpts,
                rewrite_feedback=(
                    invocation_input.rewrite_feedback or "按审核意见改进题目"
                ),
                context=runtime.context,
                config=dict(config),
            )
            invocation_inputs.discard(batch_id)
            candidate = getattr(output, "candidate", None)
            return {
                "candidates": (
                    []
                    if candidate is None
                    else [candidate.model_dump(mode="json")]
                ),
                "generation_phase": "enrichment",
                "completed_units": 1,
                "total_units": 1,
                "generated_candidate_count": int(candidate is not None),
                "warnings": [],
            }

        seed = _revision_seed_task(batch_id, original)
        outcome = None
        for attempt in (1, 2):
            running = replace(
                seed,
                automatic_attempt_count=attempt,
                version=attempt,
            )
            output = await agents.revise(
                source_excerpts=invocation_input.source_excerpts,
                rewrite_feedback=(
                    invocation_input.rewrite_feedback or "按审核意见改进题目"
                ),
                seed=running,
                context=runtime.context,
                config=dict(config),
            )
            outcome = normalize_provider_candidate_observation(
                output, seed_tasks=(running,)
            )[0]
            if outcome.status != "retryable":
                break
        invocation_inputs.discard(batch_id)
        normalized = None if outcome is None else outcome.candidate
        return {
            "candidates": [] if normalized is None else [normalized],
            "generation_phase": "enrichment",
            "completed_units": 1,
            "total_units": 1,
            "generated_candidate_count": int(normalized is not None),
            "warnings": (
                []
                if normalized is not None
                else [{"code": "revision_candidate_skipped"}]
            ),
        }

    async def retry_one_seed(
        state: QuestionCurationInput,
        config: RunnableConfig,
        runtime: Runtime[AgentContext],
    ) -> dict[str, object]:
        batch_id = _batch_id(state)
        task_id = str(state.get("manual_seed_task_id") or "")
        retry_key = str(state.get("manual_seed_retry_key") or "")
        expected_version = int(state.get("manual_seed_expected_version", -1))
        receipt = repository.find_curation_seed_retry_receipt(task_id, retry_key)
        if receipt is None:
            raise ValueError("manual curation seed retry receipt is missing")
        running = repository.claim_manual_curation_seed_retry(
            receipt.id, expected_seed_version=expected_version
        )
        by_ref = {
            section.ref: section
            for section in _sections_for_batch(invocation_inputs, batch_id)
        }
        sections = tuple(by_ref[ref] for ref in running.source_refs)
        try:
            output = await agents.enrich(
                (running,),
                sections=sections,
                known_questions=_prefilter_similar_titles(
                    (running,), _similar_titles_for_batch(invocation_inputs, batch_id)
                ),
                context=runtime.context,
                config=dict(config),
                unit_index=running.seed_ordinal,
            )
        except (ValidationError, ValueError):
            output = {"candidates": "invalid"}
        except asyncio.CancelledError:
            _interrupt_seed_invocation(
                repository, (running,), "curation_interrupted"
            )
            raise
        except Exception as error:
            _interrupt_seed_invocation(
                repository, (running,), curation_error_code(error)
            )
            raise
        outcome = normalize_provider_candidate_observation(
            output, seed_tasks=(running,)
        )[0]
        if outcome.status in {"completed", "degraded"}:
            repository.complete_curation_seed_task(
                running.id,
                expected_version=running.version,
                status=outcome.status,
                candidate=outcome.candidate or {},
                answer_basis=outcome.answer_basis,
                material_support=outcome.material_support,
                needs_review=outcome.needs_review,
                normalization_issues=outcome.normalization_issues,
            )
        else:
            repository.skip_curation_seed_task(
                running.id,
                expected_version=running.version,
                error_code=outcome.error_code or "invalid_candidate",
                normalization_issues=outcome.normalization_issues,
            )
        invocation_inputs.discard(batch_id)
        return {
            "candidates": [],
            "generation_phase": "enrichment",
            "completed_units": 1,
            "total_units": 1,
            "generated_candidate_count": int(outcome.candidate is not None),
            "warnings": [],
        }

    async def plan_sections(state: QuestionCurationInput) -> dict[str, object]:
        batch_id = _batch_id(state)
        existing = repository.list_curation_work_items(
            batch_id, stage="discovery"
        )
        if existing:
            return {
                "discovery_work_item_ids": [item.id for item in existing],
                "generation_phase": "discovery",
                "completed_units": sum(
                    item.status == "completed" for item in existing
                ),
                "total_units": len(existing),
                "generated_candidate_count": _completed_candidate_count(
                    repository, batch_id
                ),
                "warnings": [],
            }
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
        all_sections = _sections_for_batch(invocation_inputs, batch_id)
        sections_by_ref = {section.ref: section for section in all_sections}
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
            try:
                sections = tuple(
                    sections_by_ref[source_ref]
                    for source_ref in running.source_refs
                )
                output = await _discover_bounded(
                    agents,
                    sections,
                    context=runtime.context,
                    config=dict(config),
                    parent_unit_index=running.unit_index,
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
        reconciliation = reconcile_curation_seed_tasks(repository, batch_id)
        seeds = list(repository.list_curation_seed_tasks(batch_id))
        warnings = list(state.get("warnings", []))
        for warning in reconciliation.warnings:
            if warning not in warnings:
                warnings.append(warning)
        if len(seeds) > 200:
            seeds = seeds[:200]
            warning = {"code": "candidate_limit_reached", "limit": 200}
            if warning not in warnings:
                warnings.append(warning)
        return {
            "seed_task_ids": [item.id for item in seeds],
            "generation_phase": "enrichment",
            "completed_units": sum(_seed_terminal(item.status) for item in seeds),
            "total_units": len(seeds),
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
        by_ref = {
            section.ref: section
            for section in _sections_for_batch(invocation_inputs, batch_id)
        }
        similar_titles = _similar_titles_for_batch(invocation_inputs, batch_id)
        limit = repository.get_batch(batch_id).concurrency_limit
        selected_ids = set(state.get("seed_task_ids", []))
        selected = [
            task for task in repository.list_curation_seed_tasks(batch_id)
            if task.id in selected_ids
        ]
        if any(task.status == "pending" for task in selected):
            claimed = tuple(
                task for task in repository.claim_curation_seed_tasks(
                    batch_id, statuses=("pending",), limit=min(9, limit * 3)
                ) if task.id in selected_ids
            )
            invocations = tuple(
                tuple(task.id for task in claimed[start : start + 3])
                for start in range(0, len(claimed), 3)
            )
        else:
            claimed = tuple(
                task for task in repository.claim_curation_seed_tasks(
                    batch_id, statuses=("retryable",), limit=limit
                ) if task.id in selected_ids
            )
            invocations = tuple((task.id,) for task in claimed)

        async def worker(seed_task_ids: tuple[str, ...]) -> None:
            seeds = tuple(repository.get_curation_seed_task(item_id) for item_id in seed_task_ids)
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
                    unit_index=seeds[0].seed_ordinal,
                )
            except asyncio.CancelledError:
                _interrupt_seed_invocation(
                    repository,
                    seeds,
                    "curation_interrupted",
                    refund_automatic_attempt=True,
                )
                raise
            except (
                StructuredOutputValidationError,
                ValidationError,
                ValueError,
            ):
                output = {"candidates": "invalid"}
            except Exception as error:
                _interrupt_seed_invocation(
                    repository, seeds, curation_error_code(error)
                )
                raise
            try:
                outcomes = normalize_provider_candidate_observation(
                    output, seed_tasks=seeds
                )
                for outcome in outcomes:
                    current = repository.get_curation_seed_task(
                        outcome.seed_task_id
                    )
                    if outcome.status in {"completed", "degraded"}:
                        repository.complete_curation_seed_task(
                            current.id,
                            expected_version=current.version,
                            status=outcome.status,
                            candidate=outcome.candidate or {},
                            answer_basis=outcome.answer_basis,
                            material_support=outcome.material_support,
                            needs_review=outcome.needs_review,
                            normalization_issues=outcome.normalization_issues,
                        )
                    elif current.automatic_attempt_count >= 2:
                        repository.skip_curation_seed_task(
                            current.id,
                            expected_version=current.version,
                            error_code=(
                                outcome.error_code or "invalid_candidate"
                            ),
                            normalization_issues=outcome.normalization_issues,
                        )
                    else:
                        repository.mark_curation_seed_retryable(
                            current.id,
                            expected_version=current.version,
                            error_code=(
                                outcome.error_code or "invalid_candidate"
                            ),
                            normalization_issues=outcome.normalization_issues,
                        )
            except Exception as error:
                _interrupt_seed_invocation(
                    repository, seeds, curation_error_code(error)
                )
                raise

        result = await run_curation_invocation_wave(
            invocations,
            limit=limit,
            worker=worker,
        )
        _raise_wave_failure(repository, batch_id, result)
        items = [
            task for task in repository.list_curation_seed_tasks(batch_id)
            if task.id in selected_ids
        ]
        return {
            "generation_phase": "enrichment",
            "completed_units": sum(_seed_terminal(item.status) for item in items),
            "total_units": len(items),
            "generated_candidate_count": _completed_candidate_count(
                repository, batch_id
            ),
        }

    async def reduce_candidates(state: QuestionCurationState) -> dict[str, object]:
        candidates: list[QuestionCandidate] = []
        selected_ids = set(state.get("seed_task_ids", []))
        for item in repository.list_curation_seed_tasks(_batch_id(state)):
            if item.id not in selected_ids or item.candidate is None:
                continue
            for candidate in (QuestionCandidate.model_validate(item.candidate),):
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
        total = len(state.get("seed_task_ids", []))
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
        if state.get("manual_seed_task_id"):
            return "manual_retry"
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
                not _seed_terminal(repository.get_curation_seed_task(item_id).status)
                for item_id in state.get("seed_task_ids", [])
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
        "retry_one_seed", retry_one_seed, input_schema=QuestionCurationInput
    )
    graph.add_node(
        "plan_sections", plan_sections, input_schema=QuestionCurationInput
    )
    graph.add_node("discover_wave", discover_wave)
    graph.add_node("plan_enrichment", plan_enrichment)
    graph.add_node("enrich_wave", enrich_wave)
    graph.add_node("reduce_candidates", reduce_candidates)
    graph.add_conditional_edges(
        START,
        route_mode,
        {
            "manual_retry": "retry_one_seed",
            "revision": "revise_one",
            "curate": "plan_sections",
        },
    )
    graph.add_edge("retry_one_seed", END)
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


def _completed_candidate_count(
    repository: ReviewRepository, batch_id: str
) -> int:
    seed_tasks = repository.list_curation_seed_tasks(batch_id)
    if seed_tasks:
        return sum(task.candidate is not None for task in seed_tasks)
    return sum(
        len(item.output.get("candidates", ()))
        for item in repository.list_curation_work_items(
            batch_id, stage="enrichment"
        )
        if item.status == "completed" and item.output is not None
    )


def _prefilter_similar_titles(
    seeds: tuple[CurationSeedTaskRecord, ...],
    titles: tuple[str, ...],
    *,
    limit: int = 20,
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


def _seed_terminal(status: str) -> bool:
    return status in {"completed", "degraded", "skipped"}


def _revision_seed_task(
    batch_id: str, candidate: QuestionCandidateRecord
) -> CurationSeedTaskRecord:
    source_refs = candidate.source_refs
    if not source_refs:
        raise ValueError("revision candidate has no authoritative source refs")
    seed_key = sha256(f"{batch_id}{candidate.id}".encode("utf-8")).hexdigest()
    question_text = candidate.question.question_text
    return CurationSeedTaskRecord(
        id=f"revision:{candidate.id}",
        batch_id=batch_id,
        discovery_work_item_id=f"revision:{candidate.id}",
        seed_key=seed_key,
        seed_ordinal=0,
        question_text=question_text,
        primary_source_ref=source_refs[0],
        source_refs=source_refs,
        input_digest=sha256(question_text.encode("utf-8")).hexdigest(),
        status="running",
        automatic_attempt_count=0,
        manual_attempt_count=0,
        candidate=None,
        answer_basis="unknown",
        material_support="unknown",
        needs_review=True,
        normalization_issues=(),
        last_error_code=None,
        version=0,
        created_at="",
        updated_at="",
    )


def _interrupt_seed_invocation(
    repository: ReviewRepository,
    seeds: tuple[CurationSeedTaskRecord, ...],
    error_code: str,
    *,
    refund_automatic_attempt: bool = False,
) -> None:
    for seed in seeds:
        current = repository.get_curation_seed_task(seed.id)
        if current.status == "running":
            repository.interrupt_curation_seed_task(
                current.id,
                expected_version=current.version,
                error_code=error_code,
                refund_automatic_attempt=refund_automatic_attempt,
            )


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
