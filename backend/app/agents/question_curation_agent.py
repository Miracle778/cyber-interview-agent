from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.agent_factory import AgentFactory, AgentSpec
from app.agents.agent_invocation import isolated_thread_config
from app.agents.agent_model_resolver import ModelInvocationPolicy
from app.agents.agent_protocols import AgentRunnable
from app.agents.context import AgentContext
from app.agents.prompts.question_curation_prompts import (
    QUESTION_DISCOVERY_PROMPT,
    QUESTION_ENRICHMENT_PROMPT,
    QUESTION_REVISION_PROMPT,
    render_question_discovery_input,
    render_question_enrichment_input,
    render_question_revision_input,
)
from app.agents.question_curation_contracts import (
    ProviderQuestionCandidateChunk,
    ProviderQuestionSeedChunk,
    QuestionSeed,
    QuestionSeedChunk,
    normalize_provider_seed_chunk,
)
from app.review.curation_sections import SourceSection
from app.review.models import CurationSeedTaskRecord


_DISCOVERY_POLICY = ModelInvocationPolicy(2_048, 90, 1)
_ENRICHMENT_POLICY = ModelInvocationPolicy(4_096, 180, 1)
_REVISION_POLICY = ModelInvocationPolicy(4_096, 180, 0)


@dataclass(frozen=True, slots=True)
class QuestionCurationAgents:
    discovery: AgentRunnable
    enrichment: AgentRunnable
    revision: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        tools=(),
        checkpointer=None,
    ) -> "QuestionCurationAgents":
        common = {
            "model_bindings": model_bindings,
            "checkpointer": checkpointer,
        }
        return cls(
            discovery=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_discovery",
                    prompt=QUESTION_DISCOVERY_PROMPT,
                    middleware=middleware,
                    response_format=ProviderQuestionSeedChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_DISCOVERY_POLICY,
                ),
                **common,
            ),
            enrichment=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_enrichment",
                    prompt=QUESTION_ENRICHMENT_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=ProviderQuestionCandidateChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_ENRICHMENT_POLICY,
                ),
                **common,
            ),
            revision=factory.create(
                AgentSpec(
                    role="question_generation",
                    execution_name="question_revision",
                    prompt=QUESTION_REVISION_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=ProviderQuestionCandidateChunk,
                    structured_output_handle_errors=False,
                    invocation_policy=_REVISION_POLICY,
                ),
                **common,
            ),
        )

    async def discover(
        self,
        sections: Sequence[SourceSection],
        *,
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> QuestionSeedChunk:
        result = await self.discovery.ainvoke(
            {"messages": [HumanMessage(content=render_question_discovery_input(sections))]},
            isolated_thread_config(
                config, context, f"question_discovery:{context.run_id}:{unit_index}"
            ),
            context=context,
        )
        chunk = normalize_provider_seed_chunk(_structured(result))
        allowed = {section.ref: section.source_id for section in sections}
        seeds: list[QuestionSeed] = []
        seen_refs: set[str] = set()
        for seed in chunk.seeds:
            if any(ref not in allowed for ref in seed.source_refs):
                raise ValueError("question discovery returned an unknown source ref")
            if len({allowed[ref] for ref in seed.source_refs}) != 1:
                raise ValueError("question discovery returned cross-source refs")
            if seed.source_ref in seen_refs:
                continue
            seen_refs.add(seed.source_ref)
            seeds.append(seed)
        return chunk.model_copy(update={"seeds": seeds})

    async def enrich(
        self,
        seeds: Sequence[QuestionSeed | CurationSeedTaskRecord],
        *,
        sections: Sequence[SourceSection],
        known_questions: Sequence[str],
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> ProviderQuestionCandidateChunk:
        allowed = {section.ref: section.source_id for section in sections}
        seed_refs = {
            _seed_primary_ref(seed): tuple(seed.source_refs) for seed in seeds
        }
        for seed in seeds:
            if any(ref not in allowed for ref in seed.source_refs):
                raise ValueError("question enrichment received an unknown source ref")
            if len({allowed[ref] for ref in seed.source_refs}) != 1:
                raise ValueError("question enrichment received cross-source refs")
        result = await self.enrichment.ainvoke(
            {
                "messages": [HumanMessage(content=render_question_enrichment_input(
                    seeds, sections=sections, known_questions=known_questions
                ))]
            },
            isolated_thread_config(
                config, context, f"question_enrichment:{context.run_id}:{unit_index}"
            ),
            context=context,
        )
        structured = _structured(result)
        if hasattr(structured, "model_dump"):
            structured = structured.model_dump()
        return ProviderQuestionCandidateChunk.model_validate(structured)

    async def revise(
        self,
        *,
        source_excerpts: Sequence[str],
        rewrite_feedback: str,
        seed: CurationSeedTaskRecord | None = None,
        context: AgentContext,
        config: dict[str, Any],
    ) -> ProviderQuestionCandidateChunk:
        result = await self.revision.ainvoke(
            {"messages": [HumanMessage(content=render_question_revision_input(
                source_excerpts, rewrite_feedback=rewrite_feedback, seed=seed
            ))]},
            isolated_thread_config(
                config, context, f"question_revision:{context.run_id}"
            ),
            context=context,
        )
        structured = _structured(result)
        if hasattr(structured, "model_dump"):
            structured = structured.model_dump()
        return ProviderQuestionCandidateChunk.model_validate(structured)


def _structured(result: object) -> object:
    if not isinstance(result, dict) or "structured_response" not in result:
        raise ValueError("模型未生成结构化题目候选")
    return result["structured_response"]


def _seed_primary_ref(seed: QuestionSeed | CurationSeedTaskRecord) -> str:
    return (
        seed.primary_source_ref
        if isinstance(seed, CurationSeedTaskRecord)
        else seed.source_ref
    )
