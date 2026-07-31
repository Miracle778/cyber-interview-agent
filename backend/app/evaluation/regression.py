from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.agents.context import AgentContext
from app.evaluation.business_rules import evaluate_business_rules
from app.evaluation.case_snapshot import restore_case_snapshot
from app.evaluation.outcomes import BusinessOutcomeProjection
from app.evaluation.registry import get_eval_pack
from app.evaluation.repository import (
    AgentEvaluationRepository,
    RegressionCaseRecord,
    RegressionRunRecord,
)
from app.evaluation.views import build_task_evaluation_view
from app.infrastructure.runtime_database import connect_runtime_database


@dataclass(frozen=True, slots=True)
class RegressionExecutionResult:
    execution_id: str
    outcome: BusinessOutcomeProjection


class RegressionImplementation(Protocol):
    implementation_id: str

    async def execute(
        self,
        *,
        case: RegressionCaseRecord,
        sandbox_root: Path,
    ) -> RegressionExecutionResult: ...


class RegressionImplementationUnavailable(LookupError):
    pass


class RegressionImplementationCatalog:
    def __init__(
        self,
        implementations: tuple[RegressionImplementation, ...] = (),
    ) -> None:
        self._items = {item.implementation_id: item for item in implementations}

    def get(self, implementation_id: str) -> RegressionImplementation:
        try:
            return self._items[implementation_id]
        except KeyError as error:
            raise RegressionImplementationUnavailable(implementation_id) from error

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._items))


class IsolatedAgentRegressionRunner:
    def __init__(
        self,
        *,
        workspace_id: str,
        workspace_root: Path,
        repository: AgentEvaluationRepository,
        implementations: RegressionImplementationCatalog,
        judge,
    ) -> None:
        self.workspace_id = workspace_id
        self.workspace_root = workspace_root
        self.repository = repository
        self.implementations = implementations
        self.judge = judge

    async def run(
        self,
        *,
        case_id: str,
        baseline_implementation_id: str,
        candidate_implementation_id: str,
        idempotency_key: str,
    ) -> RegressionRunRecord:
        case = self.repository.get_regression_case(case_id)
        if case is None:
            raise LookupError("regression case not found")
        run = self.repository.create_regression_run(
            run_id=str(uuid4()),
            case_id=case.id,
            case_version=case.version,
            baseline_implementation_id=baseline_implementation_id,
            candidate_implementation_id=candidate_implementation_id,
            idempotency_key=idempotency_key,
        )
        if run.status != "pending":
            return run
        run = self.repository.mark_regression_running(run.id)
        try:
            baseline = self.implementations.get(baseline_implementation_id)
            candidate = self.implementations.get(candidate_implementation_id)
        except RegressionImplementationUnavailable as error:
            return self.repository.complete_regression_run(
                run.id,
                status="failed",
                infrastructure_failures_json=json.dumps([
                    {
                        "side": "runner",
                        "code": "implementation_not_available",
                        "detail": str(error),
                    }
                ]),
                error_code="implementation_not_available",
            )

        snapshot = _object(case.required_domain_snapshot_json)
        sandbox_parent = self.workspace_root / ".agent-evaluation" / "sandboxes"
        sandbox_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"{run.id}-baseline-", dir=sandbox_parent
        ) as baseline_dir, tempfile.TemporaryDirectory(
            prefix=f"{run.id}-candidate-", dir=sandbox_parent
        ) as candidate_dir:
            baseline_root = Path(baseline_dir)
            candidate_root = Path(candidate_dir)
            try:
                restore_case_snapshot(
                    workspace_root=self.workspace_root,
                    snapshot=snapshot,
                    sandbox_root=baseline_root,
                )
                restore_case_snapshot(
                    workspace_root=self.workspace_root,
                    snapshot=snapshot,
                    sandbox_root=candidate_root,
                )
            except Exception as error:
                return self._infrastructure_failure(
                    run,
                    "runner",
                    "snapshot_restore_failed",
                    error,
                )
            try:
                baseline_result = await baseline.execute(
                    case=case, sandbox_root=baseline_root
                )
            except Exception as error:
                return self._infrastructure_failure(
                    run, "baseline", _infrastructure_code(error), error
                )
            try:
                candidate_result = await candidate.execute(
                    case=case, sandbox_root=candidate_root
                )
            except Exception as error:
                return self._infrastructure_failure(
                    run,
                    "candidate",
                    _infrastructure_code(error),
                    error,
                    baseline=baseline_result,
                )

            pack = get_eval_pack(case.eval_pack_id)
            baseline_connection = connect_runtime_database(baseline_root)
            candidate_connection = connect_runtime_database(candidate_root)
            try:
                baseline_rules = evaluate_business_rules(
                    baseline_result.outcome,
                    connection=baseline_connection,
                    workspace_id=self.workspace_id,
                )
                candidate_rules = evaluate_business_rules(
                    candidate_result.outcome,
                    connection=candidate_connection,
                    workspace_id=self.workspace_id,
                )
            finally:
                baseline_connection.close()
                candidate_connection.close()
            baseline_view = build_task_evaluation_view(
                baseline_result.outcome, pack
            )
            candidate_view = build_task_evaluation_view(
                candidate_result.outcome, pack
            )
            swap = int(hashlib.sha256(run.id.encode()).hexdigest(), 16) % 2 == 1
            view_a, view_b = (
                (candidate_view, baseline_view)
                if swap
                else (baseline_view, candidate_view)
            )
            context = AgentContext(
                workspace_id=self.workspace_id,
                workspace_root=self.workspace_root,
                session_id="evaluation-regression",
                run_id=run.id,
                allowed_tools=frozenset(),
                allowed_scopes=frozenset(),
                progress_scope=("evaluation_regression", run.id),
                agent_role="answer_evaluation",
            )
            try:
                pairwise = await self.judge.compare_v2(
                    view_a=view_a,
                    view_b=view_b,
                    pack=pack,
                    context=context,
                )
            except Exception as error:
                return self._infrastructure_failure(
                    run,
                    "judge",
                    "judge_provider_failed",
                    error,
                    baseline=baseline_result,
                    candidate=candidate_result,
                    deterministic={
                        "baseline": asdict(baseline_rules),
                        "candidate": asdict(candidate_rules),
                    },
                )
            winner = pairwise.winner
            if winner in {"a", "b"}:
                if (winner == "a") == swap:
                    winner = "candidate"
                else:
                    winner = "baseline"
            pairwise_payload = pairwise.model_dump(mode="json", by_alias=True)
            pairwise_payload["winner"] = winner
            return self.repository.complete_regression_run(
                run.id,
                status="completed",
                baseline_execution_id=baseline_result.execution_id,
                candidate_execution_id=candidate_result.execution_id,
                baseline_outcome_hash=baseline_result.outcome.outcome_hash,
                candidate_outcome_hash=candidate_result.outcome.outcome_hash,
                deterministic_comparison_json=json.dumps(
                    {
                        "baseline": asdict(baseline_rules),
                        "candidate": asdict(candidate_rules),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                pairwise_result_json=json.dumps(
                    pairwise_payload, ensure_ascii=False, sort_keys=True
                ),
                isolation_manifest_json=json.dumps(
                    {
                        "productionWrites": False,
                        "separateSandboxes": True,
                        "snapshotHash": case.snapshot_hash,
                        "blindOrderHash": hashlib.sha256(
                            f"{run.id}:{int(swap)}".encode()
                        ).hexdigest(),
                    },
                    sort_keys=True,
                ),
            )

    def _infrastructure_failure(
        self,
        run: RegressionRunRecord,
        side: str,
        code: str,
        error: Exception,
        *,
        baseline: RegressionExecutionResult | None = None,
        candidate: RegressionExecutionResult | None = None,
        deterministic: Mapping[str, object] | None = None,
    ) -> RegressionRunRecord:
        return self.repository.complete_regression_run(
            run.id,
            status="failed",
            baseline_execution_id=None if baseline is None else baseline.execution_id,
            candidate_execution_id=None if candidate is None else candidate.execution_id,
            baseline_outcome_hash=None if baseline is None else baseline.outcome.outcome_hash,
            candidate_outcome_hash=None if candidate is None else candidate.outcome.outcome_hash,
            deterministic_comparison_json=(
                None
                if deterministic is None
                else json.dumps(deterministic, ensure_ascii=False, sort_keys=True)
            ),
            infrastructure_failures_json=json.dumps([
                {"side": side, "code": code, "detail": str(error)[:500]}
            ], ensure_ascii=False),
            isolation_manifest_json=json.dumps({
                "productionWrites": False,
                "separateSandboxes": True,
            }),
            error_code=code,
        )


def _object(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("regression case snapshot must be an object")
    return parsed


def _infrastructure_code(error: Exception) -> str:
    text = str(error).casefold()
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return "network_timeout"
    if "rate limit" in text or "429" in text or "quota" in text:
        return "provider_limit"
    if isinstance(error, sqlite3.OperationalError) and "locked" in text:
        return "database_locked"
    return "agent_execution_failed"
