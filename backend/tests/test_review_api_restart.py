from pathlib import Path
from types import SimpleNamespace
import asyncio

import pytest

from app.application.workspace_runtime import AgentApplication
from app.knowledge.source_registry import KnowledgeSourceService
from app.review.curation_command_contracts import CurationCommandPlan
from app.review.models import MasteryProjection, QuestionSnapshot, ReviewRoundSettings
from tests.test_review_api_v2 import _graph_factory


class _BlockingClassifier:
    def __init__(self, entered: asyncio.Event) -> None:
        self.entered = entered

    async def classify(self, assembled, *, context):
        self.entered.set()
        await asyncio.Event().wait()


class _ResolvedClassifier:
    async def classify(self, assembled, *, context):
        return CurationCommandPlan(clarification="恢复后完成")


class _Responder:
    async def astream(self, rendered_context, *, context):
        yield "恢复后完成"


def _command_agents(classifier):
    return SimpleNamespace(
        classifier=classifier,
        summarizer=SimpleNamespace(),
        responder=_Responder(),
        context_limit_tokens=16_000,
        token_counter=len,
    )


@pytest.mark.asyncio
async def test_waiting_input_round_resumes_after_application_restart(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Restart round"
    )
    round_id = "round-restart"
    execution = await review.executions.prepare(
        session, input={"roundId": round_id}
    )
    review.repository.create_round(
        workspace_id="w1",
        session_id=session.id,
        execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(),
            difficulties=("medium",),
            mode="random-mixed",
            question_count=1,
            allow_follow_up=False,
            seed=1,
            answer_model_id="model-1",
            reasoning_effort="none",
        ),
        question_snapshots=(
            QuestionSnapshot(
                question_id="q1",
                document_id="doc-q1",
                content_hash="a" * 64,
                title="MVCC",
                question_text="Explain MVCC",
                reference_answer="Multi-version concurrency control",
                topics=("database",),
                difficulty="medium",
                key_points=("versions",),
                follow_ups=(),
            ),
        ),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id=round_id,
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": round_id}
    )
    await review.executions.wait(execution.id)
    before = await review.round_resource(round_id)
    assert before["execution_status"] == "waiting_for_input"
    request = before["current_input"]
    await first.close()

    second = build()
    try:
        assert await second.recover() == ()
        restored = await second.locate_review_round(round_id).round_resource(
            round_id
        )
        assert restored["current_input"]["id"] == request["id"]
        await second.locate_review_round(round_id).submit_answer(
            round_id,
            request_id=request["id"],
            version=request["version"],
            idempotency_key="restart-answer-01",
            value="multiple versions",
        )
        await second.wait_execution(restored["execution_id"])
        resumed = await second.locate_review_round(round_id).round_resource(
            round_id
        )
        assert resumed["attempts"][0]["answer"] == "multiple versions"
        assert resumed["execution_status"] == "waiting_for_approval"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_restart_reconciles_abandoned_generating_batch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="question.curate", title="Interrupted batch"
    )
    execution = await review.executions.prepare(session, input={})
    batch = review.repository.create_batch(
        workspace_id="w1",
        session_id=session.id,
        run_id=execution.id,
        source_refs=("source-1",),
    )
    await first.close()

    second = build()
    try:
        await second.recover()
        restored = second.review("w1").repository.get_batch(batch.id)
        assert restored.status == "failed"
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_interrupted_curation_command_requires_explicit_retry(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace-command-retry"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    source = await KnowledgeSourceService(
        workspace, workspace_id="w1"
    ).create(
        original_filename="retry.md",
        content_type="text/markdown",
        content=b"# Retry\n\nExplain durable retries.",
    )
    first = build()
    created = await first.review("w1").create_curation_session(
        source_refs=(source.id,)
    )
    await first.wait_execution(created["execution_id"])
    session_id = created["id"]
    detail = await first.locate_review_session(session_id).curation_resource(
        session_id
    )
    entered = asyncio.Event()
    review = first.locate_review_session(session_id)
    review.curation_command_agents = _command_agents(
        _BlockingClassifier(entered)
    )
    accepted = await review.submit_curation_command(
        session_id,
        text="把这一批按之前方式处理一下",
        summary_version=detail["summary_version"],
        idempotency_key="restart-command-1",
        provider_model_id=None,
        reasoning_effort="none",
    )
    await asyncio.wait_for(entered.wait(), timeout=0.2)
    await first.close()

    second = build()
    try:
        restored_review = second.locate_curation_command(
            accepted["command_id"]
        )
        interrupted = restored_review.repository.get_curation_command_receipt(
            accepted["command_id"]
        )
        assert interrupted.lifecycle_status == "interrupted"
        assert interrupted.retry_count == 0
        assert second.replay_events(session_id, after_id=None)[-1].type != (
            "execution.completed"
        )

        restored_review.curation_command_agents = _command_agents(
            _ResolvedClassifier()
        )
        retried = await restored_review.retry_curation_command(
            accepted["command_id"]
        )
        assert retried["execution_id"] != accepted["execution_id"]
        await second.wait_execution(retried["execution_id"])
        completed = restored_review.repository.get_curation_command_receipt(
            accepted["command_id"]
        )
        messages = (await second.session_detail(session_id))["messages"]

        assert completed.lifecycle_status == "completed"
        assert completed.retry_count == 1
        assert sum(
            message["content"] == "把这一批按之前方式处理一下"
            for message in messages
        ) == 1
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_restart_resumes_answer_accepted_before_graph_spawn(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace-accepted"
    workspace.mkdir()

    def build() -> AgentApplication:
        return AgentApplication(
            workspace_resolver=lambda _workspace_id: workspace,
            workspace_ids=lambda: ("w1",),
            model_bindings=lambda _workspace_id: {},
            graph_factory=_graph_factory,
        )

    first = build()
    review = first.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Accepted answer"
    )
    execution = await review.executions.prepare(
        session, input={"roundId": "round-accepted"}
    )
    review.repository.create_round(
        workspace_id="w1",
        session_id=session.id,
        execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=1, allow_follow_up=False, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(QuestionSnapshot(
            question_id="q-accepted", document_id="doc-accepted",
            content_hash="c" * 64, title="Accepted",
            question_text="Explain durable acceptance",
            reference_answer="Commit before model work",
            topics=("runtime",), difficulty="medium",
            key_points=("transaction",), follow_ups=(),
        ),),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-accepted",
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": "round-accepted"}
    )
    await review.executions.wait(execution.id)
    request = (await review.round_resource("round-accepted"))["current_input"]
    receipt = review.repository.accept_review_answer(
        request_id=request["id"], expected_version=request["version"],
        idempotency_key="accepted-before-spawn", value="transaction first",
    )
    assert receipt.status == "evaluating"
    await first.close()

    second = build()
    try:
        await second.recover()
        await second.wait_execution(execution.id)
        restored = await second.locate_review_round(
            "round-accepted"
        ).round_resource("round-accepted")
        assert restored["attempts"][0]["status"] == "completed"
        assert restored["attempts"][0]["answer"] == "transaction first"
        assert sum(
            message["content"] == "transaction first"
            for message in restored["messages"]
        ) == 1
    finally:
        await second.close()
