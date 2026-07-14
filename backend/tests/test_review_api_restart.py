from pathlib import Path

import pytest

from app.application.workspace_runtime import AgentApplication
from app.review.models import MasteryProjection, QuestionSnapshot, ReviewRoundSettings
from tests.test_review_api_v2 import _graph_factory


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
