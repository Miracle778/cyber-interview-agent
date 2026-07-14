from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.types import Interrupt

from app.application.event_projector import AgentEventProjector
from app.application.execution_service import (
    AgentExecutionService,
    _classify_interrupt,
)
from app.application.session_service import ProductEventStream, ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.models import MasteryProjection, QuestionSnapshot, ReviewRoundSettings
from app.review.repository import ReviewRepository


def _question() -> QuestionSnapshot:
    return QuestionSnapshot(
        question_id="q1",
        document_id="d1",
        content_hash="a" * 64,
        title="MVCC",
        question_text="Explain MVCC",
        reference_answer="Read View",
        topics=("database",),
        difficulty="medium",
        key_points=("Read View",),
        follow_ups=(),
    )


def _settings() -> ReviewRoundSettings:
    return ReviewRoundSettings(
        topics=(),
        difficulties=("medium",),
        mode="random-mixed",
        question_count=1,
        allow_follow_up=False,
        seed=1,
        answer_model_id="m1",
        reasoning_effort="none",
    )


def test_input_interrupt_is_not_projected_as_hitl_approval() -> None:
    projector = AgentEventProjector()
    interrupt = Interrupt(
        value={
            "inputRequestId": "input-1",
            "kind": "answer",
            "version": 1,
            "ordinal": 1,
            "prompt": "must-not-leak",
        },
        id="interrupt-1",
    )

    events = projector.project(
        {"type": "values", "data": {}, "interrupts": (interrupt,)}
    )

    assert events[0].type == "review.input.required"
    assert events[0].payload == {
        "interrupt_id": "interrupt-1",
        "input_request_id": "input-1",
        "kind": "answer",
        "version": 1,
        "ordinal": 1,
    }
    assert _classify_interrupt(interrupt.value) == "input"
    assert _classify_interrupt({"actionId": "action-1"}) == "approval"
    with pytest.raises(ValueError, match="unsupported_interrupt"):
        _classify_interrupt({"other": "value"})


@pytest.mark.asyncio
async def test_duplicate_input_receipt_does_not_resume_graph_twice(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    product = ProductRepository(connection)
    events = ProductEventStream(product, workspace_root=tmp_path)
    session = product.create_session(
        workspace_id="w1", kind="review.round", title="Round", session_id="s1"
    )
    execution = product.create_execution(
        session.id, input={}, model_bindings={}, execution_id="r1"
    )
    reviews = ReviewRepository(connection)
    reviews.create_round(
        workspace_id="w1",
        session_id="s1",
        execution_id="r1",
        settings=_settings(),
        question_snapshots=(_question(),),
        mastery_before=MasteryProjection("w1", 0, (), ()),
        round_id="round-1",
    )
    request = reviews.create_input_request(
        round_id="round-1",
        ordinal=1,
        kind="answer",
        prompt="Explain MVCC",
        request_id="input-1",
    )
    product.transition_execution(
        execution.id, expected=("running",), target="waiting_for_input"
    )
    service = AgentExecutionService(
        workspace_id="w1",
        workspace_root=tmp_path,
        repository=product,
        events=events,
        graph_factory=lambda *_args, **_kwargs: None,
        model_bindings=lambda: {},
        create_action=lambda _command: None,
        create_draft=lambda _command: None,
        mark_draft_review_pending=lambda *_args, **_kwargs: None,
        review_repository=reviews,
    )
    spawned = []
    service._spawn = lambda execution_id, *, graph_input: spawned.append(  # type: ignore[method-assign]
        (execution_id, graph_input)
    )

    first = await service.resume_input(
        "r1", request_id=request.id, value="Read View", receipt_id="receipt-1"
    )
    duplicate = await service.resume_input(
        "r1", request_id=request.id, value="Read View", receipt_id="receipt-1"
    )

    assert first == duplicate
    assert product.get_execution("r1").status == "running"
    assert product.get_execution("r1").resume_count == 1
    assert len(spawned) == 1
    assert [event.type for event in product.list_events("s1", after_id=None)] == [
        "review.input.resolved",
        "execution.started",
    ]
    connection.close()
