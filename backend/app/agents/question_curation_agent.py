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
    ProviderQuestionSeedChunk,
    QuestionCandidateChunk,
    QuestionRevisionOutput,
    QuestionSeed,
    QuestionSeedChunk,
    normalize_provider_seed_chunk,
)
from app.review.curation_sections import SourceSection


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
                    response_format=QuestionCandidateChunk,
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
                    response_format=QuestionRevisionOutput,
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
        seeds: Sequence[QuestionSeed],
        *,
        sections: Sequence[SourceSection],
        known_questions: Sequence[str],
        context: AgentContext,
        config: dict[str, Any],
        unit_index: int,
    ) -> QuestionCandidateChunk:
        allowed = {section.ref: section.source_id for section in sections}
        seed_refs = {seed.source_ref: tuple(seed.source_refs) for seed in seeds}
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
        chunk = QuestionCandidateChunk.model_validate(_structured(result))
        candidates = []
        seen_refs: set[str] = set()
        for candidate in chunk.candidates:
            primary = candidate.source_refs[0]
            if (
                primary not in seed_refs
                or any(ref not in allowed for ref in candidate.source_refs)
                or tuple(candidate.source_refs) != seed_refs[primary]
            ):
                raise ValueError("question enrichment returned an unknown source ref")
            if len({allowed[ref] for ref in candidate.source_refs}) != 1:
                raise ValueError("question enrichment returned cross-source refs")
            source_ref = primary
            if source_ref in seen_refs:
                continue
            seen_refs.add(source_ref)
            candidates.append(candidate)
        return chunk.model_copy(update={"candidates": candidates})

    async def revise(
        self,
        *,
        source_excerpts: Sequence[str],
        rewrite_feedback: str,
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionRevisionOutput:
        result = await self.revision.ainvoke(
            {"messages": [HumanMessage(content=render_question_revision_input(
                source_excerpts, rewrite_feedback=rewrite_feedback
            ))]},
            isolated_thread_config(
                config, context, f"question_revision:{context.run_id}"
            ),
            context=context,
        )
        output = QuestionRevisionOutput.model_validate(_structured(result))
        source_ids = {
            excerpt.split("\n", 1)[0].split(":", 1)[0]
            for excerpt in source_excerpts
        }
        if any(
            not any(ref == source_id or ref.startswith(f"{source_id}#") for source_id in source_ids)
            for ref in output.candidate.source_refs
        ):
            raise ValueError("question revision returned an unknown source ref")
        return output


def _structured(result: object) -> object:
    if not isinstance(result, dict) or "structured_response" not in result:
        raise ValueError("模型未生成结构化题目候选")
    return result["structured_response"]
