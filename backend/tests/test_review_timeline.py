import sqlite3
from pathlib import Path

import pytest

from app.application.session_service import ProductEventStream, ProductRepository
from app.infrastructure.runtime_database import connect_runtime_database
from app.review.timeline import SessionTimelineProjector


@pytest.mark.asyncio
async def test_timeline_message_persists_structured_payload_and_emits_safe_event(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="w1", kind="question.curate", title="Curation"
    )
    events = ProductEventStream(repository, workspace_root=tmp_path)
    projector = SessionTimelineProjector(repository, events)

    message = await projector.append(
        session_id=session.id,
        execution_id=None,
        role="assistant",
        message_kind="stage",
        content="正在合并相似题",
        payload={"resourceId": "curation-1", "version": 2, "stage": "merging"},
    )

    assert message.message_kind == "stage"
    assert message.payload == {
        "resourceId": "curation-1",
        "version": 2,
        "stage": "merging",
    }
    stored = repository.list_messages(session.id)
    assert stored == (message,)
    event = repository.list_events(session.id, after_id=None)[-1]
    assert event.type == "session.message.created"
    assert event.payload == {
        "messageId": message.id,
        "messageKind": "stage",
        "resourceId": "curation-1",
        "version": 2,
    }
    assert "正在合并相似题" not in str(event.payload)
    connection.close()


def test_product_messages_reject_unknown_kind_and_non_object_payload(
    tmp_path: Path,
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="w1", kind="question.curate", title="Curation"
    )

    with pytest.raises(ValueError, match="message kind"):
        repository.append_message(
            session.id,
            execution_id=None,
            role="assistant",
            content="bad",
            message_kind="chain_of_thought",
            payload={},
        )
    with pytest.raises(ValueError, match="payload"):
        repository.append_message(
            session.id,
            execution_id=None,
            role="assistant",
            content="bad",
            message_kind="stage",
            payload=[],  # type: ignore[arg-type]
        )
    connection.close()


@pytest.mark.asyncio
async def test_product_event_retries_a_transient_sqlite_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = connect_runtime_database(tmp_path)
    repository = ProductRepository(connection)
    session = repository.create_session(
        workspace_id="w1", kind="profile.chat", title="Profile"
    )
    events = ProductEventStream(repository, workspace_root=tmp_path)
    original_append = repository.append_event
    attempts = 0

    def append_with_transient_lock(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(repository, "append_event", append_with_transient_lock)

    event = await events.publish(
        session.id,
        None,
        "execution.started",
        {"executionId": "r1"},
    )

    assert event.type == "execution.started"
    assert attempts == 2
    connection.close()
