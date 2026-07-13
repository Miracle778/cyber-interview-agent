from __future__ import annotations

from hashlib import sha256

import pytest
from langchain_core.tools import BaseTool
from langchain.tools import ToolRuntime

from app.agents.context import AgentContext
from app.security.workspace_paths import PathPolicyError
from app.tools.runtime_tools import create_runtime_tools


def _context(workspace):
    return AgentContext(
        workspace_id="w1",
        workspace_root=workspace,
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(
            {"read_source", "read_active_knowledge", "write_review_draft"}
        ),
        allowed_scopes=frozenset(
            {"review.sources", "knowledge.active", "review.drafts"}
        ),
    )


def _runtime(context):
    return ToolRuntime(
        state={},
        context=context,
        config={},
        stream_writer=lambda _value: None,
        tool_call_id="tool-call-1",
        store=None,
    )


@pytest.fixture
def workspace(tmp_path):
    for relative in (
        "artifacts/review/sources",
        "artifacts/review/drafts",
        "knowledge-vault",
        ".cyber-interview-agent/diagnostics",
    ):
        (tmp_path / relative).mkdir(parents=True)
    return tmp_path


def test_runtime_tools_are_standard_tools_with_business_only_schemas(workspace):
    tools = {tool.name: tool for tool in create_runtime_tools()}

    assert all(isinstance(tool, BaseTool) for tool in tools.values())
    assert set(tools) == {
        "read_source",
        "read_active_knowledge",
        "write_review_draft",
        "diagnostic_read",
    }
    assert tools["read_source"].args == {"path": {"title": "Path", "type": "string"}}
    assert "runtime" not in tools["write_review_draft"].args


def test_read_source_uses_injected_workspace_context(workspace):
    content = "赛博面试记录"
    encoded = content.encode("utf-8")
    (workspace / "artifacts/review/sources/notes.md").write_bytes(encoded)
    tool = next(tool for tool in create_runtime_tools() if tool.name == "read_source")

    result = tool.func(path="notes.md", runtime=_runtime(_context(workspace)))

    assert result == {
        "path": "notes.md",
        "text": content,
        "sha256": sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
    }


def test_read_source_rejects_workspace_escape_inside_handler(workspace):
    outside = workspace.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    tool = next(tool for tool in create_runtime_tools() if tool.name == "read_source")

    with pytest.raises(PathPolicyError):
        tool.func(path="../../outside.md", runtime=_runtime(_context(workspace)))
