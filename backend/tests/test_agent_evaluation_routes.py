from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_agent_evaluation_service
from app.api.routes_agent_evaluations import router
from app.evaluation.repository import AgentEvaluationRepository
from app.infrastructure.runtime_database import connect_runtime_database


class RouteEvaluationService:
    def __init__(self, root: Path, *, advanced: bool = False) -> None:
        self.connection = connect_runtime_database(root)
        self.repository = AgentEvaluationRepository(
            self.connection, "workspace-1"
        )
        self._advanced = advanced

    @property
    def advanced_diagnostics_enabled(self) -> bool:
        return self._advanced

    async def evaluate(
        self,
        execution_id: str,
        *,
        trigger: str = "manual",
        idempotency_key: str | None = None,
        **_kwargs,
    ):
        existing = self.repository.list_runs_for_execution(execution_id)
        if existing:
            return existing[0]
        run = self.repository.create_run(
            eval_run_id=f"eval-{execution_id}",
            execution_id=execution_id,
            eval_pack_id="review.v1",
            eval_pack_version=1,
            trigger=trigger,
            frozen_input_hash="a" * 64,
            snapshot_json='{"events":[{"content":"private","available":true}]}',
            idempotency_key=idempotency_key or f"{trigger}-{execution_id}",
            judge_provider_model_id="model-1",
        )
        self.repository.store_dimension_results(
            run.id,
            (
                {
                    "dimension_id": "correctness",
                    "source": "judge",
                    "status": "scored",
                    "score": 80,
                    "confidence": 0.8,
                    "summary": "证据支持",
                    "cited_event_hashes_json": '["event-hash"]',
                    "cited_artifact_hashes_json": '["artifact-hash"]',
                    "risks_json": "[]",
                },
            ),
        )
        return self.repository.complete_run(
            run.id,
            deterministic_result_json='{"status":"passed"}',
            judge_result_json=(
                '{"confidence":0.8,"summary":"稳定","risks":[],'
                '"humanReviewRequired":false}'
            ),
            status="completed",
            judge_trace_run_id=run.id,
        )

    async def start_manual_evaluation(
        self,
        execution_id: str,
        *,
        idempotency_key: str,
        **kwargs,
    ):
        await self.evaluate(
            execution_id,
            idempotency_key=idempotency_key,
            **kwargs,
        )
        return SimpleNamespace(id=f"judge-{idempotency_key}")


@pytest.fixture
def api(tmp_path):
    service = RouteEvaluationService(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_evaluation_service] = lambda: service
    try:
        yield app, service
    finally:
        service.connection.close()


@pytest.mark.asyncio
async def test_manual_run_is_idempotent_and_raw_fields_are_hidden(api) -> None:
    app, _service = api
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/agent-evaluations/runs",
            params={"workspaceId": "workspace-1"},
            headers={"Idempotency-Key": "manual-request-1"},
            json={"executionId": "execution-1"},
        )
        replay = await client.post(
            "/api/agent-evaluations/runs",
            params={"workspaceId": "workspace-1"},
            headers={"Idempotency-Key": "manual-request-1"},
            json={"executionId": "execution-1"},
        )
    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json() == {
        "judgeExecutionId": "judge-manual-request-1",
        "sourceExecutionId": "execution-1",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        runs = await client.get(
            "/api/agent-evaluations/runs",
            params={"workspaceId": "workspace-1", "executionId": "execution-1"},
        )
    run = runs.json()["items"][0]
    assert run["rawSnapshot"] is None
    assert run["rawJudgeResult"] is None
    assert run["judgeTraceRunId"] is None
    assert run["dimensions"][0]["score"] == 80


@pytest.mark.asyncio
async def test_feedback_history_case_redaction_and_comparison_guard(api) -> None:
    app, service = api
    await service.evaluate("execution-1", idempotency_key="request-1")
    await service.evaluate("execution-2", idempotency_key="request-2")
    second = service.repository.list_runs_for_execution("execution-2")[0]
    service.repository.connection.execute(
        "UPDATE agent_eval_dimension_results SET dimension_id = 'other' "
        "WHERE eval_run_id = ?",
        (second.id,),
    )
    service.repository.connection.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        feedback = await client.post(
            "/api/agent-evaluations/runs/eval-execution-1/feedback",
            params={"workspaceId": "workspace-1"},
            json={"verdict": "accurate", "reason": "证据一致"},
        )
        history = await client.get(
            "/api/agent-evaluations/runs/eval-execution-1/feedback",
            params={"workspaceId": "workspace-1"},
        )
        unconfirmed = await client.post(
            "/api/agent-evaluations/regression-cases",
            params={"workspaceId": "workspace-1"},
            json={"evalRunId": "eval-execution-1", "confirmed": False},
        )
        case = await client.post(
            "/api/agent-evaluations/regression-cases",
            params={"workspaceId": "workspace-1"},
            json={"evalRunId": "eval-execution-1", "confirmed": True},
        )
        comparison = await client.get(
            "/api/agent-evaluations/comparisons",
            params=[
                ("workspaceId", "workspace-1"),
                ("runId", "eval-execution-1"),
                ("runId", "eval-execution-2"),
            ],
        )
    assert feedback.status_code == 201
    assert [item["version"] for item in history.json()] == [1]
    assert unconfirmed.status_code == 409
    assert case.json()["containsPrivateBodies"] is False
    stored = service.repository.list_regression_cases()[0]
    assert "private" not in stored.snapshot_json
    assert comparison.status_code == 409
