from __future__ import annotations

import json
import asyncio

from app.evaluation.case_snapshot import create_restorable_case_snapshot
from app.evaluation.contracts import PairwiseDimensionResult, PairwiseJudgeResult
from app.evaluation.outcomes import (
    BusinessOutcomePayload,
    OutcomeCounters,
    OutcomeIdentity,
    OutcomeInput,
    OutcomeItem,
    OutcomeProvenance,
    OutcomeUserDecision,
    freeze_business_outcome,
)
from app.evaluation.regression import (
    IsolatedAgentRegressionRunner,
    RegressionExecutionResult,
    RegressionImplementationCatalog,
)
from app.evaluation.repository import AgentEvaluationRepository
from app.infrastructure.runtime_database import connect_runtime_database


class _Implementation:
    def __init__(self, implementation_id: str, answer: str, roots: list) -> None:
        self.implementation_id = implementation_id
        self.answer = answer
        self.roots = roots

    async def execute(self, *, case, sandbox_root):
        self.roots.append(sandbox_root)
        connection = connect_runtime_database(sandbox_root)
        execution_id = f"{self.implementation_id}-execution"
        session_id = f"{self.implementation_id}-session"
        connection.execute(
            "INSERT INTO agent_sessions "
            "(id, workspace_id, graph_id, graph_version, title) "
            "VALUES (?, 'workspace-1', 'question.curate', 1, 'Regression')",
            (session_id,),
        )
        connection.execute(
            "INSERT INTO agent_runs (id, session_id, status, input_json) "
            "VALUES (?, ?, 'completed', '{}')",
            (execution_id, session_id),
        )
        connection.commit()
        connection.close()
        outcome = freeze_business_outcome(BusinessOutcomePayload(
            task_type="question_curation",
            identity=OutcomeIdentity(
                workspace_id="workspace-1",
                session_id=session_id,
                execution_id=execution_id,
                graph_id="question.curate",
                domain_refs={"batchId": f"{self.implementation_id}-batch"},
            ),
            input=OutcomeInput(
                source_refs=("source-1",),
                input_hash="a" * 64,
                requested_scope={},
            ),
            execution_status="completed",
            terminal_state="review_pending",
            items=(OutcomeItem(
                item_id=f"{self.implementation_id}-candidate",
                item_type="question_candidate",
                status="review_pending",
                content={
                    "question_text": "Redis 为什么快？",
                    "reference_answer": self.answer,
                    "source_answer": self.answer,
                    "supplemental_answer": None,
                    "answer_basis": "source",
                },
                provenance=(OutcomeProvenance(
                    field_path="content.sourceAnswer",
                    support_type="direct",
                    source_refs=("source-1",),
                ),),
                user_decision=OutcomeUserDecision(status="pending"),
            ),),
            units=(),
            unit_counters={
                "items": OutcomeCounters(
                    total=1, completed=0, failed=0, skipped=0, pending=1
                )
            },
        ))
        return RegressionExecutionResult(execution_id, outcome)


class _Judge:
    async def compare_v2(self, *, view_a, view_b, pack, context):
        assert view_a.task_type == view_b.task_type == "question_curation"
        return PairwiseJudgeResult(
            winner="a",
            confidence=.8,
            dimensions=[
                PairwiseDimensionResult(
                    dimension_id=item.id,
                    winner="a",
                    confidence=.8,
                    summary="A 更稳定",
                )
                for item in pack.dimensions
            ],
            summary="盲化比较完成",
            risks=[],
            human_review_required=False,
        )


def _case(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    connection = connect_runtime_database(workspace)
    connection.execute(
        "INSERT INTO agent_sessions "
        "(id, workspace_id, graph_id, graph_version, title) "
        "VALUES ('source-session', 'workspace-1', 'question.curate', 1, 'Source')"
    )
    connection.execute(
        "INSERT INTO agent_runs (id, session_id, status, input_json) "
        "VALUES ('source-execution', 'source-session', 'completed', '{}')"
    )
    connection.commit()
    snapshot = create_restorable_case_snapshot(
        workspace_root=workspace,
        case_id="case-1",
        connection=connection,
    )
    repository = AgentEvaluationRepository(connection, "workspace-1")
    case = repository.create_regression_case(
        case_id="case-1",
        source_eval_run_id=None,
        execution_id="source-execution",
        eval_pack_id="question-curation.v2",
        eval_pack_version=2,
        snapshot_hash="b" * 64,
        snapshot_json="{}",
        expected_invariants_json="[]",
        contains_private_bodies=True,
        redaction_summary="restorable",
        case_contract_version=2,
        task_type="question_curation",
        sanitized_input_json="{}",
        required_domain_snapshot_json=json.dumps(snapshot),
        privacy_manifest_json='{"domainSnapshotMode":"restorable"}',
        baseline_versions_json='{"graph":"question.curate@1"}',
    )
    return workspace, connection, repository, case


def test_runner_uses_two_restored_sandboxes_and_blind_pairwise_judge(tmp_path) -> None:
    workspace, connection, repository, case = _case(tmp_path)
    roots = []
    runner = IsolatedAgentRegressionRunner(
        workspace_id="workspace-1",
        workspace_root=workspace,
        repository=repository,
        implementations=RegressionImplementationCatalog((
            _Implementation("baseline@1", "内存访问", roots),
            _Implementation("candidate@2", "内存与事件循环", roots),
        )),
        judge=_Judge(),
    )
    try:
        result = asyncio.run(runner.run(
            case_id=case.id,
            baseline_implementation_id="baseline@1",
            candidate_implementation_id="candidate@2",
            idempotency_key="run-case-1",
        ))
        assert result.status == "completed"
        assert result.baseline_outcome_hash != result.candidate_outcome_hash
        assert json.loads(result.pairwise_result_json)["winner"] in {
            "baseline", "candidate"
        }
        assert json.loads(result.isolation_manifest_json)["productionWrites"] is False
        assert len(roots) == 2 and roots[0] != roots[1]
        assert all(not root.exists() for root in roots)
    finally:
        connection.close()


def test_runner_classifies_missing_implementation_as_infrastructure_failure(tmp_path) -> None:
    workspace, connection, repository, case = _case(tmp_path)
    runner = IsolatedAgentRegressionRunner(
        workspace_id="workspace-1",
        workspace_root=workspace,
        repository=repository,
        implementations=RegressionImplementationCatalog(),
        judge=_Judge(),
    )
    try:
        result = asyncio.run(runner.run(
            case_id=case.id,
            baseline_implementation_id="missing@1",
            candidate_implementation_id="missing@2",
            idempotency_key="run-case-missing",
        ))
        assert result.status == "failed"
        assert result.error_code == "implementation_not_available"
        assert json.loads(result.infrastructure_failures_json)[0]["side"] == "runner"
    finally:
        connection.close()
