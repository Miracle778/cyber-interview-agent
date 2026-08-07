from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from app.evaluation.contracts import (
    JudgeDimensionResult,
    JudgeDimensionResultV2,
    JudgeResult,
    JudgeResultV2,
)
from app.evaluation.outcomes import (
    BusinessOutcomePayload,
    OutcomeCounters,
    OutcomeIdentity,
    OutcomeInput,
    freeze_business_outcome,
)
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
from app.application.execution_service import AgentExecutionService
from app.application.session_service import (
    AgentSessionService,
    ProductEventStream,
    ProductRepository,
)
from app.agents.definition_registry import require_agent_definition
from app.agents.definition_snapshot import build_agent_definition_snapshot


class FakeObservability:
    def __init__(self, *, graph_id: str = "review.single", status: str = "completed"):
        self.row = {
            "id": "execution-1",
            "graph_id": graph_id,
            "status": status,
            "title": "复习单题",
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


class FakeV2Judge:
    async def evaluate_v2(self, *, view, pack, context):
        return JudgeResultV2(
            dimensions=[
                JudgeDimensionResultV2(
                    dimension_id=dimension.dimension_id,
                    applicability=dimension.applicability,
                    rating=(
                        "meets"
                        if dimension.applicability == "applicable"
                        else None
                    ),
                    severity=(
                        "none"
                        if dimension.applicability == "applicable"
                        else None
                    ),
                    confidence=(
                        0.8
                        if dimension.applicability == "applicable"
                        else None
                    ),
                    cited_event_hashes=[],
                    cited_artifact_hashes=[],
                    evidence_gaps=(
                        []
                        if dimension.applicability == "applicable"
                        else [dimension.applicability_reason]
                    ),
                    summary=dimension.applicability_reason,
                    risks=[],
                )
                for dimension in view.dimensions
            ],
            summary="业务结果可用",
            risks=[],
            human_review_required=False,
        )


class FakeOutcomeAdapter:
    def build(self, execution_id):
        return freeze_business_outcome(
            BusinessOutcomePayload(
                task_type="question_curation",
                identity=OutcomeIdentity(
                    workspace_id="workspace-1",
                    session_id="session-1",
                    execution_id=execution_id,
                    graph_id="question.curate",
                    domain_refs={"batchId": "batch-1"},
                ),
                input=OutcomeInput(
                    source_refs=("source-1",),
                    input_hash="d" * 64,
                    requested_scope={"batchId": "batch-1"},
                ),
                execution_status="completed",
                terminal_state="review_pending",
                items=(),
                units=(),
                unit_counters={
                    "candidates": OutcomeCounters(
                        total=0, completed=0, failed=0, skipped=0, pending=0
                    )
                },
            )
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


def test_enabled_evaluation_captures_supported_execution_before_graph(tmp_path) -> None:
    connection, _observability, service = _service(
        tmp_path,
        settings=SimpleNamespace(
            enabled=True,
            capture_regression_inputs=True,
            automatic_daily_cap=20,
            judge_provider_model_id=None,
        ),
    )
    product = ProductRepository(connection)
    session = product.create_session(
        workspace_id="workspace-1",
        kind="review.discussion",
        title="Discussion",
    )
    execution = product.create_execution(
        session.id,
        input={"message": "explain"},
        model_bindings={"answer_evaluation": "model-1"},
    )
    try:
        service.capture_pre_execution_snapshot(execution)
        snapshot = service.pre_execution_snapshot(execution.id)

        assert snapshot is not None
        assert snapshot["mode"] == "restorable"
        assert snapshot["capturePoint"] == "before_graph_execution"
        assert snapshot["sourceExecutionId"] == execution.id
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_manual_judge_is_idempotent_and_does_not_change_business_status(
    tmp_path,
) -> None:
    connection, observability, service = _service(tmp_path)
    try:
        first = await service.evaluate(
            "execution-1", idempotency_key="manual-request-1", eval_pack_id="review.v1"
        )
        replay = await service.evaluate(
            "execution-1", idempotency_key="manual-request-1", eval_pack_id="review.v1"
        )
        assert first.id == replay.id
        assert first.status == "completed"
        assert observability.row["status"] == "completed"
        assert len(service.repository.list_dimension_results(first.id)) > 0
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_manual_judge_runs_as_visible_product_execution(tmp_path) -> None:
    connection, _observability, service = _service(tmp_path)
    product = ProductRepository(connection)
    events = ProductEventStream(product, workspace_root=tmp_path)
    sessions = AgentSessionService(product, events)

    async def unused_command(*_args, **_kwargs):
        return None

    executions = AgentExecutionService(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        repository=product,
        events=events,
        graph_factory=lambda *_args, **_kwargs: None,
        model_bindings=lambda: {"answer_evaluation": "model-1"},
        create_action=unused_command,
        create_draft=unused_command,
        mark_draft_review_pending=unused_command,
    )
    service.bind_execution_runtime(sessions=sessions, executions=executions)

    try:
        started = await service.start_manual_evaluation(
            "execution-1",
            idempotency_key="visible-quality-run",
            eval_pack_id="review.v1",
        )
        completed = await executions.wait(started.id)
        evaluation = service.repository.list_runs()[0]
        session = sessions.get(completed.session_id)
        replay = await service.start_manual_evaluation(
            "execution-1",
            idempotency_key="visible-quality-run",
            eval_pack_id="review.v1",
        )

        assert completed.status == "completed"
        assert evaluation.id == completed.id
        assert evaluation.status == "completed"
        assert session.kind == "quality.evaluate"
        assert session.visibility == "system"
        assert session.title == "质量检查：复习单题"
        assert replay.id == completed.id
        assert replay.status == "completed"
    finally:
        await events.close()
        connection.close()


@pytest.mark.asyncio
async def test_evaluation_uses_frozen_pack_instead_of_current_registry(
    tmp_path,
) -> None:
    connection, observability, service = _service(tmp_path)
    current = build_agent_definition_snapshot(
        definition=require_agent_definition("review.single"),
        graph_version=1,
        model_bindings={"answer_evaluation": "model-1"},
    )
    frozen = replace(
        current,
        agent_definition_version="historical-definition",
        eval_pack_id="review.v1",
        eval_pack_version=1,
    )
    observability.row["agent_definition_snapshot_json"] = frozen.to_json()
    try:
        result = await service.evaluate("execution-1")

        assert result.status == "completed"
        assert result.eval_pack_id == "review.v1"
        assert result.eval_pack_version == 1
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_evaluation_rejects_pack_override_that_differs_from_snapshot(
    tmp_path,
) -> None:
    connection, observability, service = _service(tmp_path)
    frozen = build_agent_definition_snapshot(
        definition=require_agent_definition("review.single"),
        graph_version=1,
        model_bindings={"answer_evaluation": "model-1"},
    )
    observability.row["agent_definition_snapshot_json"] = frozen.to_json()
    try:
        with pytest.raises(
            EvaluationNotSupportedError,
            match="冻结的评估标准",
        ):
            await service.evaluate("execution-1", eval_pack_id="review.v1")
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
        result = await service.evaluate("execution-1", eval_pack_id="review.v1")
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
            await service.evaluate("execution-1", eval_pack_id="review.v1")
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
            "execution-1", trigger="automatic", idempotency_key="automatic-1",
            eval_pack_id="review.v1",
        )
        assert completed.status == "completed"
        with pytest.raises(AutomaticEvaluationSkipped, match="daily_cap"):
            await service.evaluate(
                "execution-1",
                trigger="automatic",
                idempotency_key="automatic-2",
                eval_pack_id="review.v1",
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


@pytest.mark.asyncio
async def test_v2_evaluation_uses_business_outcome_and_minimal_judge_view(
    tmp_path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    observability = FakeObservability(graph_id="question.curate")
    service = AgentEvaluationService(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        repository=AgentEvaluationRepository(connection, "workspace-1"),
        observability=observability,
        model_bindings=lambda: {"answer_evaluation": "model-1"},
        settings=lambda: SimpleNamespace(
            enabled=True,
            automatic_daily_cap=20,
            judge_provider_model_id=None,
        ),
        judge_factory=lambda _model_id: FakeV2Judge(),
        outcome_adapter_factory=lambda _task_type: FakeOutcomeAdapter(),
    )
    try:
        result = await service.evaluate("execution-1")
        dimensions = service.repository.list_dimension_results(result.id)
        snapshot = result.snapshot_json

        assert result.status == "completed"
        assert result.eval_pack_id == "question-curation.v2"
        assert result.evaluation_contract_version == 2
        assert result.business_outcome_hash is not None
        assert '"businessOutcome"' in snapshot
        assert '"evaluationView"' in snapshot
        assert "traceEvents" not in snapshot
        assert '"mode":"minimal_evaluation_view"' in result.judge_data_scope_json
        assert any(item.rating == "meets" for item in dimensions)
        assert any(item.applicability == "not_applicable" for item in dimensions)
    finally:
        connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "graph_id",
    (
        "review.round",
        "review.single",
        "review.discussion",
        "profile.ingest",
        "profile.assess",
        "profile.manage",
        "job.analysis",
        "project.deep_dive",
    ),
)
async def test_primary_v2_packs_run_through_the_shared_service(
    tmp_path,
    graph_id,
) -> None:
    connection = connect_runtime_database(tmp_path)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('session-1', 'workspace-1', ?, 1, 'Test')",
        (graph_id,),
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('execution-1', 'session-1', 'completed', '{}')"
    )
    connection.commit()
    service = AgentEvaluationService(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        repository=AgentEvaluationRepository(connection, "workspace-1"),
        observability=FakeObservability(graph_id=graph_id),
        model_bindings=lambda: {"answer_evaluation": "model-1"},
        settings=lambda: SimpleNamespace(
            enabled=True,
            automatic_daily_cap=20,
            judge_provider_model_id=None,
        ),
        judge_factory=lambda _model_id: FakeV2Judge(),
    )
    try:
        result = await service.evaluate("execution-1")
        assert result.status == "completed"
        assert result.evaluation_contract_version == 2
        assert result.task_type != "legacy"
        assert result.business_outcome_hash is not None
    finally:
        connection.close()
