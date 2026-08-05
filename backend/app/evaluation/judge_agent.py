from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

from langchain_core.messages import HumanMessage

from app.agents.agent_invocation import isolated_thread_config
from app.agents.context import AgentContext
from app.evaluation.contracts import (
    EvalPack,
    JudgeResult,
    JudgeResultV2,
    PairwiseJudgeResult,
)
from app.evaluation.snapshot import FrozenEvaluationSnapshot
from app.evaluation.views import EvaluationView


class JudgeInvoker(Protocol):
    async def evaluate(
        self,
        *,
        snapshot: FrozenEvaluationSnapshot,
        pack: EvalPack,
        context: AgentContext,
    ) -> JudgeResult: ...

    async def evaluate_v2(
        self,
        *,
        view: EvaluationView,
        pack: EvalPack,
        context: AgentContext,
    ) -> JudgeResultV2: ...

    async def compare_v2(
        self,
        *,
        view_a: EvaluationView,
        view_b: EvaluationView,
        pack: EvalPack,
        context: AgentContext,
    ) -> PairwiseJudgeResult: ...


class StructuredJudgeAgent:
    """Strict ToolStrategy Judge with no tools and no business dependencies."""

    def __init__(self, runnable, v2_runnable=None, pairwise_runnable=None) -> None:
        self._runnable = runnable
        self._v2_runnable = v2_runnable
        self._pairwise_runnable = pairwise_runnable

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

    async def compare_v2(
        self,
        *,
        view_a: EvaluationView,
        view_b: EvaluationView,
        pack: EvalPack,
        context: AgentContext,
    ) -> PairwiseJudgeResult:
        if self._pairwise_runnable is None:
            raise ValueError("Judge 未配置盲化 A/B 结构化输出")
        request = {
            "evalPack": {
                "id": pack.id,
                "version": pack.version,
                "taskType": pack.task_type,
                "dimensions": [asdict(item) for item in pack.dimensions],
                "instructions": pack.judge.instructions,
            },
            "outcomeA": view_a.model_dump(mode="json"),
            "outcomeB": view_b.model_dump(mode="json"),
        }
        result = await self._pairwise_runnable.ainvoke(
            {
                "messages": [HumanMessage(content=json.dumps(
                    request,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ))]
            },
            isolated_thread_config({}, context, "quality_judge_pairwise_v2"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("Judge 未返回盲化 A/B 结构化结果")
        judged = PairwiseJudgeResult.model_validate(result["structured_response"])
        expected = {dimension.id for dimension in pack.dimensions}
        actual = {dimension.dimension_id for dimension in judged.dimensions}
        if actual != expected or len(judged.dimensions) != len(expected):
            raise ValueError("Pairwise Judge 维度与 v2 Eval Pack 不兼容")
        return judged

    async def evaluate_v2(
        self,
        *,
        view: EvaluationView,
        pack: EvalPack,
        context: AgentContext,
    ) -> JudgeResultV2:
        if self._v2_runnable is None:
            raise ValueError("Judge 未配置 v2 结构化输出")
        request = {
            "evalPack": {
                "id": pack.id,
                "version": pack.version,
                "taskType": pack.task_type,
                "dimensions": [asdict(item) for item in pack.dimensions],
                "instructions": pack.judge.instructions,
            },
            "evaluationView": view.model_dump(mode="json"),
            "businessOutcomeHash": view.business_outcome_hash,
        }
        result = await self._v2_runnable.ainvoke(
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
            isolated_thread_config({}, context, "quality_judge_v2"),
            context=context,
        )
        if "structured_response" not in result:
            raise ValueError("Judge 未返回 v2 结构化结果")
        judged = JudgeResultV2.model_validate(result["structured_response"])
        expected = {dimension.id for dimension in pack.dimensions}
        actual = {dimension.dimension_id for dimension in judged.dimensions}
        if actual != expected or len(judged.dimensions) != len(expected):
            raise ValueError("Judge 维度与 v2 Eval Pack 不兼容")
        return judged
