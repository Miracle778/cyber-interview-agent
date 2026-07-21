from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.context import AgentContext
from app.agents.question_curation_agent import QuestionCurationAgents
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
    QuestionCandidateChunk,
    QuestionRevisionOutput,
    QuestionSeed,
    QuestionSeedChunk,
)
from app.graphs.question_curation import create_question_curation_graph
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.curation_sections import SourceSection
from app.review.repository import ReviewRepository


class FakeProviderError(RuntimeError):
    code = "provider_error"


@dataclass(frozen=True, slots=True)
class DiscoveryCall:
    unit_index: int
    sections: tuple[SourceSection, ...]


@dataclass(frozen=True, slots=True)
class EnrichmentCall:
    unit_index: int
    seeds: tuple[QuestionSeed, ...]


class RecordingCurationAgents:
    def __init__(self, *, discovery_outputs=(), enrichment_outputs=(), revision_output=None):
        self._discovery_outputs = iter(discovery_outputs)
        self._enrichment_outputs = iter(enrichment_outputs)
        self.revision_output = revision_output
        self.discovery_calls: list[DiscoveryCall] = []
        self.enrichment_calls: list[EnrichmentCall] = []
        self.revision_calls: list[object] = []

    @property
    def discovery_call_indexes(self) -> list[int]:
        return [call.unit_index for call in self.discovery_calls]

    async def discover(self, sections, *, context, config, unit_index):
        self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
        output = next(self._discovery_outputs)
        if isinstance(output, Exception):
            raise output
        return output

    async def enrich(self, seeds, *, sections, known_questions, context, config, unit_index):
        self.enrichment_calls.append(EnrichmentCall(unit_index, tuple(seeds)))
        output = next(self._enrichment_outputs)
        if isinstance(output, Exception):
            raise output
        return output

    async def revise(self, *, source_excerpts, rewrite_feedback, context, config):
        self.revision_calls.append((source_excerpts, rewrite_feedback))
        return self.revision_output


@pytest.fixture
def repository(tmp_path: Path):
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions (id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('s1', 'w1', 'question.curate', 1, 'Curation')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) VALUES ('r1', 's1', 'running')"
    )
    connection.commit()
    yield ReviewRepository(connection)
    connection.close()


@pytest.fixture
def batch(repository: ReviewRepository):
    return repository.create_batch(
        workspace_id="w1", session_id="s1", run_id="r1", source_refs=("s1",)
    )


def context(tmp_path: Path) -> AgentContext:
    return AgentContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def dense_source(question_count: int) -> str:
    return "s1:questions.md\n" + "\n".join(
        f"{index}、问题 {index}？\n答案 {index}"
        for index in range(1, question_count + 1)
    )


def curation_input(batch_id: str, *, section_count: int = 2) -> dict[str, object]:
    return {
        "batch_id": batch_id,
        "source_excerpts": [dense_source(section_count)],
        "similar_questions": [],
        "rewrite_feedback": None,
    }


def seed(index: int) -> QuestionSeed:
    return QuestionSeed(
        question_text=f"问题 {index}？", source_ref=f"s1#section-{index:04d}"
    )


def candidate(index: int) -> QuestionCandidate:
    return QuestionCandidate(
        title=f"题目 {index}",
        question_text=f"问题 {index}？",
        reference_answer=f"答案 {index}",
        topics=["mybatis"],
        difficulty="medium",
        key_points=[f"关键点 {index}"],
        follow_ups=[],
        source_refs=[f"s1#section-{index:04d}"],
        correction_note="结构化整理",
    )


def test_question_contracts_are_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        QuestionSeedChunk.model_validate({"seeds": [seed(1).model_dump()] * 7})
    with pytest.raises(ValidationError):
        QuestionCandidateChunk.model_validate(
            {"candidates": [candidate(1).model_dump()] * 4}
        )
    with pytest.raises(ValidationError):
        QuestionCandidateBatch.model_validate(
            {"candidates": [], "hidden_reasoning": "forbidden"}
        )


@pytest.mark.asyncio
async def test_graph_runs_bounded_discovery_then_enrichment(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        discovery_outputs=[QuestionSeedChunk(seeds=[seed(1), seed(2)])],
        enrichment_outputs=[
            QuestionCandidateChunk(candidates=[candidate(1), candidate(2)])
        ],
    )
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        curation_input(batch.id), context=context(tmp_path)
    )

    assert len(agents.discovery_calls) == 1
    assert len(agents.discovery_calls[0].sections) <= 6
    assert len(agents.enrichment_calls) == 1
    assert len(agents.enrichment_calls[0].seeds) <= 3
    assert len(result["candidates"]) == 2
    assert result["generation_phase"] == "enrichment"


@pytest.mark.asyncio
async def test_retry_reuses_completed_discovery_item(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        discovery_outputs=[
            QuestionSeedChunk(seeds=[seed(1)]),
            FakeProviderError(),
            QuestionSeedChunk(seeds=[seed(7)]),
        ],
        enrichment_outputs=[
            QuestionCandidateChunk(candidates=[candidate(1), candidate(7)])
        ],
    )
    graph = create_question_curation_graph(agents, repository=repository)
    with pytest.raises(FakeProviderError):
        await graph.ainvoke(
            curation_input(batch.id, section_count=7), context=context(tmp_path)
        )
    await graph.ainvoke(
        curation_input(batch.id, section_count=7),
        context=replace(context(tmp_path), run_id="r2"),
    )

    assert agents.discovery_call_indexes == [0, 1, 1]
    assert repository.list_curation_work_items(
        batch.id, stage="discovery"
    )[0].attempt_count == 1


@pytest.mark.asyncio
async def test_single_revision_bypasses_discovery_and_enrichment(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        revision_output=QuestionRevisionOutput(candidate=candidate(1))
    )
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        {
            **curation_input(batch.id),
            "revision_candidate_id": "candidate-1",
            "rewrite_feedback": "更具体",
        },
        context=context(tmp_path),
    )

    assert len(agents.revision_calls) == 1
    assert agents.discovery_calls == []
    assert agents.enrichment_calls == []
    assert len(result["candidates"]) == 1


@pytest.mark.asyncio
async def test_graph_caps_dense_sources_at_200_with_explicit_warning(
    repository: ReviewRepository, batch, tmp_path: Path
):
    all_seeds = [seed(index) for index in range(1, 206)]
    discovery_outputs = [
        QuestionSeedChunk(seeds=all_seeds[start : start + 6])
        for start in range(0, len(all_seeds), 6)
    ]
    enrichment_outputs = [
        QuestionCandidateChunk(
            candidates=[
                candidate(index).model_copy(update={
                    "question_text": f"唯一主题 topic-{index} 的机制与边界是什么？",
                    "topics": [f"topic-{index}"],
                })
                for index in range(start, min(start + 3, 201))
            ]
        )
        for start in range(1, 201, 3)
    ]
    agents = RecordingCurationAgents(
        discovery_outputs=discovery_outputs,
        enrichment_outputs=enrichment_outputs,
    )
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        curation_input(batch.id, section_count=205), context=context(tmp_path)
    )

    assert len(result["candidates"]) == 200
    assert {warning["code"] for warning in result["warnings"]} == {
        "candidate_limit_reached"
    }
    assert len(agents.discovery_calls) == 35
    assert len(agents.enrichment_calls) == 67


@pytest.mark.asyncio
async def test_concrete_agents_reject_unknown_source_refs(tmp_path: Path):
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": QuestionSeedChunk(
                    seeds=[QuestionSeed(question_text="问题？", source_ref="other")]
                )
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)
    with pytest.raises(ValueError, match="unknown source ref"):
        await agents.discover(
            (section,), context=context(tmp_path), config={}, unit_index=0
        )


@pytest.mark.asyncio
async def test_concrete_agents_keep_first_seed_for_duplicate_source_refs(
    tmp_path: Path,
):
    first = QuestionSeed(question_text="第一个问题？", source_ref="s1#section-0001")
    duplicate = QuestionSeed(question_text="第二个问题？", source_ref="s1#section-0001")

    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": QuestionSeedChunk(
                    seeds=[first, duplicate]
                )
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)

    result = await agents.discover(
        (section,), context=context(tmp_path), config={}, unit_index=0
    )

    assert result.seeds == [first]


@pytest.mark.asyncio
async def test_concrete_agents_keep_first_candidate_for_duplicate_source_refs(
    tmp_path: Path,
):
    first = candidate(1)
    duplicate = first.model_copy(update={"title": "重复候选"})

    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": QuestionCandidateChunk(
                    candidates=[first, duplicate]
                )
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)

    result = await agents.enrich(
        (seed(1),),
        sections=(section,),
        known_questions=(),
        context=context(tmp_path),
        config={},
        unit_index=0,
    )

    assert result.candidates == [first]
