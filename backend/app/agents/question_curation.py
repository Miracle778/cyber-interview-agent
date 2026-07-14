from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.agents.context import AgentContext
from app.agents.factory import AgentFactory, AgentSpec
from app.agents.question_curation_contracts import QuestionCandidateBatch


class AgentRunnable(Protocol):
    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        context: AgentContext | None = None,
    ) -> dict[str, Any]: ...


_PROMPT = (
    "把给定来源整理为可复习的中文面试题候选。纠正明显错误，保留来源引用，"
    "标注 topic、难度、关键点、必要追问和简短修正说明。"
    "来源中每个清晰可辨的独立题目都必须分别生成一个候选；不得任意合并、"
    "抽样或只挑代表题。若来源明确列出 N 道题，必须返回 N 个 candidates。"
    "不得自动发布。"
)


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
                    system_prompt=_PROMPT,
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
        candidate_index: dict[str, int] = {}
        known_questions = list(similar_questions)
        for source_unit in units:
            body = ["来源：", *source_unit]
            if known_questions:
                body.extend(("现有相似题：", *known_questions))
            if rewrite_feedback:
                body.extend(("重写要求：", rewrite_feedback))
            result = await self.runnable.ainvoke(
                {"messages": [HumanMessage(content="\n".join(body))]},
                _role_config(config, context, "question_generation"),
                context=context,
            )
            if "structured_response" not in result:
                raise ValueError("模型未生成结构化题目候选")
            batch = QuestionCandidateBatch.model_validate(
                result["structured_response"]
            )
            for candidate in batch.candidates:
                key = candidate.question_text.strip().casefold()
                existing_index = candidate_index.get(key)
                if existing_index is not None:
                    existing = candidates[existing_index]
                    candidates[existing_index] = existing.model_copy(
                        update={
                            "source_refs": list(
                                dict.fromkeys(
                                    [
                                        *existing.source_refs,
                                        *candidate.source_refs,
                                    ]
                                )
                            )
                        }
                    )
                    continue
                candidate_index[key] = len(candidates)
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


def _role_config(
    config: dict[str, Any], context: AgentContext, role: str
) -> dict[str, Any]:
    isolated = {
        key: value for key, value in config.items() if key != "configurable"
    }
    isolated["configurable"] = {
        "thread_id": f"{context.session_id}:{role}"
    }
    return isolated
