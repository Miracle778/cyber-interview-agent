from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

from langchain_core.messages import HumanMessage

from app.agents.agent_invocation import isolated_thread_config
from app.agents.context import AgentContext
from app.evaluation.contracts import EvalPack, JudgeResult
from app.evaluation.snapshot import FrozenEvaluationSnapshot


class JudgeInvoker(Protocol):
    async def evaluate(
        self,
        *,
        snapshot: FrozenEvaluationSnapshot,
        pack: EvalPack,
        context: AgentContext,
    ) -> JudgeResult: ...


class StructuredJudgeAgent:
    """Strict ToolStrategy Judge with no tools and no business dependencies."""

    def __init__(self, runnable) -> None:
        self._runnable = runnable

    async def evaluate(
        self,
        *,
        snapshot: FrozenEvaluationSnapshot,
        pack: EvalPack,
        context: AgentContext,
    ) -> JudgeResult:
        request = {
            "evalPack": {
                "id": pack.id,
                "version": pack.version,
                "dimensions": [asdict(item) for item in pack.dimensions],
                "instructions": pack.judge.instructions,
            },
            "frozenSnapshot": asdict(snapshot),
            "snapshotHash": snapshot.frozen_input_hash,
        }
        result = await self._runnable.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        content=json.dumps(
                            request,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                ]
            },
            isolated_thread_config({}, context, "quality_judge"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("Judge 未返回结构化结果")
        judged = JudgeResult.model_validate(result["structured_response"])
        expected = {dimension.id for dimension in pack.dimensions}
        actual = {dimension.dimension_id for dimension in judged.dimensions}
        if actual != expected or len(judged.dimensions) != len(expected):
            raise ValueError("Judge 维度与 Eval Pack 不兼容")
        return judged
