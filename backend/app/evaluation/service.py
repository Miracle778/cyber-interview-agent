from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.context import AgentContext
from app.evaluation.contracts import JudgeResult, JudgeResultV2
from app.evaluation.judge_agent import JudgeInvoker
from app.evaluation.outcome_adapters.question_curation import (
    QuestionCurationOutcomeAdapter,
)
from app.evaluation.registry import get_eval_pack
from app.evaluation.repository import AgentEvaluationRepository, EvaluationRunRecord
from app.evaluation.runtime import EvaluationRuntime
from app.evaluation.sampling import decide_automatic_evaluation
from app.evaluation.views import (
    EvaluationView,
    build_question_curation_evaluation_view,
)
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
        advanced_diagnostics_enabled: Callable[[], bool] | None = None,
        outcome_adapter_factory: Callable[[str], object] | None = None,
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
        self._advanced_diagnostics_enabled = (
            advanced_diagnostics_enabled or (lambda: False)
        )
        self._outcome_adapter_factory = (
            outcome_adapter_factory or self._default_outcome_adapter
        )

    @property
    def advanced_diagnostics_enabled(self) -> bool:
        return bool(self._advanced_diagnostics_enabled())

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
        if pack.evaluation_contract_version == 2:
            return await self._evaluate_v2(
                execution_id=execution_id,
                pack=pack,
                provider_model_id=provider_model_id,
                trigger=trigger,
                idempotency_key=idempotency_key,
            )
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
            evaluation_contract_version=pack.evaluation_contract_version,
            task_type=pack.task_type,
            run_kind="historical_review",
            business_outcome_hash=None,
            judge_data_scope_json=json.dumps(
                {
                    "mode": "legacy_full_snapshot",
                    "providerModelId": provider_model_id,
                    "categories": [
                        "executionMetadata",
                        "traceEvents",
                        "traceEventBodies",
                        "artifactMetadata",
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
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

    async def _evaluate_v2(
        self,
        *,
        execution_id: str,
        pack,
        provider_model_id: str,
        trigger: str,
        idempotency_key: str | None,
    ) -> EvaluationRunRecord:
        outcome = self._outcome_adapter_factory(pack.task_type).build(execution_id)
        view = self._build_evaluation_view(outcome)
        view_json = view.model_dump_json()
        frozen_input_hash = hashlib.sha256(view_json.encode("utf-8")).hexdigest()
        snapshot_json = json.dumps(
            {
                "businessOutcome": outcome.model_dump(mode="json"),
                "evaluationView": view.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        scope_json = json.dumps(
            {
                "mode": "minimal_evaluation_view",
                "providerModelId": provider_model_id,
                "categories": list(view.data_categories),
                "excludes": [
                    "traceEventBodies",
                    "localPaths",
                    "secrets",
                    "unrelatedPrivateFields",
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        key = idempotency_key or (
            f"{trigger}:{execution_id}:{pack.id}:{pack.version}:"
            f"{outcome.outcome_hash}:{frozen_input_hash}"
        )
        record = self.repository.create_run(
            eval_run_id=str(uuid4()),
            execution_id=execution_id,
            eval_pack_id=pack.id,
            eval_pack_version=pack.version,
            trigger=trigger,
            frozen_input_hash=frozen_input_hash,
            snapshot_json=snapshot_json,
            idempotency_key=key,
            judge_provider_model_id=provider_model_id,
            evaluation_contract_version=2,
            task_type=pack.task_type,
            run_kind="historical_review",
            business_outcome_hash=outcome.outcome_hash,
            judge_data_scope_json=scope_json,
        )
        if record.status != "pending":
            return record
        record = self.repository.mark_running(record.id)
        deterministic = {
            "status": "passed",
            "rules": [],
            "evidenceGaps": list(outcome.evidence_gaps),
            "note": "业务不变量规则将在 Phase 2 逐项校准；当前不阻断业务。",
        }
        deterministic_json = json.dumps(
            deterministic,
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
            judged = await self._judge_factory(provider_model_id).evaluate_v2(
                view=view,
                pack=pack,
                context=context,
            )
            self._validate_v2_judge_result(view, judged)
        except asyncio.CancelledError:
            self.repository.complete_run(
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
            await self._emit(
                "evaluation.failed",
                {
                    "evalRunId": record.id,
                    "executionId": execution_id,
                    "errorCode": "judge_provider_failed",
                },
            )
            return completed
        self._store_judge_v2(record.id, judged)
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

    def _default_outcome_adapter(self, task_type: str):
        if task_type == "question_curation":
            return QuestionCurationOutcomeAdapter(
                self.repository.connection,
                self.workspace_id,
            )
        raise EvaluationNotSupportedError(
            f"任务类型尚未提供业务结果适配器: {task_type}"
        )

    @staticmethod
    def _build_evaluation_view(outcome) -> EvaluationView:
        if outcome.task_type == "question_curation":
            return build_question_curation_evaluation_view(outcome)
        raise EvaluationNotSupportedError(
            f"任务类型尚未提供最小 Judge View: {outcome.task_type}"
        )

    @staticmethod
    def _validate_v2_judge_result(
        view: EvaluationView,
        result: JudgeResultV2,
    ) -> None:
        expected = {
            item.dimension_id: item.applicability for item in view.dimensions
        }
        actual = {
            item.dimension_id: item.applicability for item in result.dimensions
        }
        if actual != expected or len(result.dimensions) != len(expected):
            raise ValueError("Judge 维度或适用性与 Evaluation View 不兼容")

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

    def _store_judge_v2(
        self,
        eval_run_id: str,
        result: JudgeResultV2,
    ) -> None:
        self.repository.store_dimension_results(
            eval_run_id,
            tuple(
                {
                    "dimension_id": item.dimension_id,
                    "source": "judge",
                    "status": "scored",
                    "applicability": item.applicability,
                    "rating": item.rating,
                    "severity": item.severity,
                    "confidence": item.confidence,
                    "summary": item.summary,
                    "cited_event_hashes_json": json.dumps(
                        item.cited_event_hashes
                    ),
                    "cited_artifact_hashes_json": json.dumps(
                        item.cited_artifact_hashes
                    ),
                    "risks_json": json.dumps(item.risks, ensure_ascii=False),
                    "evidence_gaps_json": json.dumps(
                        item.evidence_gaps, ensure_ascii=False
                    ),
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
