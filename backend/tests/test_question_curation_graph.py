from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agents import question_curation_contracts as curation_contracts
from app.agents.context import AgentContext
from app.agents.prompts.question_curation_prompts import (
    QUESTION_DISCOVERY_PROMPT,
    QUESTION_ENRICHMENT_PROMPT,
)
from app.agents.question_curation_agent import (
    ModelOutputTruncatedError,
    ModelStructuredOutputMissingError,
    QuestionCurationAgents,
)
from app.agents.question_curation_contracts import (
    QuestionCandidate,
    QuestionCandidateBatch,
    QuestionCandidateChunk,
    QuestionRevisionOutput,
    QuestionSeed,
    QuestionSeedChunk,
)
from app.graphs.question_curation import create_question_curation_graph
from app.infrastructure.checkpoints import AgentCheckpointer
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.curation_sections import SourceSection, section_sources
from app.review.repository import ReviewRepository


class FakeProviderError(RuntimeError):
    code = "provider_error"


class FakeRateLimitedError(RuntimeError):
    code = "rate_limited"


class FakeRetryAfterError(RuntimeError):
    status_code = 503

    class response:
        headers = {"Retry-After": "1"}


class FakeAnthropicOverloadError(RuntimeError):
    status_code = 529


@dataclass(frozen=True, slots=True)
class DiscoveryCall:
    unit_index: int
    sections: tuple[SourceSection, ...]


@dataclass(frozen=True, slots=True)
class EnrichmentCall:
    unit_index: int
    seeds: tuple[QuestionSeed, ...]
    sections: tuple[SourceSection, ...] = ()
    known_questions: tuple[str, ...] = ()


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
        self.enrichment_calls.append(EnrichmentCall(
            unit_index,
            tuple(seeds),
            tuple(sections),
            tuple(known_questions),
        ))
        output = next(
            self._enrichment_outputs, QuestionCandidateChunk(candidates=[])
        )
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


def plain_sources(count: int) -> list[str]:
    return [
        f"plain-{index}:article.md\n" + (f"普通说明段落 {index}。" * 450)
        for index in range(count)
    ]


def curation_input(batch_id: str, *, section_count: int = 2) -> dict[str, object]:
    return {
        "batch_id": batch_id,
        "source_excerpts": [dense_source(section_count)],
        "similar_questions": [],
        "rewrite_feedback": None,
    }


def persist_graph_input(
    repository: ReviewRepository, input_value: dict[str, object]
) -> dict[str, object]:
    batch_id = str(input_value["batch_id"])
    batch = repository.get_batch(batch_id)
    persisted = {
        **input_value,
        "batchId": batch_id,
        "sourceRefs": list(batch.source_refs),
    }
    repository._connection.execute(
        "UPDATE agent_runs SET input_json = ? WHERE id = ?",
        (json.dumps(persisted, ensure_ascii=False), batch.run_id),
    )
    repository._connection.commit()
    safe: dict[str, object] = {"batch_id": batch_id}
    revision_candidate_id = input_value.get("revision_candidate_id")
    if revision_candidate_id is not None:
        safe["revision_candidate_id"] = revision_candidate_id
    return safe


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
        QuestionSeedChunk.model_validate({"seeds": [seed(1).model_dump()] * 21})
    assert len(QuestionSeedChunk(seeds=[seed(1)] * 20).seeds) == 20
    with pytest.raises(ValidationError):
        QuestionCandidateChunk.model_validate(
            {"candidates": [candidate(1).model_dump()] * 4}
        )
    with pytest.raises(ValidationError):
        QuestionCandidateBatch.model_validate(
            {"candidates": [], "hidden_reasoning": "forbidden"}
        )


def test_question_seed_preserves_legacy_primary_ref_and_normalizes_duplicates() -> None:
    legacy = QuestionSeed.model_validate({
        "question_text": "什么是 MVCC？",
        "source_ref": "s1#section-0001",
    })
    normalized = QuestionSeed.model_validate({
        "question_text": "什么是 MVCC？",
        "source_ref": "s1#section-0001",
        "source_refs": [
            "s1#section-0001",
            "s1#section-0002",
            "s1#section-0001",
            "s1#section-0003",
        ],
    })

    assert legacy.source_refs == ["s1#section-0001"]
    assert normalized.source_refs == [
        "s1#section-0001",
        "s1#section-0002",
        "s1#section-0003",
    ]
    repeated = QuestionSeed.model_validate({
        "question_text": "什么是 MVCC？",
        "source_ref": "s1#section-0001",
        "source_refs": [
            "s1#section-0001" if index % 2 else "s1#section-0002"
            for index in range(1, 34)
        ],
    })
    assert repeated.source_refs == ["s1#section-0001", "s1#section-0002"]
    with pytest.raises(ValidationError, match="primary source ref must be first"):
        QuestionSeed.model_validate({
            "question_text": "什么是 MVCC？",
            "source_ref": "s1#section-0001",
            "source_refs": ["s1#section-0002", "s1#section-0001"],
        })
    with pytest.raises(ValidationError):
        QuestionSeed.model_validate({
            "question_text": "什么是 MVCC？",
            "source_ref": "s1#section-0001",
            "source_refs": [f"s1#section-{index:04d}" for index in range(1, 34)],
        })


def test_strict_question_seed_chunk_rejects_ungrounded_rows() -> None:
    with pytest.raises(ValidationError):
        QuestionSeedChunk.model_validate({
            "seeds": [{
                "question_text": "模型生成但没有证据引用的题目",
                "source_refs": [None],
            }]
        })


def test_strict_question_candidate_chunk_rejects_missing_metadata() -> None:
    raw = candidate(1).model_dump()
    raw.pop("title")
    raw.pop("topics")

    with pytest.raises(ValidationError):
        QuestionCandidateChunk.model_validate({"candidates": [raw]})


def test_provider_seed_normalization_caps_the_raw_list_at_twenty() -> None:
    raw = curation_contracts.ProviderQuestionSeedChunk.model_validate({
        "seeds": [
            {
                "question_text": f"问题 {index}？",
                "source_ref": f"s1#section-{index:04d}",
                "source_refs": [f"s1#section-{index:04d}"],
            }
            for index in range(1, 22)
        ]
    })

    normalized = curation_contracts.normalize_provider_seed_chunk(raw)

    assert len(normalized.seeds) == 20
    assert normalized.seeds[-1].source_ref == "s1#section-0020"


def test_provider_seed_normalization_repairs_reference_order_and_nulls() -> None:
    raw = curation_contracts.ProviderQuestionSeedChunk.model_validate({
        "seeds": [{
            "question_text": "什么是引用归一化？",
            "source_ref": "s1#section-0002",
            "source_refs": [
                "s1#section-0001",
                None,
                "s1#section-0002",
                "s1#section-0001",
            ],
        }]
    })

    normalized = curation_contracts.normalize_provider_seed_chunk(raw)

    assert normalized.seeds[0].source_refs == [
        "s1#section-0002",
        "s1#section-0001",
    ]


def test_provider_seed_normalization_drops_only_rows_without_grounding() -> None:
    raw = curation_contracts.ProviderQuestionSeedChunk.model_validate({
        "seeds": [
            {
                "question_text": "有效题目？",
                "source_ref": "s1#section-0001",
                "source_refs": ["s1#section-0001"],
            },
            {
                "question_text": "无证据题目？",
                "source_refs": [None],
            },
            {
                "question_text": "未知引用题目？",
                "source_ref": "s1#section-9999",
                "source_refs": ["s1#section-9999"],
            },
        ]
    })

    normalized = curation_contracts.normalize_provider_seed_chunk(raw)

    assert [item.source_ref for item in normalized.seeds] == [
        "s1#section-0001",
        "s1#section-9999",
    ]


def test_provider_candidate_normalization_repairs_metadata_and_seed_refs() -> None:
    raw_candidate = candidate(1).model_dump()
    raw_candidate.pop("title")
    raw_candidate.pop("topics")
    raw_candidate["source_refs"] = ["s1#section-0001"]
    raw = curation_contracts.ProviderQuestionCandidateChunk.model_validate({
        "candidates": [raw_candidate]
    })

    normalized = curation_contracts.normalize_provider_candidate_chunk(
        raw,
        seed_source_refs={
            "s1#section-0001": (
                "s1#section-0001",
                "s1#section-0002",
            )
        },
    )

    assert normalized.candidates[0].title == normalized.candidates[0].question_text
    assert normalized.candidates[0].topics == ["未分类"]
    assert normalized.candidates[0].source_refs == [
        "s1#section-0001",
        "s1#section-0002",
    ]


def test_provider_candidate_normalization_rejects_unknown_evidence() -> None:
    raw_candidate = candidate(1).model_dump()
    raw_candidate["source_refs"] = [
        "s1#section-0001",
        "s1#section-9999",
    ]

    with pytest.raises(ValueError, match="unknown source ref"):
        curation_contracts.normalize_provider_candidate_chunk(
            {"candidates": [raw_candidate]},
            seed_source_refs={"s1#section-0001": ("s1#section-0001",)},
        )


def test_provider_candidate_normalization_restores_primary_ref_order() -> None:
    raw_candidate = candidate(1).model_dump()
    raw_candidate["source_refs"] = [
        "s1#section-0002",
        "s1#section-0001",
    ]

    normalized = curation_contracts.normalize_provider_candidate_chunk(
        {"candidates": [raw_candidate]},
        seed_source_refs={
            "s1#section-0001": (
                "s1#section-0001",
                "s1#section-0002",
            )
        },
    )

    assert normalized.candidates[0].source_refs == [
        "s1#section-0001",
        "s1#section-0002",
    ]


def test_question_curation_agents_use_stage_specific_retry_policies() -> None:
    class RecordingFactory:
        def __init__(self):
            self.specs = []

        def create(self, spec, **_kwargs):
            self.specs.append(spec)
            return object()

    factory = RecordingFactory()

    QuestionCurationAgents.create(factory, model_bindings={})

    discovery, enrichment, revision = factory.specs
    assert discovery.response_format is curation_contracts.ProviderQuestionSeedChunk
    assert (
        enrichment.response_format
        is curation_contracts.ProviderQuestionCandidateChunk
    )
    assert revision.response_format is curation_contracts.ProviderQuestionCandidateChunk
    assert discovery.structured_output_handle_errors is False
    assert enrichment.structured_output_handle_errors is False
    assert revision.structured_output_handle_errors is False
    assert (
        discovery.invocation_policy.max_output_tokens,
        discovery.invocation_policy.request_timeout_seconds,
        discovery.invocation_policy.max_retries,
    ) == (2_048, 90, 1)
    assert (
        enrichment.invocation_policy.max_output_tokens,
        enrichment.invocation_policy.request_timeout_seconds,
        enrichment.invocation_policy.max_retries,
    ) == (4_096, 180, 1)
    assert (
        revision.invocation_policy.max_output_tokens,
        revision.invocation_policy.request_timeout_seconds,
        revision.invocation_policy.max_retries,
    ) == (4_096, 180, 0)


@pytest.mark.asyncio
async def test_concrete_agents_normalize_provider_discovery_output(
    tmp_path: Path,
) -> None:
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": {
                    "seeds": [{
                        "question_text": "什么是引用归一化？",
                        "source_ref": "s1#section-0002",
                        "source_refs": [
                            "s1#section-0001",
                            "s1#section-0002",
                        ],
                    }]
                }
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "正文一", "a" * 64),
        SourceSection("s1", "s1#section-0002", 2, "正文二", "b" * 64),
    )

    result = await agents.discover(
        sections, context=context(tmp_path), config={}, unit_index=0
    )

    assert result.seeds[0].source_refs == [
        "s1#section-0002",
        "s1#section-0001",
    ]


@pytest.mark.asyncio
async def test_concrete_agents_skip_heading_only_discovery_without_model_call(
    tmp_path: Path,
) -> None:
    class Runnable:
        calls = 0

        async def ainvoke(self, _input, config=None, *, context=None):
            self.calls += 1
            raise AssertionError("heading-only content must not call the model")

    runnable = Runnable()
    agents = QuestionCurationAgents(runnable, runnable, runnable)
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "# MySQL", "a" * 64),
        SourceSection("s1", "s1#section-0002", 2, "**补充记录**", "b" * 64),
    )

    result = await agents.discover(
        sections, context=context(tmp_path), config={}, unit_index=0
    )

    assert result.seeds == []
    assert runnable.calls == 0


@pytest.mark.asyncio
async def test_concrete_agents_report_truncated_reasoning_as_recoverable(
    tmp_path: Path,
) -> None:
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "result": [
                    AIMessage(
                        content=[{"type": "thinking", "thinking": "分析中"}],
                        response_metadata={"stop_reason": "max_tokens"},
                    )
                ],
                "structured_response": None,
            }

    runnable = Runnable()
    agents = QuestionCurationAgents(runnable, runnable, runnable)
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64),
    )

    with pytest.raises(ModelOutputTruncatedError) as failure:
        await agents.discover(
            sections, context=context(tmp_path), config={}, unit_index=0
        )

    assert failure.value.code == "output_truncated"


@pytest.mark.asyncio
async def test_concrete_agents_accept_explicit_zero_question_prose(
    tmp_path: Path,
) -> None:
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "messages": [
                    AIMessage(content="这些片段未包含可识别的面试题。")
                ],
                "structured_response": None,
            }

    runnable = Runnable()
    agents = QuestionCurationAgents(runnable, runnable, runnable)
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "普通随手记录", "a" * 64),
    )

    result = await agents.discover(
        sections, context=context(tmp_path), config={}, unit_index=0
    )

    assert result.seeds == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "我无法按格式输出，请稍后重试。",
        "这里可能包含一道题：线程池应该如何实现？",
    ],
)
async def test_concrete_agents_do_not_silently_drop_unstructured_content(
    tmp_path: Path, content: str
) -> None:
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "messages": [AIMessage(content=content)],
                "structured_response": None,
            }

    runnable = Runnable()
    agents = QuestionCurationAgents(runnable, runnable, runnable)
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "普通随手记录", "a" * 64),
    )

    with pytest.raises(ModelStructuredOutputMissingError):
        await agents.discover(
            sections, context=context(tmp_path), config={}, unit_index=0
        )


@pytest.mark.parametrize("_transport_failure", ["429", "5xx", "network"])
def test_curation_transport_failures_have_at_most_one_retry(
    _transport_failure: str,
) -> None:
    class RecordingFactory:
        def __init__(self):
            self.specs = []

        def create(self, spec, **_kwargs):
            self.specs.append(spec)
            return object()

    factory = RecordingFactory()
    QuestionCurationAgents.create(factory, model_bindings={})

    discovery, enrichment, _revision = factory.specs
    assert discovery.invocation_policy.max_retries == 1
    assert enrichment.invocation_policy.max_retries == 1


def test_question_curation_prompts_describe_multi_ref_bounds() -> None:
    assert "20" in QUESTION_DISCOVERY_PROMPT.system
    assert "当前窗口" in QUESTION_DISCOVERY_PROMPT.system
    assert "source_refs" in QUESTION_DISCOVERY_PROMPT.system
    assert "3" in QUESTION_ENRICHMENT_PROMPT.system
    assert "有序引用" in QUESTION_ENRICHMENT_PROMPT.system


@pytest.mark.asyncio
async def test_graph_runs_bounded_discovery_then_enrichment(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        discovery_outputs=[QuestionSeedChunk(seeds=[QuestionSeed(
            question_text="普通说明主题的机制是什么？",
            source_ref="plain-0#section-0001",
        )])],
        enrichment_outputs=[
            QuestionCandidateChunk(candidates=[candidate(1).model_copy(update={
                "question_text": "普通说明主题的机制是什么？",
                "source_refs": ["plain-0#section-0001"],
            })])
        ],
    )
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id), "source_excerpts": plain_sources(1)
        }),
        context=context(tmp_path),
    )

    assert len(agents.discovery_calls) == 1
    assert len(agents.discovery_calls[0].sections) <= 6
    assert len(agents.enrichment_calls) == 1
    assert len(agents.enrichment_calls[0].seeds) <= 3
    assert len(result["candidates"]) == 1
    assert result["generation_phase"] == "enrichment"


@pytest.mark.asyncio
async def test_structured_units_complete_without_discovery_agent_calls(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        enrichment_outputs=[
            QuestionCandidateChunk(candidates=[candidate(1), candidate(2)])
        ]
    )
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(
            repository, curation_input(batch.id, section_count=2)
        ),
        context=context(tmp_path),
    )

    discovery_items = repository.list_curation_work_items(
        batch.id, stage="discovery"
    )
    assert agents.discovery_calls == []
    assert all(item.processor_kind == "deterministic" for item in discovery_items)
    assert all(item.status == "completed" for item in discovery_items)
    assert all(item.attempt_count == 0 for item in discovery_items)
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_enrichment_commits_siblings_then_retries_only_missing_seed(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class SeedIsolationAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.peak = 0
            self.first_wave_started = asyncio.Event()
            self.release = asyncio.Event()

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index, tuple(seeds), tuple(sections), tuple(known_questions)
            ))
            if len(seeds) == 3:
                self.active += 1
                self.peak = max(self.peak, self.active)
                if self.active == 3:
                    self.first_wave_started.set()
                try:
                    await self.release.wait()
                finally:
                    self.active -= 1
            included = seeds[:-1] if len(seeds) == 3 and unit_index == 0 else seeds
            return {"candidates": [{
                "seed_key": item.seed_key,
                "title": f"题目 {item.seed_ordinal + 1}",
                "question_text": item.question_text,
                "source_answer": f"答案 {item.seed_ordinal + 1}",
                "topics": ["数据库"],
                "difficulty": "medium",
                "key_points": ["关键点"],
                "follow_ups": [],
                "source_refs": list(item.source_refs),
                "correction_note": "无需修正",
            } for item in included]}

    agents = SeedIsolationAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    task = asyncio.create_task(graph.ainvoke(
        persist_graph_input(repository, curation_input(batch.id, section_count=9)),
        context=context(tmp_path),
    ))

    await asyncio.wait_for(agents.first_wave_started.wait(), timeout=1)
    assert agents.peak == 3
    agents.release.set()
    result = await asyncio.wait_for(task, timeout=2)

    assert len(agents.enrichment_calls) == 4
    assert [len(call.seeds) for call in agents.enrichment_calls].count(1) == 1
    assert len(result["candidates"]) == 9
    assert all(
        item.status == "completed"
        for item in repository.list_curation_seed_tasks(batch.id)
    )


@pytest.mark.asyncio
async def test_enrichment_retries_malformed_tool_output_without_failing_wave(
    repository: ReviewRepository, batch, tmp_path: Path
):
    malformed = StructuredOutputValidationError(
        "ProviderQuestionCandidateChunk",
        ValueError("candidates must contain objects"),
        AIMessage(content="", tool_calls=[]),
    )
    agents = RecordingCurationAgents(
        enrichment_outputs=[malformed, malformed],
    )
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(
            repository, curation_input(batch.id, section_count=1)
        ),
        context=context(tmp_path),
    )

    seed_tasks = repository.list_curation_seed_tasks(batch.id)
    assert len(agents.enrichment_calls) == 2
    assert len(seed_tasks) == 1
    assert seed_tasks[0].status == "skipped"
    assert seed_tasks[0].last_error_code == "invalid_provider_response"
    assert result["candidates"] == []


@pytest.mark.asyncio
async def test_discovery_wave_runs_three_provider_calls_concurrently(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class BarrierAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__(
                enrichment_outputs=[
                    QuestionCandidateChunk(candidates=[]),
                    QuestionCandidateChunk(candidates=[]),
                ]
            )
            self.active = 0
            self.peak = 0
            self.first_wave_started = asyncio.Event()
            self.release = asyncio.Event()

        async def discover(self, sections, *, context, config, unit_index):
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            if self.active == 3:
                self.first_wave_started.set()
            try:
                await self.release.wait()
                return QuestionSeedChunk(seeds=[QuestionSeed(
                    question_text=f"说明主题 {unit_index} 的机制是什么？",
                    source_ref=sections[0].ref,
                    source_refs=[section.ref for section in sections],
                )])
            finally:
                self.active -= 1

    agents = BarrierAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    task = asyncio.create_task(graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": plain_sources(6),
        }),
        context=context(tmp_path),
    ))

    await asyncio.wait_for(agents.first_wave_started.wait(), timeout=1)
    assert agents.peak == 3
    agents.release.set()
    result = await asyncio.wait_for(task, timeout=2)

    assert agents.peak == 3
    assert len(agents.discovery_calls) == 6
    assert result["generated_candidate_count"] == 0


@pytest.mark.asyncio
async def test_graph_emits_monotonic_progress_after_each_bounded_wave(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class ProgressAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()

        async def discover(self, sections, *, context, config, unit_index):
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            return QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"说明主题 {unit_index} 的机制是什么？",
                source_ref=sections[0].ref,
                source_refs=[section.ref for section in sections],
            )])

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index, tuple(seeds), tuple(sections), tuple(known_questions)
            ))
            return QuestionCandidateChunk(candidates=[])

    agents = ProgressAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    discovery_completed: list[int] = []
    async for state in graph.astream(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": plain_sources(7),
        }),
        context=context(tmp_path),
        stream_mode="values",
    ):
        if state.get("generation_phase") == "discovery":
            discovery_completed.append(int(state.get("completed_units", 0)))

    assert discovery_completed == [0, 3, 6, 7]
    assert discovery_completed == sorted(discovery_completed)


@pytest.mark.asyncio
async def test_discovery_wave_keeps_siblings_and_reports_one_failed_block(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class PartialFailureAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()

        async def discover(self, sections, *, context, config, unit_index):
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            if unit_index == 1:
                raise FakeProviderError("private provider body")
            await asyncio.sleep(0.01)
            return QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"说明主题 {unit_index} 的机制是什么？",
                source_ref=sections[0].ref,
                source_refs=[section.ref for section in sections],
            )])

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index, tuple(seeds), tuple(sections), tuple(known_questions)
            ))
            return QuestionCandidateChunk(candidates=[
                QuestionCandidate(
                    title=f"题目 {item.seed_ordinal + 1}",
                    question_text=item.question_text,
                    reference_answer="答案",
                    topics=["topic"],
                    difficulty="medium",
                    key_points=["关键点"],
                    follow_ups=[],
                    source_refs=list(item.source_refs),
                    correction_note="结构化整理",
                )
                for item in seeds
            ])

    agents = PartialFailureAgents()
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": plain_sources(3),
        }),
        context=context(tmp_path),
    )

    items = repository.list_curation_work_items(batch.id, stage="discovery")
    assert [item.status for item in items] == ["completed", "failed", "completed"]
    assert [item.attempt_count for item in items] == [1, 2, 1]
    assert agents.discovery_call_indexes.count(1) == 2
    assert items[0].output is not None
    assert items[2].output is not None
    assert len(result["candidates"]) == 2
    assert result["warnings"] == [{
        "code": "curation_discovery_block_failed",
        "stage": "discovery",
        "unitIndex": 1,
        "sourceId": "plain-1",
        "sourceRefs": [
            "plain-1#section-0001",
            "plain-1#section-0002",
            "plain-1#section-0003",
        ],
        "errorCode": "provider_error",
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_type",
    [FakeRateLimitedError, FakeRetryAfterError, FakeAnthropicOverloadError],
)
async def test_rate_limited_block_is_skipped_and_reduces_current_batch_to_one(
    repository: ReviewRepository, batch, tmp_path: Path, failure_type
):
    class RateLimitedAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()

        async def discover(self, sections, *, context, config, unit_index):
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            if unit_index == 1:
                raise failure_type("private provider overload response")
            await asyncio.sleep(0.01)
            return QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"说明主题 {unit_index} 的机制是什么？",
                source_ref=sections[0].ref,
                source_refs=[section.ref for section in sections],
            )])

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            return QuestionCandidateChunk(candidates=[
                QuestionCandidate(
                    title=f"题目 {item.seed_ordinal + 1}",
                    question_text=item.question_text,
                    reference_answer="答案",
                    topics=["topic"],
                    difficulty="medium",
                    key_points=["关键点"],
                    follow_ups=[],
                    source_refs=list(item.source_refs),
                    correction_note="结构化整理",
                )
                for item in seeds
            ])

    agents = RateLimitedAgents()
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": plain_sources(3),
        }),
        context=context(tmp_path),
    )

    assert repository.get_batch(batch.id).concurrency_limit == 1
    assert [
        item.status
        for item in repository.list_curation_work_items(batch.id, stage="discovery")
    ] == ["completed", "failed", "completed"]
    assert agents.discovery_call_indexes.count(1) == 2
    assert len(result["candidates"]) == 2
    assert result["warnings"][0]["errorCode"] == "rate_limited"


@pytest.mark.asyncio
async def test_enrichment_provider_failure_retries_then_skips_without_losing_results(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        enrichment_outputs=[
            FakeProviderError("private provider body"),
            FakeProviderError("private provider body"),
        ],
    )
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(
            repository, curation_input(batch.id, section_count=1)
        ),
        context=context(tmp_path),
    )

    seed_tasks = repository.list_curation_seed_tasks(batch.id)
    assert len(agents.enrichment_calls) == 2
    assert len(seed_tasks) == 1
    assert seed_tasks[0].status == "skipped"
    assert seed_tasks[0].last_error_code == "provider_error"
    assert result["candidates"] == []
    assert result["warnings"] == [{
        "code": "curation_enrichment_item_skipped",
        "stage": "enrichment",
        "seedOrdinal": 0,
        "sourceId": "s1",
        "sourceRefs": ["s1#section-0001"],
        "errorCode": "provider_error",
    }]


@pytest.mark.asyncio
async def test_graph_cancellation_interrupts_every_started_item(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class BlockingAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()
            self.active = 0
            self.started = asyncio.Event()

        async def discover(self, sections, *, context, config, unit_index):
            self.active += 1
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            if self.active == 3:
                self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    agents = BlockingAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    task = asyncio.create_task(graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": plain_sources(3),
        }),
        context=context(tmp_path),
    ))
    await asyncio.wait_for(agents.started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert agents.active == 0
    assert all(
        item.status != "running"
        for item in repository.list_curation_work_items(batch.id)
    )
    assert {
        item.status for item in repository.list_curation_work_items(batch.id)
    } == {"interrupted"}


@pytest.mark.asyncio
async def test_enrichment_uses_only_bounded_active_titles_not_prior_outputs(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class DynamicEnrichmentAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index,
                tuple(seeds),
                tuple(sections),
                tuple(known_questions),
            ))
            await asyncio.sleep(0.005 if unit_index == 0 else 0)
            return QuestionCandidateChunk(candidates=[
                QuestionCandidate(
                    title=f"generated-unit-{unit_index}-{ordinal}",
                    question_text=seed_value.question_text,
                    reference_answer="答案",
                    topics=["topic"],
                    difficulty="medium",
                    key_points=["关键点"],
                    follow_ups=[],
                    source_refs=list(seed_value.source_refs),
                    correction_note="结构化整理",
                )
                for ordinal, seed_value in enumerate(seeds)
            ])

    agents = DynamicEnrichmentAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id, section_count=6),
            "similar_questions": [f"active title {index}" for index in range(100)],
        }),
        context=context(tmp_path),
    )

    assert len(agents.enrichment_calls) == 2
    assert all(len(call.known_questions) <= 20 for call in agents.enrichment_calls)
    assert all(
        tuple(section.ref for section in call.sections)
        == tuple(dict.fromkeys(
            ref for seed_value in call.seeds for ref in seed_value.source_refs
        ))
        for call in agents.enrichment_calls
    )
    assert all(
        not any("generated-unit" in title for title in call.known_questions)
        for call in agents.enrichment_calls
    )
    assert result["generated_candidate_count"] == 6


@pytest.mark.asyncio
async def test_enrichment_ranks_active_titles_for_each_seed_chunk(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class ChunkAgents(RecordingCurationAgents):
        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index,
                tuple(seeds),
                tuple(sections),
                tuple(known_questions),
            ))
            return QuestionCandidateChunk(candidates=[])

    agents = ChunkAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    questions = [
        "alphaalpha cache invalidation?",
        "bravobravo cache stampede?",
        "charliecharlie write through?",
        "deltadelta transaction isolation?",
        "echoecho deadlock prevention?",
        "foxtrotfoxtrot lock fairness?",
    ]
    source = "s1:questions.md\n" + "\n".join(
        f"{index}、{question}\nanswer-{index}"
        for index, question in enumerate(questions, start=1)
    )
    left_titles = [
        f"{question} version-{variant}"
        for question in questions[:3]
        for variant in range(10)
    ]
    right_titles = [
        f"{question} version-{variant}"
        for question in questions[3:]
        for variant in range(10)
    ]

    await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id, section_count=6),
            "source_excerpts": [source],
            "similar_questions": [*left_titles, *right_titles],
        }),
        context=context(tmp_path),
    )

    calls = sorted(
        (call for call in agents.enrichment_calls if len(call.seeds) == 3),
        key=lambda call: call.unit_index,
    )
    assert len(calls) == 2
    assert all(len(call.known_questions) == 20 for call in calls)
    assert all(
        any(title.startswith(question) for question in questions[:3])
        and not any(title.startswith(question) for question in questions[3:])
        for title in calls[0].known_questions
    )
    assert all(
        any(title.startswith(question) for question in questions[3:])
        and not any(title.startswith(question) for question in questions[:3])
        for title in calls[1].known_questions
    )


@pytest.mark.asyncio
async def test_resume_progress_starts_at_persisted_candidate_count(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class ResumeProgressAgents(RecordingCurationAgents):
        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index,
                tuple(seeds),
                tuple(sections),
                tuple(known_questions),
            ))
            return QuestionCandidateChunk(candidates=[QuestionCandidate(
                title=f"题目 {seed_task.seed_ordinal + 1}",
                question_text=seed_task.question_text,
                reference_answer=f"答案 {seed_task.seed_ordinal + 1}",
                topics=["mybatis"],
                difficulty="medium",
                key_points=[f"关键点 {seed_task.seed_ordinal + 1}"],
                follow_ups=[],
                source_refs=list(seed_task.source_refs),
                correction_note="结构化整理",
            ) for seed_task in seeds])

    agents = ResumeProgressAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    graph_input = persist_graph_input(
        repository, curation_input(batch.id, section_count=4)
    )
    first = await graph.ainvoke(graph_input, context=context(tmp_path))
    persisted_count = first["generated_candidate_count"]
    resumed_counts: list[int] = []

    async for state in graph.astream(
        graph_input,
        context=replace(context(tmp_path), run_id="r2"),
        stream_mode="values",
    ):
        if state.get("generation_phase") in {"discovery", "enrichment"}:
            resumed_counts.append(int(state.get("generated_candidate_count", 0)))

    assert persisted_count == 4
    assert resumed_counts
    assert resumed_counts[0] >= persisted_count
    assert resumed_counts == sorted(resumed_counts)


@pytest.mark.asyncio
async def test_persisted_graph_checkpoint_contains_no_source_corpus_or_titles(
    repository: ReviewRepository, batch, tmp_path: Path
):
    source_marker = "DO_NOT_CHECKPOINT_SOURCE_CORPUS_4A01"
    title_marker = "DO_NOT_CHECKPOINT_SIMILAR_TITLE_9B02"
    agents = RecordingCurationAgents(
        enrichment_outputs=[QuestionCandidateChunk(candidates=[])]
    )
    (tmp_path / ".cyber-interview-agent").mkdir(exist_ok=True)
    async with AgentCheckpointer(tmp_path).open() as saver:
        graph = create_question_curation_graph(
            agents, repository=repository, checkpointer=saver
        )
        await graph.ainvoke(
            persist_graph_input(repository, {
                **curation_input(batch.id, section_count=1),
                "source_excerpts": [f"s1:source.md\n1、{source_marker}？\n答案"],
                "similar_questions": [title_marker],
            }),
            config={"configurable": {"thread_id": "safe-checkpoint"}},
            context=context(tmp_path),
        )
        persisted = await saver.aget_tuple(
            {"configurable": {"thread_id": "safe-checkpoint"}}
        )

        assert persisted is not None
        checkpoint_bytes = saver.serde.dumps_typed(persisted.checkpoint)[1]

    assert source_marker.encode() not in checkpoint_bytes
    assert title_marker.encode() not in checkpoint_bytes


@pytest.mark.asyncio
async def test_graph_output_state_excludes_source_text_and_unbounded_titles(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        enrichment_outputs=[QuestionCandidateChunk(candidates=[candidate(1)])]
    )
    graph = create_question_curation_graph(agents, repository=repository)

    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id, section_count=1),
            "similar_questions": [f"active title {index}" for index in range(100)],
        }),
        context=context(tmp_path),
    )

    assert "source_excerpts" not in result
    assert "similar_questions" not in result
    assert "rewrite_feedback" not in result
    assert set(result) <= {
        "batch_id",
        "revision_candidate_id",
        "discovery_work_item_ids",
        "enrichment_work_item_ids",
        "seed_task_ids",
        "generation_phase",
        "completed_units",
        "total_units",
        "generated_candidate_count",
        "candidates",
        "warnings",
    }


@pytest.mark.asyncio
async def test_retry_reuses_completed_discovery_item(
    repository: ReviewRepository, batch, tmp_path: Path
):
    class ResumeAgents(RecordingCurationAgents):
        def __init__(self):
            super().__init__()
            self.attempts: dict[int, int] = {}

        async def discover(self, sections, *, context, config, unit_index):
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            self.attempts[unit_index] = self.attempts.get(unit_index, 0) + 1
            if unit_index == 1 and self.attempts[unit_index] == 1:
                raise FakeProviderError()
            return QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"普通说明主题 {unit_index} 的机制是什么？",
                source_ref=sections[0].ref,
                source_refs=[section.ref for section in sections],
            )])

        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index, tuple(seeds), tuple(sections), tuple(known_questions)
            ))
            return QuestionCandidateChunk(candidates=[
                QuestionCandidate(
                    title=f"题目 {index}",
                    question_text=seed_value.question_text,
                    reference_answer="答案",
                    topics=["topic"],
                    difficulty="medium",
                    key_points=["关键点"],
                    follow_ups=[],
                    source_refs=list(seed_value.source_refs),
                    correction_note="结构化整理",
                )
                for index, seed_value in enumerate(seeds)
            ])

    agents = ResumeAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    graph_input = persist_graph_input(repository, {
        **curation_input(batch.id),
        "source_excerpts": plain_sources(2),
    })
    result = await graph.ainvoke(
        graph_input, context=context(tmp_path)
    )

    assert len(repository.list_curation_seed_tasks(batch.id)) == 2
    assert result["warnings"] == []
    assert agents.discovery_call_indexes.count(0) == 1
    assert agents.discovery_call_indexes.count(1) == 2
    attempts = [
        item.attempt_count
        for item in repository.list_curation_work_items(
            batch.id, stage="discovery"
        )
    ]
    assert attempts == [1, 2]
    assert all(
        item.status == "completed"
        for item in repository.list_curation_work_items(
            batch.id, stage="discovery"
        )
    )


@pytest.mark.asyncio
async def test_legacy_dense_work_item_is_split_without_replanning_identity(
    repository: ReviewRepository, batch, tmp_path: Path
) -> None:
    source_excerpt = "s1:notes.md\n" + "\n\n".join(
        f"第 {index} 条没有明确题目结构的随手记录。"
        for index in range(1, 9)
    )
    sections = section_sources((source_excerpt,))
    legacy = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="f" * 64,
        source_refs=tuple(section.ref for section in sections),
        processor_kind="model",
    )

    class LegacyAgents(RecordingCurationAgents):
        async def discover(self, sections, *, context, config, unit_index):
            self.discovery_calls.append(DiscoveryCall(unit_index, tuple(sections)))
            return QuestionSeedChunk(seeds=[QuestionSeed(
                question_text=f"{sections[0].text} 可以追问什么？",
                source_ref=sections[0].ref,
                source_refs=[section.ref for section in sections],
            )])

    agents = LegacyAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "source_excerpts": [source_excerpt],
        }),
        context=context(tmp_path),
    )

    items = repository.list_curation_work_items(batch.id, stage="discovery")
    assert [item.id for item in items] == [legacy.id]
    assert items[0].status == "completed"
    assert [len(call.sections) for call in agents.discovery_calls] == [6, 2]
    assert len(items[0].output["seeds"]) == 2


@pytest.mark.asyncio
async def test_single_revision_bypasses_discovery_and_enrichment(
    repository: ReviewRepository, batch, tmp_path: Path
):
    agents = RecordingCurationAgents(
        revision_output=QuestionRevisionOutput(candidate=candidate(1))
    )
    graph = create_question_curation_graph(agents, repository=repository)
    result = await graph.ainvoke(
        persist_graph_input(repository, {
            **curation_input(batch.id),
            "revision_candidate_id": "candidate-1",
            "rewrite_feedback": "更具体",
        }),
        context=context(tmp_path),
    )

    assert len(agents.revision_calls) == 1
    assert agents.discovery_calls == []
    assert agents.enrichment_calls == []
    assert len(result["candidates"]) == 1


@pytest.mark.asyncio
async def test_manual_seed_retry_runs_exactly_one_seed_attempt(
    repository: ReviewRepository, batch, tmp_path: Path
):
    source_ref = "s1#section-0001"
    discovery = repository.plan_curation_work_item(
        batch_id=batch.id,
        stage="discovery",
        unit_index=0,
        input_digest="a" * 64,
        source_refs=(source_ref,),
        processor_kind="deterministic",
    )
    repository.complete_deterministic_curation_work_item(
        discovery.id,
        output=QuestionSeedChunk(seeds=[QuestionSeed(
            question_text="问题 1？", source_ref=source_ref
        )]).model_dump(mode="json"),
    )
    task = repository.plan_curation_seed_task(
        batch_id=batch.id,
        discovery_work_item_id=discovery.id,
        seed_ordinal=0,
        question_text="问题 1？",
        primary_source_ref=source_ref,
        source_refs=(source_ref,),
        input_digest="b" * 64,
    )
    running = repository.claim_curation_seed_tasks(
        batch.id, statuses=("pending",), limit=1
    )[0]
    skipped = repository.skip_curation_seed_task(
        running.id,
        expected_version=running.version,
        error_code="missing_answer",
        normalization_issues=("missing_answer",),
    )
    repository._connection.execute(
        "UPDATE agent_runs SET status = 'completed' WHERE id = 'r1'"
    )
    repository._connection.execute(
        "INSERT INTO agent_runs (id, session_id, status) "
        "VALUES ('manual-execution', 's1', 'queued')"
    )
    repository._connection.commit()
    receipt, _created = repository.begin_curation_seed_retry(
        task.id,
        expected_version=skipped.version,
        idempotency_key="manual-retry-0001",
        request_digest="c" * 64,
        execution_id="manual-execution",
    )

    class ManualAgents(RecordingCurationAgents):
        async def enrich(
            self, seeds, *, sections, known_questions, context, config, unit_index
        ):
            self.enrichment_calls.append(EnrichmentCall(
                unit_index, tuple(seeds), tuple(sections), tuple(known_questions)
            ))
            seed_task = seeds[0]
            return {"candidates": [{
                "seed_key": seed_task.seed_key,
                "question_text": seed_task.question_text,
                "source_answer": "恢复后的材料答案",
                "topics": ["runtime"],
                "difficulty": "medium",
                "key_points": ["可恢复"],
                "follow_ups": [],
                "source_refs": list(seed_task.source_refs),
                "correction_note": "无需修正",
            }]}

    agents = ManualAgents()
    graph = create_question_curation_graph(agents, repository=repository)
    graph_input = persist_graph_input(
        repository, curation_input(batch.id, section_count=1)
    )
    graph_input.update({
        "manual_seed_task_id": task.id,
        "manual_seed_expected_version": skipped.version,
        "manual_seed_retry_key": "manual-retry-0001",
    })

    await graph.ainvoke(graph_input, context=context(tmp_path))

    restored = repository.get_curation_seed_task(task.id)
    assert len(agents.enrichment_calls) == 1
    assert (restored.status, restored.manual_attempt_count) == ("degraded", 1)
    assert (
        repository.get_curation_seed_retry_receipt(receipt.id).result_status
        == "degraded"
    )


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
        persist_graph_input(
            repository, curation_input(batch.id, section_count=205)
        ),
        context=context(tmp_path),
    )

    assert len(result["candidates"]) == 200
    assert {warning["code"] for warning in result["warnings"]} == {
        "candidate_limit_reached"
    }
    assert len(agents.discovery_calls) == 0
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
async def test_schema_validation_is_not_retried_by_the_curation_agent(
    tmp_path: Path,
):
    class Runnable:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, _input, config=None, *, context=None):
            self.calls += 1
            return {"structured_response": {"seeds": "not-a-list"}}

    runnable = Runnable()
    agents = QuestionCurationAgents(runnable, runnable, runnable)
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)

    with pytest.raises(ValidationError):
        await agents.discover(
            (section,), context=context(tmp_path), config={}, unit_index=0
        )

    assert runnable.calls == 1


@pytest.mark.asyncio
async def test_concrete_agents_reject_unknown_secondary_source_refs(tmp_path: Path):
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": QuestionSeedChunk(seeds=[QuestionSeed(
                    question_text="问题？",
                    source_ref="s1#section-0001",
                    source_refs=["s1#section-0001", "s1#section-9999"],
                )])
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    section = SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64)

    with pytest.raises(ValueError, match="unknown source ref"):
        await agents.discover(
            (section,), context=context(tmp_path), config={}, unit_index=0
        )


@pytest.mark.asyncio
async def test_concrete_agents_reject_cross_source_seed_refs(tmp_path: Path):
    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {
                "structured_response": QuestionSeedChunk(seeds=[QuestionSeed(
                    question_text="问题？",
                    source_ref="s1#section-0001",
                    source_refs=["s1#section-0001", "s2#section-0001"],
                )])
            }

    agents = QuestionCurationAgents(Runnable(), Runnable(), Runnable())
    sections = (
        SourceSection("s1", "s1#section-0001", 1, "正文", "a" * 64),
        SourceSection("s2", "s2#section-0001", 1, "正文", "b" * 64),
    )

    with pytest.raises(ValueError, match="cross-source"):
        await agents.discover(
            sections, context=context(tmp_path), config={}, unit_index=0
        )


@pytest.mark.asyncio
async def test_concrete_agents_preserve_untrusted_refs_for_normalization_boundary(
    tmp_path: Path,
):
    invalid = candidate(1).model_copy(update={
        "source_refs": ["s1#section-0001", "s1#section-9999"]
    })

    class Runnable:
        async def ainvoke(self, _input, config=None, *, context=None):
            return {"structured_response": QuestionCandidateChunk(candidates=[invalid])}

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

    assert result.candidates[0].source_refs == [
        "s1#section-0001",
        "s1#section-9999",
    ]


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
async def test_concrete_agents_preserve_duplicate_candidates_for_quality_boundary(
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

    assert [item.title for item in result.candidates] == ["题目 1", "重复候选"]
