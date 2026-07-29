from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.context import AgentContext
from app.evaluation.contracts import JudgeResult
from app.evaluation.judge_agent import JudgeInvoker
from app.evaluation.registry import get_eval_pack
from app.evaluation.repository import AgentEvaluationRepository, EvaluationRunRecord
from app.evaluation.runtime import EvaluationRuntime
from app.evaluation.sampling import decide_automatic_evaluation
from app.observability.registry import AGENT_OBSERVABILITY_REGISTRY


class EvaluationNotSupportedError(ValueError):
    pass


class AutomaticEvaluationSkipped(RuntimeError):
    pass


class AgentEvaluationService:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: AgentEvaluationRepository,
        observability,
        model_bindings: Callable[[], Mapping[str, str]],
        settings: Callable[[], object],
        judge_factory: Callable[[str], JudgeInvoker],
        publish_event: Callable[[str, dict[str, object]], Awaitable[None] | None]
        | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.repository = repository
        self.observability = observability
        self._model_bindings = model_bindings
        self._settings = settings
        self._judge_factory = judge_factory
        self._publish_event = publish_event
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def evaluate(
        self,
        execution_id: str,
        *,
        trigger: str = "manual",
        idempotency_key: str | None = None,
        degraded: bool = False,
        rejected: bool = False,
        heavily_edited: bool = False,
    ) -> EvaluationRunRecord:
        execution = self.observability._run(execution_id)
        registration = AGENT_OBSERVABILITY_REGISTRY.get(execution["graph_id"])
        if registration is None or registration.eval_pack_id is None:
            raise EvaluationNotSupportedError("该 Agent 暂不支持质量评估")
        if execution["graph_id"] == "evaluation.judge":
            raise EvaluationNotSupportedError("Judge 运行不能递归评估")
        pack = get_eval_pack(registration.eval_pack_id)
        configured = self._settings()
        if trigger == "automatic":
            decision = decide_automatic_evaluation(
                execution_id=execution_id,
                status=execution["status"],
                policy=pack.trigger_policy,
                degraded=degraded,
                rejected=rejected,
                heavily_edited=heavily_edited,
            )
            if not bool(getattr(configured, "enabled", False)) or not decision.selected:
                raise AutomaticEvaluationSkipped(decision.reason)
            cap = min(
                pack.trigger_policy.daily_cap,
                int(getattr(configured, "automatic_daily_cap", 20)),
            )
            if not self.repository.reserve_daily_slot(
                self._now().date().isoformat(), cap=cap
            ):
                raise AutomaticEvaluationSkipped("daily_cap")
        snapshot = self.observability.build_evaluation_snapshot(execution_id, pack)
        provider_model_id = getattr(configured, "judge_provider_model_id", None)
        if not provider_model_id:
            provider_model_id = self._model_bindings().get("answer_evaluation")
        if not provider_model_id:
            raise EvaluationNotSupportedError("未配置 Judge 模型")
        run_id = str(uuid4())
        key = idempotency_key or (
            f"{trigger}:{execution_id}:{pack.id}:{pack.version}:"
            f"{snapshot.frozen_input_hash}"
        )
        record = self.repository.create_run(
            eval_run_id=run_id,
            execution_id=execution_id,
            eval_pack_id=pack.id,
            eval_pack_version=pack.version,
            trigger=trigger,
            frozen_input_hash=snapshot.frozen_input_hash,
            snapshot_json=json.dumps(
                asdict(snapshot),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            idempotency_key=key,
            judge_provider_model_id=provider_model_id,
        )
        if record.status != "pending":
            return record
        record = self.repository.mark_running(record.id)
        deterministic = EvaluationRuntime(snapshot=snapshot, pack=pack).run_deterministic()
        deterministic_json = json.dumps(
            asdict(deterministic),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        await self._emit(
            "evaluation.started",
            {"evalRunId": record.id, "executionId": execution_id, "trigger": trigger},
        )
        context = AgentContext(
            workspace_id=self.workspace_id,
            workspace_root=self.workspace_root,
            session_id="evaluation",
            run_id=record.id,
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
            progress_scope=("evaluation", record.id),
            agent_role="answer_evaluation",
        )
        try:
            judged = await self._judge_factory(provider_model_id).evaluate(
                snapshot=snapshot,
                pack=pack,
                context=context,
            )
        except asyncio.CancelledError:
            completed = self.repository.complete_run(
                record.id,
                deterministic_result_json=deterministic_json,
                judge_result_json=None,
                status="cancelled",
                error_code="judge_cancelled",
                judge_trace_run_id=record.id,
            )
            await self._emit(
                "evaluation.cancelled",
                {"evalRunId": record.id, "executionId": execution_id},
            )
            raise
        except Exception:
            completed = self.repository.complete_run(
                record.id,
                deterministic_result_json=deterministic_json,
                judge_result_json=None,
                status="failed",
                error_code="judge_provider_failed",
                judge_trace_run_id=record.id,
            )
            self._store_deterministic(record.id, deterministic)
            await self._emit(
                "evaluation.failed",
                {
                    "evalRunId": record.id,
                    "executionId": execution_id,
                    "errorCode": "judge_provider_failed",
                },
            )
            return completed
        self._store_deterministic(record.id, deterministic)
        self._store_judge(record.id, judged)
        completed = self.repository.complete_run(
            record.id,
            deterministic_result_json=deterministic_json,
            judge_result_json=judged.model_dump_json(by_alias=True),
            status="completed",
            judge_trace_run_id=record.id,
        )
        await self._emit(
            "evaluation.completed",
            {"evalRunId": record.id, "executionId": execution_id},
        )
        return completed

    def _store_deterministic(self, eval_run_id: str, result) -> None:
        self.repository.store_dimension_results(
            eval_run_id,
            tuple(
                {
                    "dimension_id": item.rule_id,
                    "source": "deterministic",
                    "status": item.status,
                    "summary": "; ".join(item.evidence_gaps) or "规则通过",
                    "cited_event_hashes_json": json.dumps(item.cited_event_hashes),
                }
                for item in result.rules
            ),
        )

    def _store_judge(self, eval_run_id: str, result: JudgeResult) -> None:
        self.repository.store_dimension_results(
            eval_run_id,
            tuple(
                {
                    "dimension_id": item.dimension_id,
                    "source": "judge",
                    "status": "scored",
                    "score": item.score,
                    "confidence": item.confidence,
                    "summary": item.summary,
                    "cited_event_hashes_json": json.dumps(item.cited_event_hashes),
                    "cited_artifact_hashes_json": json.dumps(item.cited_artifact_hashes),
                    "risks_json": json.dumps(item.risks, ensure_ascii=False),
                }
                for item in result.dimensions
            ),
        )

    async def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self._publish_event is None:
            return
        result = self._publish_event(event_type, payload)
        if asyncio.iscoroutine(result):
            await result
