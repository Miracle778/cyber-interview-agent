import asyncio
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.db.runtime_database import connect_runtime_database
from app.runtime.checkpoints import RuntimeCheckpointer
from app.runtime.event_stream import EventStream
from app.runtime.graph_registry import GraphDefinition, GraphRegistry
from app.runtime.repository import RuntimeRepository, SessionBusyError
from app.runtime.run_manager import RunManager


class EchoState(TypedDict, total=False):
    text: str
    response: str


def echo_definition() -> GraphDefinition:
    def factory(checkpointer):
        graph = StateGraph(EchoState)
        graph.add_node(
            "echo", lambda state: {"response": f"Echo: {state['text']}"}
        )
        graph.add_edge(START, "echo")
        graph.add_edge("echo", END)
        return graph.compile(checkpointer=checkpointer)

    return GraphDefinition(
        graph_id="test.echo",
        graph_version=1,
        factory=factory,
        required_model_roles=frozenset(),
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


@pytest.fixture
def runtime_parts(tmp_path):
    connection = connect_runtime_database(tmp_path)
    repository = RuntimeRepository(connection)
    registry = GraphRegistry()
    registry.register(echo_definition())
    checkpointer = RuntimeCheckpointer(tmp_path)
    manager = RunManager(
        repository=repository,
        event_stream=EventStream(repository),
        graph_registry=registry,
        checkpointer=checkpointer,
    )
    yield repository, registry, checkpointer, manager
    connection.close()


def create_session(repository: RuntimeRepository, *, title: str = "Echo"):
    return repository.create_session(
        workspace_id="w1",
        graph_id="test.echo",
        graph_version=1,
        title=title,
    )


@pytest.mark.asyncio
async def test_completed_run_persists_product_messages_events_and_checkpoint(
    runtime_parts,
):
    repository, _registry, checkpointer, manager = runtime_parts
    session = create_session(repository)

    run = await manager.start(
        session.id,
        input={"text": "hello"},
        model_bindings={"agent_chat": "model-1"},
    )
    completed = await manager.wait(run.id)

    assert completed.status == "completed"
    assert [message.role for message in repository.list_messages(session.id)] == [
        "user",
        "assistant",
    ]
    assert repository.list_messages(session.id)[-1].content == "Echo: hello"
    assert [event.type for event in repository.list_events(session.id)] == [
        "run.started",
        "message.completed",
        "run.completed",
    ]
    assert await checkpointer.has_checkpoint(session.id)


@pytest.mark.asyncio
async def test_start_rejects_second_active_run(tmp_path):
    connection = connect_runtime_database(tmp_path)
    repository = RuntimeRepository(connection)
    registry = GraphRegistry()
    gate = asyncio.Event()

    def factory(checkpointer):
        async def wait_node(state):
            await gate.wait()
            return {"response": "done"}

        graph = StateGraph(EchoState)
        graph.add_node("wait", wait_node)
        graph.add_edge(START, "wait")
        graph.add_edge("wait", END)
        return graph.compile(checkpointer=checkpointer)

    registry.register(
        GraphDefinition(
            graph_id="test.echo",
            graph_version=1,
            factory=factory,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    manager = RunManager(
        repository=repository,
        event_stream=EventStream(repository),
        graph_registry=registry,
        checkpointer=RuntimeCheckpointer(tmp_path),
    )
    session = create_session(repository)
    first = await manager.start(session.id, input={"text": "one"}, model_bindings={})

    with pytest.raises(SessionBusyError):
        await manager.start(session.id, input={"text": "two"}, model_bindings={})

    await manager.cancel(first.id)
    gate.set()
    connection.close()


@pytest.mark.asyncio
async def test_cancel_is_idempotent(runtime_parts):
    repository, _registry, _checkpointer, manager = runtime_parts
    session = create_session(repository)
    run = await manager.start(session.id, input={"text": "hello"}, model_bindings={})

    first = await manager.cancel(run.id)
    second = await manager.cancel(run.id)

    assert first.status == "cancelled"
    assert second.status == "cancelled"
    assert [event.type for event in repository.list_events(session.id)].count(
        "run.cancelled"
    ) == 1


@pytest.mark.asyncio
async def test_recovery_marks_running_as_interrupted_and_emits_event(runtime_parts):
    repository, _registry, _checkpointer, manager = runtime_parts
    session = create_session(repository)
    run = repository.create_run(session.id, input={"text": "hello"}, model_bindings={})
    repository.transition_run(run.id, expected="queued", target="running")

    recovered = await manager.recover_interrupted_runs()

    assert recovered == (run.id,)
    assert repository.get_run(run.id).status == "interrupted"
    assert repository.list_events(session.id)[-1].type == "run.interrupted"


@pytest.mark.asyncio
async def test_resume_uses_same_run_and_checkpoint(runtime_parts):
    repository, _registry, _checkpointer, manager = runtime_parts
    session = create_session(repository)
    first = await manager.start(
        session.id, input={"text": "hello"}, model_bindings={}
    )
    await manager.wait(first.id)
    repository.transition_run(first.id, expected="completed", target="interrupted")

    resumed = await manager.resume(first.id)
    completed = await manager.wait(resumed.id)

    assert resumed.id == first.id
    assert completed.status == "completed"
    assert completed.resume_count == 1
