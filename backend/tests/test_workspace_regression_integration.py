from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from langgraph.graph import END, START, StateGraph

from app.application.workspace_runtime import WorkspaceRuntime
from app.evaluation.contracts import (
    PairwiseDimensionResult,
    PairwiseJudgeResult,
)
from app.evaluation.outcome_adapters.domain import create_sqlite_outcome_adapter
from app.infrastructure.observability import NoopObservabilitySink


class FakePairwiseJudge:
    async def compare_v2(self, *, view_a, view_b, pack, context):
        assert view_a.task_type == view_b.task_type == pack.task_type
        assert context.allowed_tools == frozenset()
        return PairwiseJudgeResult(
            winner="tie",
            confidence=1,
            dimensions=[
                PairwiseDimensionResult(
                    dimension_id=item.id,
                    winner="tie",
                    confidence=1,
                    summary="相同输入得到等价结果",
                )
                for item in pack.dimensions
            ],
            summary="两个隔离运行结果等价",
            risks=[],
            human_review_required=False,
        )


class RegressionGraphFactory:
    trace_writer = None

    def create_evaluation_judge(self, **_kwargs):
        return FakePairwiseJudge()

    def __call__(self, kind: str, **dependencies):
        if kind not in {"review.discussion", "question.curate"}:
            raise ValueError(kind)
        graph = StateGraph(dict)

        async def answer(state):
            if kind == "question.curate":
                source_ref = state["source_refs"][0]
                return {
                    "generation_phase": "completed",
                    "candidates": [
                        {
                            "title": "Redis 性能原理",
                            "question_text": "Redis 为什么快？",
                            "reference_answer": "内存访问与高效事件模型。",
                            "topics": ["Redis"],
                            "difficulty": "medium",
                            "key_points": ["内存", "事件模型"],
                            "follow_ups": [],
                            "source_refs": [source_ref],
                            "correction_note": "",
                        }
                    ],
                }
            return {"response": f"解释：{state['message']}"}

        graph.add_node("answer", answer)
        graph.add_edge(START, "answer")
        graph.add_edge("answer", END)
        return graph.compile(checkpointer=dependencies["checkpointer"])


@pytest.mark.asyncio
async def test_registered_workspace_implementations_rerun_conversation_in_two_sandboxes(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    factory = RegressionGraphFactory()
    bindings = {"answer_evaluation": "judge-model", "agent_chat": "chat-model"}
    runtime = WorkspaceRuntime.create(
        workspace_id="workspace-1",
        root=workspace,
        model_bindings=lambda: bindings,
        graph_factory=factory,
        observability=NoopObservabilitySink(),
        validate_review_model=lambda _model, _effort: None,
        advanced_diagnostics_enabled=lambda: False,
        quality_evaluation_settings=lambda: SimpleNamespace(
            enabled=True,
            capture_regression_inputs=True,
            automatic_daily_cap=20,
            judge_provider_model_id="judge-model",
        ),
    )
    try:
        session = await runtime.sessions.create(
            workspace_id="workspace-1",
            kind="review.discussion",
            title="Conversation regression",
        )
        execution = await runtime.executions.start(
            session,
            input={"message": "为什么 Redis 很快？"},
        )
        completed = await runtime.executions.wait(execution.id)
        assert completed.status == "completed"
        assert runtime.agent_evaluation is not None
        snapshot = runtime.agent_evaluation.pre_execution_snapshot(execution.id)
        assert snapshot is not None
        outcome = create_sqlite_outcome_adapter(
            "review_discussion",
            runtime.connection,
            "workspace-1",
        ).build(execution.id)
        snapshot_json = json.dumps(snapshot, sort_keys=True)
        case = runtime.agent_evaluation.repository.create_regression_case(
            case_id="conversation-case",
            source_eval_run_id=None,
            execution_id=execution.id,
            eval_pack_id="review-discussion.v2",
            eval_pack_version=2,
            snapshot_hash=hashlib.sha256(snapshot_json.encode()).hexdigest(),
            snapshot_json=snapshot_json,
            expected_invariants_json="[]",
            contains_private_bodies=True,
            redaction_summary="本机隔离案例",
            case_contract_version=2,
            task_type="review_discussion",
            sanitized_input_json=json.dumps(execution.input, ensure_ascii=False),
            required_domain_snapshot_json=snapshot_json,
            privacy_manifest_json='{"containsPrivateBodies":true}',
            baseline_versions_json=json.dumps({"modelBindings": bindings}),
            source_business_outcome_json=json.dumps(
                outcome.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
            ),
        )

        result = await runtime.agent_evaluation.run_regression_case(
            case_id=case.id,
            baseline_implementation_id="source-model-config@current-code",
            candidate_implementation_id="current-runtime",
            idempotency_key="conversation-regression-1",
        )

        assert result.status == "completed", result.infrastructure_failures_json
        assert result.baseline_outcome_hash
        assert result.candidate_outcome_hash
        isolation = json.loads(result.isolation_manifest_json)
        assert isolation["productionWrites"] is False
        assert isolation["separateSandboxes"] is True
        assert isolation["baselineVersions"]["modelBindings"] == bindings
        assert isolation["candidateVersions"]["modelBindings"] == bindings
        assert runtime.repository.get_execution(execution.id).status == "completed"
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_registered_workspace_implementations_rerun_question_curation(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    factory = RegressionGraphFactory()
    bindings = {
        "answer_evaluation": "judge-model",
        "question_generation": "question-model",
    }
    runtime = WorkspaceRuntime.create(
        workspace_id="workspace-1",
        root=workspace,
        model_bindings=lambda: bindings,
        graph_factory=factory,
        observability=NoopObservabilitySink(),
        validate_review_model=lambda _model, _effort: None,
        advanced_diagnostics_enabled=lambda: False,
        quality_evaluation_settings=lambda: SimpleNamespace(
            enabled=True,
            capture_regression_inputs=True,
            automatic_daily_cap=20,
            judge_provider_model_id="judge-model",
        ),
    )
    try:
        session = await runtime.sessions.create(
            workspace_id="workspace-1",
            kind="question.curate",
            title="Question regression",
        )
        source_id = "source-1"
        runtime.review.repository.create_curation_session(
            workspace_id="workspace-1",
            session_id=session.id,
            source_refs=(source_id,),
        )
        batch = runtime.review.repository.create_batch(
            workspace_id="workspace-1",
            session_id=session.id,
            run_id=None,
            source_refs=(source_id,),
        )
        execution_input = {
            "batchId": batch.id,
            "batch_id": batch.id,
            "sourceRefs": [source_id],
            "source_refs": [source_id],
            "source_excerpts": ["source-1:notes.md\nRedis 为什么快？"],
            "similar_questions": [],
            "rewrite_feedback": None,
        }
        execution = await runtime.executions.prepare(
            session,
            input=execution_input,
            project_input_message=False,
        )
        runtime.review.repository.attach_batch_run(batch.id, execution.id)
        runtime.review.repository.record_curation_attempt(
            batch.id,
            execution.id,
            reason="initial",
        )
        runtime.review.repository.update_curation_progress(
            session.id,
            stage="generating",
            completed_units=0,
            total_units=1,
            active_batch_id=batch.id,
        )
        runtime.executions.run_prepared(execution, graph_input=execution_input)
        completed = await runtime.executions.wait(execution.id)
        assert completed.status == "completed"
        assert runtime.agent_evaluation is not None
        snapshot = runtime.agent_evaluation.pre_execution_snapshot(execution.id)
        assert snapshot is not None
        snapshot_json = json.dumps(snapshot, sort_keys=True)
        case = runtime.agent_evaluation.repository.create_regression_case(
            case_id="curation-case",
            source_eval_run_id=None,
            execution_id=execution.id,
            eval_pack_id="question-curation.v2",
            eval_pack_version=2,
            snapshot_hash=hashlib.sha256(snapshot_json.encode()).hexdigest(),
            snapshot_json=snapshot_json,
            expected_invariants_json="[]",
            contains_private_bodies=True,
            redaction_summary="本机隔离案例",
            case_contract_version=2,
            task_type="question_curation",
            sanitized_input_json=json.dumps(execution.input, ensure_ascii=False),
            required_domain_snapshot_json=snapshot_json,
            privacy_manifest_json='{"containsPrivateBodies":true}',
            baseline_versions_json=json.dumps({"modelBindings": bindings}),
        )

        result = await runtime.agent_evaluation.run_regression_case(
            case_id=case.id,
            baseline_implementation_id="source-model-config@current-code",
            candidate_implementation_id="current-runtime",
            idempotency_key="curation-regression-1",
        )

        assert result.status == "completed", result.infrastructure_failures_json
        assert result.baseline_outcome_hash == result.candidate_outcome_hash
        source_batch = runtime.review.repository.get_batch(batch.id)
        assert source_batch.status == "review_pending"
        assert len(runtime.review.repository.list_candidates("workspace-1")) == 1
    finally:
        await runtime.close()
