from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.context import AgentContext
from app.agents.agent_factory import AgentFactory, AgentSpec
from app.agents.agent_invocation import isolated_thread_config
from app.agents.agent_protocols import AgentRunnable
from app.agents.prompts.question_curation_prompts import (
    QUESTION_CURATION_PROMPT,
    render_question_curation_input,
)
from app.agents.question_curation_contracts import QuestionCandidateBatch
from app.review.question_similarity import same_question


@dataclass(frozen=True, slots=True)
class QuestionCurationAgent:
    runnable: AgentRunnable

    @classmethod
    def create(
        cls,
        factory: AgentFactory,
        *,
        model_bindings: Mapping[str, str],
        middleware: tuple[AgentMiddleware, ...] = (),
        tools=(),
        checkpointer=None,
    ) -> "QuestionCurationAgent":
        return cls(
            factory.create(
                AgentSpec(
                    role="question_generation",
                    prompt=QUESTION_CURATION_PROMPT,
                    tools=tuple(tools),
                    middleware=middleware,
                    response_format=QuestionCandidateBatch,
                ),
                model_bindings=model_bindings,
                checkpointer=checkpointer,
            )
        )

    async def generate(
        self,
        *,
        source_excerpts: tuple[str, ...],
        similar_questions: tuple[str, ...],
        rewrite_feedback: str | None,
        context: AgentContext,
        config: dict[str, Any],
    ) -> QuestionCandidateBatch:
        units = _generation_units(source_excerpts)
        candidates = []
        known_questions = list(similar_questions)
        for source_unit in units:
            result = await self.runnable.ainvoke(
                {"messages": [HumanMessage(content=render_question_curation_input(
                    source_unit,
                    known_questions=tuple(known_questions),
                    rewrite_feedback=rewrite_feedback,
                ))]},
                isolated_thread_config(config, context, "question_generation"),
                context=context,
            )
            if "structured_response" not in result:
                raise ValueError("模型未生成结构化题目候选")
            batch = QuestionCandidateBatch.model_validate(
                result["structured_response"]
            )
            for candidate in batch.candidates:
                existing_index = next(
                    (
                        index
                        for index, existing in enumerate(candidates)
                        if same_question(
                            existing.question_text,
                            candidate.question_text,
                            left_topics=existing.topics,
                            right_topics=candidate.topics,
                        )
                    ),
                    None,
                )
                if existing_index is not None:
                    existing = candidates[existing_index]
                    candidates[existing_index] = existing.model_copy(
                        update={
                            "source_refs": list(dict.fromkeys([*existing.source_refs, *candidate.source_refs])),
                            "key_points": list(dict.fromkeys([*existing.key_points, *candidate.key_points])),
                            "follow_ups": list(dict.fromkeys([*existing.follow_ups, *candidate.follow_ups])),
                        }
                    )
                    continue
                candidates.append(candidate)
                known_questions.append(candidate.question_text)
                if len(candidates) == 50:
                    return QuestionCandidateBatch(candidates=candidates)
        return QuestionCandidateBatch(candidates=candidates)


_NUMBERED_ITEM = re.compile(r"^\s*\d{1,3}[.、)]\s+")
_MAX_NUMBERED_ITEMS_PER_CALL = 6


def _generation_units(
    source_excerpts: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    split_sources = [_split_numbered_source(source) for source in source_excerpts]
    if all(len(chunks) == 1 for chunks in split_sources):
        return (source_excerpts,)
    return tuple((chunk,) for chunks in split_sources for chunk in chunks)


def _split_numbered_source(source: str) -> tuple[str, ...]:
    lines = source.splitlines()
    starts = [
        index for index, line in enumerate(lines) if _NUMBERED_ITEM.match(line)
    ]
    if len(starts) <= _MAX_NUMBERED_ITEMS_PER_CALL:
        return (source,)
    prefix = lines[: starts[0]]
    items = [
        lines[start : starts[index + 1] if index + 1 < len(starts) else None]
        for index, start in enumerate(starts)
    ]
    return tuple(
        "\n".join(
            [*prefix, *[line for item in group for line in item]]
        ).strip()
        for offset in range(0, len(items), _MAX_NUMBERED_ITEMS_PER_CALL)
        for group in (items[offset : offset + _MAX_NUMBERED_ITEMS_PER_CALL],)
    )
