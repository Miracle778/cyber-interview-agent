from pathlib import Path

import pytest

from app.runtime.default_graphs import create_default_graph_registry
from app.runtime.service import AgentRuntime
from app.tools.audit import ToolAuditRepository


@pytest.mark.asyncio
async def test_security_diagnostic_exercises_real_tool_boundaries(
    tmp_path: Path,
) -> None:
    runtime = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="test.tool-security",
        graph_version=1,
        title="工具安全自检",
    )

    run = await runtime.start_run(session.id, input={})
    completed = await runtime._context("w1").manager.wait(run.id)

    repository = runtime._context("w1").repository
    events = repository.list_events(session.id)
    tool_events = [event for event in events if event.type.startswith("tool.")]
    audits = await ToolAuditRepository(tmp_path).list_for_run(run.id)

    assert completed.status == "completed"
    assert [event.type for event in tool_events].count("tool.completed") == 1
    assert {
        event.payload.get("code")
        for event in tool_events
        if event.type == "tool.failed"
    } == {"tool_not_allowed", "tool_scope_denied", "workspace_path_denied"}
    assert [record.status for record in audits] == [
        "completed",
        "failed",
        "failed",
        "failed",
    ]
    assert {record.error_code for record in audits if record.error_code} == {
        "tool_not_allowed",
        "tool_scope_denied",
        "workspace_path_denied",
    }
    persisted = f"{events}{audits}"
    assert "tool-security-probe-v1" not in persisted
    assert "diagnostic-secret" not in persisted
    assert str(tmp_path) not in persisted
    assert repository.list_messages(session.id)[-1].content == "工具安全自检通过"
    await runtime.close()


def test_security_graph_has_only_diagnostic_permissions() -> None:
    definition = create_default_graph_registry().get("test.tool-security", 1)

    assert definition.allowed_tools == frozenset(
        {"diagnostic_read", "read_active_knowledge"}
    )
    assert definition.allowed_scopes == frozenset({"diagnostics.security"})


@pytest.mark.asyncio
async def test_security_diagnostic_can_run_twice_in_the_same_session(
    tmp_path: Path,
) -> None:
    runtime = AgentRuntime(
        graph_registry=create_default_graph_registry(),
        workspace_resolver=lambda _workspace_id: tmp_path,
        model_binding_resolver=lambda _workspace_id: {},
        workspace_ids=lambda: ("w1",),
    )
    session = await runtime.create_session(
        workspace_id="w1",
        graph_id="test.tool-security",
        graph_version=1,
        title="工具安全自检",
    )

    first = await runtime.start_run(session.id, input={})
    first_completed = await runtime._context("w1").manager.wait(first.id)
    second = await runtime.start_run(session.id, input={})
    second_completed = await runtime._context("w1").manager.wait(second.id)

    assert first_completed.status == "completed"
    assert second_completed.status == "completed"
    assert len(await ToolAuditRepository(tmp_path).list_for_run(second.id)) == 4
    await runtime.close()
