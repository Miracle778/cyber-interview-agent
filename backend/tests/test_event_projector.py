from __future__ import annotations

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Interrupt

from app.application.event_projector import AgentEventProjector


def test_projects_visible_v2_transitions_with_monotonic_cursors():
    projector = AgentEventProjector()
    text = projector.project(
        {"type": "messages", "ns": (), "data": (AIMessageChunk(content="hello"), {})}
    )
    custom = projector.project(
        {
            "type": "custom",
            "ns": (),
            "data": {"type": "artifact.changed", "payload": {"draft_id": "d1"}},
        }
    )

    assert [(event.cursor, event.type) for event in (*text, *custom)] == [
        (1, "assistant.delta"),
        (2, "artifact.changed"),
    ]
    assert text[0].payload == {"text": "hello"}


def test_interrupt_is_projected_once_and_internal_lifecycle_is_ignored():
    projector = AgentEventProjector()
    interrupt = Interrupt(
        value={"action_requests": [{"name": "write_review_draft", "args": {"secret": "hidden"}}]},
        id="interrupt-1",
    )

    first = projector.project(
        {"type": "values", "ns": (), "data": {}, "interrupts": (interrupt,)}
    )
    duplicate = projector.project(
        {"type": "values", "ns": (), "data": {}, "interrupts": (interrupt,)}
    )
    tool_message = projector.project(
        {"type": "messages", "ns": (), "data": (ToolMessage(content="done", tool_call_id="c1"), {})}
    )
    debug = projector.project({"type": "debug", "ns": (), "data": {"event": "model.start"}})

    assert len(first) == 1
    assert first[0].type == "approval.required"
    assert first[0].payload == {"interrupt_id": "interrupt-1"}
    assert duplicate == ()
    assert tool_message == ()
    assert debug == ()


def test_errors_are_sanitized_and_keepalive_does_not_advance_persisted_cursor():
    projector = AgentEventProjector()
    error = projector.project(
        {
            "type": "tasks",
            "ns": (),
            "data": {"id": "task-1", "name": "agent", "error": "api-key=secret"},
        }
    )
    keepalive = projector.keepalive()
    next_event = projector.project(
        {"type": "custom", "ns": (), "data": {"type": "execution.completed", "payload": {}}}
    )

    assert error[0].payload == {"code": "agent_execution_failed"}
    assert keepalive.type == "keepalive"
    assert keepalive.cursor is None
    assert next_event[0].cursor == 2


def test_unknown_custom_events_and_unsafe_payload_keys_are_not_forwarded():
    projector = AgentEventProjector()

    assert projector.project(
        {"type": "custom", "ns": (), "data": {"type": "model.raw", "payload": {"prompt": "secret"}}}
    ) == ()
    event = projector.project(
        {
            "type": "custom",
            "ns": (),
            "data": {
                "type": "publication.changed",
                "payload": {"draft_id": "d1", "api_key": "secret", "status": "published"},
            },
        }
    )[0]
    assert event.payload == {"draft_id": "d1", "status": "published"}


def test_curation_seed_event_drops_content_and_provider_details():
    event = AgentEventProjector().project({
        "type": "custom",
        "ns": (),
        "data": {
            "type": "curation.seed.changed",
            "payload": {
                "sessionId": "session-1",
                "batchId": "batch-1",
                "seedTaskId": "seed-1",
                "status": "degraded",
                "manualAttemptCount": 1,
                "answerBasis": "mixed",
                "needsReview": True,
                "questionText": "secret question",
                "referenceAnswer": "secret answer",
                "providerOutput": {"secret": True},
                "path": "/private/workspace",
            },
        },
    })[0]

    assert event.payload == {
        "sessionId": "session-1",
        "batchId": "batch-1",
        "seedTaskId": "seed-1",
        "status": "degraded",
        "manualAttemptCount": 1,
        "answerBasis": "mixed",
        "needsReview": True,
    }
