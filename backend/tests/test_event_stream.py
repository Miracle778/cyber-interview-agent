import asyncio

import pytest

from app.db.runtime_database import connect_runtime_database
from app.runtime.event_stream import EventStream, EventValidationError, encode_sse_event
from app.runtime.repository import RuntimeRepository


@pytest.fixture
def runtime_repository(tmp_path):
    connection = connect_runtime_database(tmp_path)
    repository = RuntimeRepository(connection)
    session = repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Echo",
        session_id="s1",
    )
    repository.create_run(
        session.id, input={}, model_bindings={}, run_id="r1"
    )
    yield repository
    connection.close()


@pytest.mark.asyncio
async def test_publish_persists_and_scrubs_before_subscriber_receives(
    runtime_repository,
):
    stream = EventStream(runtime_repository)
    subscription = stream.subscribe("s1", after_id=None)

    published = await stream.publish(
        "s1",
        "r1",
        "run.started",
        {
            "apiKey": "sk-secret",
            "nested": {"authorization": "Bearer secret", "safe": "visible"},
            "items": [{"refresh_token": "hidden", "tokenUsage": 3}],
        },
    )
    received = await anext(subscription)

    assert received.id == published.id
    assert runtime_repository.get_event(published.id) == published
    assert received.payload == {
        "items": [{"tokenUsage": 3}],
        "nested": {"safe": "visible"},
    }
    await subscription.aclose()


@pytest.mark.asyncio
async def test_subscribe_replays_after_event_id(runtime_repository):
    first = runtime_repository.append_event(
        "s1", "r1", "message.delta", {"text": "a"}
    )
    second = runtime_repository.append_event(
        "s1", "r1", "message.delta", {"text": "b"}
    )

    subscription = EventStream(runtime_repository).subscribe(
        "s1", after_id=first.id
    )

    assert await anext(subscription) == second
    await subscription.aclose()


@pytest.mark.asyncio
async def test_live_subscriber_receives_event_after_waiting(runtime_repository):
    stream = EventStream(runtime_repository)
    subscription = stream.subscribe("s1", after_id=None)
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    published = await stream.publish(
        "s1", "r1", "message.completed", {"content": "hello"}
    )

    assert await asyncio.wait_for(waiting, timeout=1) == published
    await subscription.aclose()


@pytest.mark.asyncio
async def test_unknown_event_type_is_rejected(runtime_repository):
    with pytest.raises(EventValidationError):
        await EventStream(runtime_repository).publish(
            "s1", "r1", "unknown.event", {}
        )


def test_encode_sse_event_uses_camel_case_envelope(runtime_repository):
    event = runtime_repository.append_event(
        "s1", "r1", "message.delta", {"text": "hello"}
    )

    encoded = encode_sse_event(event)

    assert encoded.startswith(f"id: {event.id}\nevent: message.delta\n")
    assert '"sessionId":"s1"' in encoded
    assert '"runId":"r1"' in encoded
    assert encoded.endswith("\n\n")
