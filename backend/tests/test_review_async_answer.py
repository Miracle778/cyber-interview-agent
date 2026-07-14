from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agents.review_round_contracts import (
    ReviewSessionReportOutput,
    RoundAnswerEvaluation,
)
from app.api.dependencies import get_agent_application
from app.api.routes_review import router as review_router
from app.application.workspace_runtime import AgentApplication
from app.graphs.review_round import create_review_round_graph
from app.review.models import MasteryProjection, QuestionSnapshot, ReviewRoundSettings


class BlockingRoundAgents:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def evaluate(self, **_values):
        self.started.set()
        await self.release.wait()
        return RoundAnswerEvaluation(
            score="good",
            missing_key_points=[],
            evidence="回答覆盖关键点",
            follow_up_required=False,
            follow_up_prompt=None,
            mastery_suggestion="stable",
        )

    async def report(self, **_values):
        return ReviewSessionReportOutput(
            title="复习报告",
            markdown="# 复习报告",
            mastery_explanation="掌握稳定",
        )


class FailOnceRoundAgents(BlockingRoundAgents):
    def __init__(self) -> None:
        super().__init__()
        self.release.set()
        self.calls = 0

    async def evaluate(self, **values):
        self.calls += 1
        if self.calls == 1:
            error = RuntimeError("private provider response")
            error.code = "evaluation_provider_failed"  # type: ignore[attr-defined]
            raise error
        return await super().evaluate(**values)


def _question(identifier: str) -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id=identifier,
        document_id=f"doc-{identifier}",
        content_hash=("a" if identifier == "q1" else "b") * 64,
        title=identifier,
        question_text=f"Explain {identifier}",
        reference_answer=f"Reference {identifier}",
        topics=("database",),
        difficulty="medium",
        key_points=("point",),
        follow_ups=(),
    )


@pytest.mark.asyncio
async def test_answer_returns_202_before_evaluation_and_projects_safe_events(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = BlockingRoundAgents()

    def graph_factory(kind, **dependencies):
        if kind != "review.round":
            raise AssertionError(kind)
        return create_review_round_graph(
            agents,
            repository=dependencies["review_repository"],
            create_report_drafts=dependencies["create_report_drafts"],
            request_publication_action=dependencies["request_publication_action"],
            checkpointer=dependencies["checkpointer"],
        )

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=graph_factory,
    )
    review = application.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Async round"
    )
    execution = await review.executions.prepare(
        session, input={"roundId": "round-async"}
    )
    review.repository.create_round(
        workspace_id="w1",
        session_id=session.id,
        execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=2, allow_follow_up=False, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(_question("q1"), _question("q2")),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-async",
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": "round-async"}
    )
    await review.executions.wait(execution.id)
    current = await review.round_resource("round-async")
    request = current["current_input"]

    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(
                client.post(
                    "/api/review/rounds/round-async/answers",
                    json={
                        "inputRequestId": request["id"],
                        "version": request["version"],
                        "idempotencyKey": "async-answer-key-1",
                        "value": "my private answer",
                    },
                ),
                timeout=0.25,
            )
            assert response.status_code == 202, response.text
            receipt = response.json()
            assert receipt == {
                "receiptId": receipt["receiptId"],
                "roundId": "round-async",
                "attemptId": receipt["attemptId"],
                "inputRequestId": request["id"],
                "status": "evaluating",
                "acceptedAt": receipt["acceptedAt"],
                "version": 1,
            }
            await asyncio.wait_for(agents.started.wait(), timeout=0.25)
            immediate = (await client.get(
                "/api/review/rounds/round-async"
            )).json()
            assert immediate["attempts"][0]["status"] == "evaluating"
            assert immediate["attempts"][0]["answer"] == "my private answer"

            duplicate = await client.post(
                "/api/review/rounds/round-async/answers",
                json={
                    "inputRequestId": request["id"],
                    "version": request["version"],
                    "idempotencyKey": "async-answer-key-1",
                    "value": "my private answer",
                },
            )
            assert duplicate.status_code == 202
            assert duplicate.json()["receiptId"] == receipt["receiptId"]

            agents.release.set()
            await application.wait_execution(execution.id)
            completed = (await client.get(
                "/api/review/rounds/round-async"
            )).json()
            assert completed["attempts"][0]["status"] == "completed"
            assert completed["attempts"][0]["evaluation"]["score"] == "good"

        events = application.replay_events(session.id, after_id=None)
        stage_events = [event for event in events if event.type.startswith("review.")]
        stage_types = [event.type for event in stage_events]
        expected_order = [
            "review.answer.accepted", "review.evaluation.started",
            "review.evaluation.completed",
        ]
        assert all(event_type in stage_types for event_type in expected_order)
        assert [stage_types.index(event_type) for event_type in expected_order] == sorted(
            stage_types.index(event_type) for event_type in expected_order
        )
        assert "my private answer" not in str([event.payload for event in events])
        assert "Reference q1" not in str([event.payload for event in events])
    finally:
        agents.release.set()
        await application.close()


@pytest.mark.asyncio
async def test_failed_evaluation_preserves_answer_and_retry_resumes_checkpoint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents = FailOnceRoundAgents()

    def graph_factory(kind, **dependencies):
        assert kind == "review.round"
        return create_review_round_graph(
            agents,
            repository=dependencies["review_repository"],
            create_report_drafts=dependencies["create_report_drafts"],
            request_publication_action=dependencies["request_publication_action"],
            checkpointer=dependencies["checkpointer"],
        )

    application = AgentApplication(
        workspace_resolver=lambda _workspace_id: workspace,
        workspace_ids=lambda: ("w1",),
        model_bindings=lambda _workspace_id: {},
        graph_factory=graph_factory,
    )
    review = application.review("w1")
    session = await review.sessions.create(
        workspace_id="w1", kind="review.round", title="Retry round"
    )
    execution = await review.executions.prepare(
        session, input={"roundId": "round-retry"}
    )
    review.repository.create_round(
        workspace_id="w1", session_id=session.id, execution_id=execution.id,
        settings=ReviewRoundSettings(
            topics=(), difficulties=("medium",), mode="random-mixed",
            question_count=2, allow_follow_up=False, seed=1,
            answer_model_id="model-1", reasoning_effort="none",
        ),
        question_snapshots=(_question("q1"), _question("q2")),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-retry",
    )
    review.executions.run_prepared(
        execution, graph_input={"round_id": "round-retry"}
    )
    await review.executions.wait(execution.id)
    request = (await review.round_resource("round-retry"))["current_input"]
    api = FastAPI()
    api.include_router(review_router)
    api.dependency_overrides[get_agent_application] = lambda: application
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            accepted = await client.post(
                "/api/review/rounds/round-retry/answers",
                json={
                    "inputRequestId": request["id"],
                    "version": request["version"],
                    "idempotencyKey": "failed-answer-key-1",
                    "value": "answer survives failure",
                },
            )
            assert accepted.status_code == 202
            await application.wait_execution(execution.id)
            failed = (await client.get(
                "/api/review/rounds/round-retry"
            )).json()
            assert failed["attempts"][0]["status"] == "evaluation_failed"
            assert failed["attempts"][0]["answer"] == "answer survives failure"
            assert failed["currentIndex"] == 0
            review.repository.reconcile_abandoned_work()
            assert review.repository.get_round("round-retry").status != "failed"

            retried = await client.post(
                "/api/review/rounds/round-retry/retry-evaluation",
                json={"idempotencyKey": "retry-evaluation-key-1"},
            )
            assert retried.status_code == 202, retried.text
            assert retried.json()["attemptId"] == failed["attempts"][0]["id"]
            await application.wait_execution(execution.id)
            restored = (await client.get(
                "/api/review/rounds/round-retry"
            )).json()
            assert restored["attempts"][0]["status"] == "completed"
            assert restored["attempts"][0]["answer"] == "answer survives failure"
            assert restored["currentIndex"] == 1

            duplicate_retry = await client.post(
                "/api/review/rounds/round-retry/retry-evaluation",
                json={"idempotencyKey": "retry-evaluation-key-1"},
            )
            assert duplicate_retry.status_code == 202
            assert duplicate_retry.json()["receiptId"] == retried.json()["receiptId"]

        payloads = str([
            event.payload
            for event in application.replay_events(session.id, after_id=None)
        ])
        assert "answer survives failure" not in payloads
        assert "private provider response" not in payloads
        assert "private provider response" not in caplog.text
    finally:
        await application.close()
