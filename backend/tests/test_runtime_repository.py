import pytest

from app.db.runtime_database import connect_runtime_database
from app.runtime.repository import (
    InvalidRunTransitionError,
    RuntimeRepository,
    SessionBusyError,
)


@pytest.fixture
def repository(tmp_path):
    connection = connect_runtime_database(tmp_path)
    yield RuntimeRepository(connection)
    connection.close()


def create_session(repository: RuntimeRepository):
    return repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Echo",
    )


def test_list_sessions_uses_insertion_order_when_timestamps_tie(repository):
    older = repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Older",
        session_id="z-older",
    )
    newer = repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Newer",
        session_id="a-newer",
    )

    assert repository.list_sessions("w1") == (newer, older)


def test_failed_run_returns_session_to_active(repository):
    session = create_session(repository)
    run = repository.create_run(
        session.id,
        input={"text": "hello"},
        model_bindings={"agent_chat": "model-1"},
    )

    running = repository.transition_run(
        run.id, expected="queued", target="running"
    )
    failed = repository.transition_run(
        run.id,
        expected="running",
        target="failed",
        error_code="boom",
        error_message="failed safely",
    )

    assert running.started_at is not None
    assert failed.status == "failed"
    assert failed.error_code == "boom"
    assert repository.get_session(session.id).status == "active"
    assert repository.get_session(session.id).last_run_id == run.id


def test_second_active_run_is_rejected_by_database_constraint(repository):
    session = create_session(repository)
    repository.create_run(session.id, input={"text": "one"}, model_bindings={})

    with pytest.raises(SessionBusyError):
        repository.create_run(
            session.id, input={"text": "two"}, model_bindings={}
        )


def test_stale_run_transition_is_rejected(repository):
    session = create_session(repository)
    run = repository.create_run(session.id, input={}, model_bindings={})

    with pytest.raises(InvalidRunTransitionError):
        repository.transition_run(run.id, expected="running", target="completed")

    assert repository.get_run(run.id).status == "queued"


def test_messages_keep_insertion_order(repository):
    session = create_session(repository)
    first = repository.append_message(
        session.id, run_id=None, role="user", content="first"
    )
    second = repository.append_message(
        session.id, run_id=None, role="assistant", content="second"
    )

    assert [message.id for message in repository.list_messages(session.id)] == [
        first.id,
        second.id,
    ]


def test_events_are_monotonic_and_replay_after_id(repository):
    session = create_session(repository)
    run = repository.create_run(session.id, input={}, model_bindings={})
    first = repository.append_event(
        session.id, run.id, "run.started", {"attempt": 1}
    )
    second = repository.append_event(
        session.id, run.id, "message.delta", {"text": "hi"}
    )

    assert second.id > first.id
    assert repository.get_event(first.id) == first
    assert repository.list_events(session.id, after_id=first.id) == (second,)


def test_recovery_interrupts_only_running_runs(repository):
    running_session = create_session(repository)
    running = repository.create_run(
        running_session.id, input={}, model_bindings={}
    )
    repository.transition_run(running.id, expected="queued", target="running")

    waiting_session = repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title="Waiting",
    )
    waiting = repository.create_run(waiting_session.id, input={}, model_bindings={})
    repository.transition_run(
        waiting.id, expected="queued", target="waiting_for_approval"
    )

    interrupted = repository.interrupt_running_runs()

    assert interrupted == (running.id,)
    assert repository.get_run(running.id).status == "interrupted"
    assert repository.get_session(running_session.id).status == "interrupted"
    assert repository.get_run(waiting.id).status == "waiting_for_approval"
    assert repository.get_session(waiting_session.id).status == "waiting_for_approval"


def test_resume_keeps_run_id_and_increments_count(repository):
    session = create_session(repository)
    run = repository.create_run(session.id, input={}, model_bindings={})
    repository.transition_run(run.id, expected="queued", target="running")
    repository.transition_run(run.id, expected="running", target="interrupted")

    resumed = repository.resume_run(run.id, expected="interrupted")

    assert resumed.id == run.id
    assert resumed.status == "queued"
    assert resumed.resume_count == 1
    assert resumed.last_resumed_at is not None
