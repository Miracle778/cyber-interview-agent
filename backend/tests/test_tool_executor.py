from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from app.db.runtime_database import connect_runtime_database
from app.runtime.event_stream import EventStream
from app.runtime.repository import RuntimeRepository
from app.tools.audit import ToolAuditRepository
from app.tools.context import ToolExecutionContext
from app.tools.defaults import create_default_tool_registry
from app.tools.executor import (
    BoundToolInvoker,
    ToolExecutionFailedError,
    sanitize_tool_payload,
)
from app.tools.registry import (
    ToolDefinition,
    ToolNotAllowedError,
    ToolRegistry,
    ToolScopeDeniedError,
)


@pytest.fixture
def runtime_parts(tmp_path: Path):
    for relative in (
        "artifacts/review/sources",
        "artifacts/review/drafts",
        "knowledge-vault",
        ".cyber-interview-agent/diagnostics",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts/review/sources/notes.md").write_text(
        "private body", encoding="utf-8"
    )
    connection = connect_runtime_database(tmp_path)
    runtime = RuntimeRepository(connection)
    runtime.create_session(
        workspace_id="w1",
        graph_id="test.files",
        graph_version=1,
        title="Files",
        session_id="s1",
    )
    runtime.create_run(
        "s1", input={}, model_bindings={}, run_id="r1", initial_status="running"
    )
    audit = ToolAuditRepository(tmp_path)
    context = ToolExecutionContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        graph_id="test.files",
        graph_version=1,
        allowed_tools=frozenset({"read_source", "read_active_knowledge"}),
        allowed_scopes=frozenset({"review.sources"}),
    )
    yield connection, runtime, audit, context
    connection.close()


@pytest.mark.asyncio
async def test_success_is_audited_before_safe_events(runtime_parts) -> None:
    _connection, runtime, audit, context = runtime_parts

    class OrderedEventStream(EventStream):
        async def publish(self, session_id, run_id, event_type, payload):
            records = await audit.list_for_run("r1")
            expected = "started" if event_type == "tool.started" else "completed"
            assert records[-1].status == expected
            return await super().publish(
                session_id, run_id, event_type, payload
            )

    invoker = BoundToolInvoker(
        context=context,
        registry=create_default_tool_registry(),
        audit_repository=audit,
        event_stream=OrderedEventStream(runtime),
    )

    result = await invoker.invoke_tool("read_source", {"path": "notes.md"})

    assert result["text"] == "private body"
    events = runtime.list_events("s1")
    assert [event.type for event in events] == ["tool.started", "tool.completed"]
    persisted = f"{await audit.list_for_run('r1')}{events}"
    assert "private body" not in persisted
    assert str(context.workspace_root) not in persisted


@pytest.mark.asyncio
async def test_unknown_tool_is_audited_and_emits_safe_failure(runtime_parts) -> None:
    _connection, runtime, audit, context = runtime_parts
    invoker = BoundToolInvoker(
        context=context,
        registry=create_default_tool_registry(),
        audit_repository=audit,
        event_stream=EventStream(runtime),
    )

    with pytest.raises(ToolNotAllowedError):
        await invoker.invoke_tool(
            "shell", {"authorization": "Bearer secret", "content": "private"}
        )

    record = (await audit.list_for_run("r1"))[-1]
    event = runtime.list_events("s1")[-1]
    assert record.status == "failed"
    assert record.error_code == "tool_not_allowed"
    assert event.type == "tool.failed"
    assert event.payload["code"] == "tool_not_allowed"
    assert "secret" not in f"{record}{event}"
    assert "private" not in f"{record}{event}"


@pytest.mark.asyncio
async def test_missing_scope_fails_before_file_handler(runtime_parts) -> None:
    _connection, runtime, audit, context = runtime_parts
    invoker = BoundToolInvoker(
        context=context,
        registry=create_default_tool_registry(),
        audit_repository=audit,
        event_stream=EventStream(runtime),
    )

    with pytest.raises(ToolScopeDeniedError):
        await invoker.invoke_tool("read_active_knowledge", {"path": "missing.md"})

    assert (await audit.list_for_run("r1"))[-1].error_code == "tool_scope_denied"


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyOutput(BaseModel):
    ok: bool


@pytest.mark.asyncio
async def test_unexpected_handler_error_is_replaced_with_stable_failure(
    runtime_parts,
) -> None:
    _connection, runtime, audit, context = runtime_parts
    registry = ToolRegistry()

    def fail(_context, _input):
        raise RuntimeError("authorization=Bearer sk-secret")

    registry.register(
        ToolDefinition(
            name="read_source",
            input_model=EmptyInput,
            output_model=EmptyOutput,
            risk_level="low",
            required_scope="review.sources",
            audit_policy="metadata_only",
            handler=fail,
        )
    )
    invoker = BoundToolInvoker(
        context=context,
        registry=registry,
        audit_repository=audit,
        event_stream=EventStream(runtime),
    )

    with pytest.raises(ToolExecutionFailedError) as caught:
        await invoker.invoke_tool("read_source", {})

    assert caught.value.code == "tool_execution_failed"
    assert (await audit.list_for_run("r1"))[-1].error_code == "tool_execution_failed"
    assert "sk-secret" not in str(runtime.list_events("s1")[-1].payload)


def test_sanitizer_removes_secrets_bodies_and_absolute_paths() -> None:
    payload = {
        "authorization": "Bearer secret",
        "content": "private body",
        "nested": {
            "apiKey": "sk-secret",
            "tokenUsage": {"input": 3, "output": 2},
            "path": "/Users/person/workspace/private.md",
            "safe": "visible",
        },
    }

    assert sanitize_tool_payload(payload) == {
        "nested": {
            "tokenUsage": {"input": 3, "output": 2},
            "safe": "visible",
        }
    }
