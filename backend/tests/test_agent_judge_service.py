from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.evaluation.contracts import JudgeDimensionResult, JudgeResult
from app.evaluation.registry import get_eval_pack
from app.evaluation.repository import AgentEvaluationRepository
from app.evaluation.sampling import decide_automatic_evaluation
from app.evaluation.service import (
    AgentEvaluationService,
    AutomaticEvaluationSkipped,
    EvaluationNotSupportedError,
)
from app.evaluation.snapshot import (
    FrozenArtifactReference,
    FrozenEvaluationSnapshot,
    FrozenTraceEvent,
)
from app.infrastructure.runtime_database import connect_runtime_database


class FakeObservability:
    def __init__(self, *, graph_id: str = "review.single", status: str = "completed"):
        self.row = {
            "id": "execution-1",
            "graph_id": graph_id,
            "status": status,
        }

    def _run(self, execution_id: str):
        assert execution_id == "execution-1"
        return dict(self.row)

    def build_evaluation_snapshot(self, execution_id: str, pack):
        return FrozenEvaluationSnapshot(
            snapshot_version=1,
            workspace_id="workspace-1",
            execution={**self.row, "id": execution_id},
            eval_pack_id=pack.id,
            eval_pack_version=pack.version,
            events=(
                FrozenTraceEvent(
                    event_id="event-1",
                    operation_id="operation-1",
                    event_type="model.response",
                    observed_at=None,
                    payload_sha256="a" * 64,
                    sequence=1,
                    available=True,
                    content='{"ok":true}',
                ),
            ),
            artifacts=(
                FrozenArtifactReference(source="snapshot", sha256="b" * 64),
            ),
            versions={"graph": "1", "trace": "3", "snapshot": "1"},
            model_bindings={"answer_evaluation": "model-1"},
            tool_versions={},
            captured_at="2026-07-30T00:00:00+00:00",
        )


class FakeJudge:
    def __init__(self, *, fail: bool = False, cancel: bool = False):
        self.fail = fail
        self.cancel = cancel

    async def evaluate(self, *, snapshot, pack, context):
        if self.cancel:
            raise asyncio.CancelledError()
        if self.fail:
            raise RuntimeError("provider unavailable")
        return JudgeResult(
            dimensions=[
                JudgeDimensionResult(
                    dimension_id=dimension.id,
                    score=80,
                    cited_event_hashes=["a" * 64],
                    cited_artifact_hashes=["b" * 64],
                    confidence=0.8,
                    summary="证据支持",
                    risks=[],
                )
                for dimension in pack.dimensions
            ],
            cited_event_hashes=["a" * 64],
            cited_artifact_hashes=["b" * 64],
            confidence=0.8,
            summary="整体稳定",
            risks=[],
            human_review_required=False,
        )


def _service(tmp_path, *, status="completed", judge=None, settings=None):
    connection = connect_runtime_database(tmp_path)
    observability = FakeObservability(status=status)
    service = AgentEvaluationService(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        repository=AgentEvaluationRepository(connection, "workspace-1"),
        observability=observability,
        model_bindings=lambda: {"answer_evaluation": "model-1"},
        settings=lambda: settings
        or SimpleNamespace(
            enabled=True,
            automatic_daily_cap=20,
            judge_provider_model_id=None,
        ),
        judge_factory=lambda _model_id: judge or FakeJudge(),
    )
    return connection, observability, service


@pytest.mark.asyncio
async def test_manual_judge_is_idempotent_and_does_not_change_business_status(
    tmp_path,
) -> None:
    connection, observability, service = _service(tmp_path)
    try:
        first = await service.evaluate(
            "execution-1", idempotency_key="manual-request-1"
        )
        replay = await service.evaluate(
            "execution-1", idempotency_key="manual-request-1"
        )
        assert first.id == replay.id
        assert first.status == "completed"
        assert observability.row["status"] == "completed"
        assert len(service.repository.list_dimension_results(first.id)) > 0
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_provider_failure_keeps_deterministic_results_and_business_run(
    tmp_path,
) -> None:
    connection, observability, service = _service(
        tmp_path, judge=FakeJudge(fail=True)
    )
    try:
        result = await service.evaluate("execution-1")
        assert result.status == "failed"
        assert result.error_code == "judge_provider_failed"
        assert result.deterministic_result_json is not None
        assert observability.row["status"] == "completed"
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_cancelled_judge_records_cancel_without_business_write(tmp_path) -> None:
    connection, observability, service = _service(
        tmp_path, judge=FakeJudge(cancel=True)
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await service.evaluate("execution-1")
        assert service.repository.list_runs()[0].status == "cancelled"
        assert observability.row["status"] == "completed"
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_automatic_risk_runs_respect_daily_cap(tmp_path) -> None:
    connection, _observability, service = _service(tmp_path, status="failed")
    service._settings = lambda: SimpleNamespace(
        enabled=True,
        automatic_daily_cap=1,
        judge_provider_model_id=None,
    )
    try:
        completed = await service.evaluate(
            "execution-1", trigger="automatic", idempotency_key="automatic-1"
        )
        assert completed.status == "completed"
        with pytest.raises(AutomaticEvaluationSkipped, match="daily_cap"):
            await service.evaluate(
                "execution-1",
                trigger="automatic",
                idempotency_key="automatic-2",
            )
    finally:
        connection.close()


def test_success_sampling_is_stable_and_recursive_agent_is_rejected(tmp_path) -> None:
    pack = get_eval_pack("review.v1")
    first = decide_automatic_evaluation(
        execution_id="stable-run",
        status="completed",
        policy=pack.trigger_policy,
    )
    second = decide_automatic_evaluation(
        execution_id="stable-run",
        status="completed",
        policy=pack.trigger_policy,
    )
    assert first == second

    connection, _observability, service = _service(tmp_path)
    service.observability = FakeObservability(graph_id="evaluation.judge")
    try:
        with pytest.raises(EvaluationNotSupportedError):
            asyncio.run(service.evaluate("execution-1"))
    finally:
        connection.close()
