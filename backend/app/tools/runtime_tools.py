from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from langchain.tools import ToolRuntime

from app.agents.context import AgentContext
from app.tools.context import ToolExecutionContext
from app.tools.file_tools import (
    ReadTextInput,
    WriteDraftInput,
    diagnostic_read,
    read_active_knowledge,
    read_source,
    write_review_draft,
)


def _legacy_context(context: AgentContext) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_id=context.workspace_id,
        workspace_root=context.workspace_root,
        session_id=context.session_id,
        run_id=context.run_id,
        graph_id="agent",
        graph_version=1,
        allowed_tools=context.allowed_tools,
        allowed_scopes=context.allowed_scopes,
    )


@tool("read_source", args_schema=ReadTextInput)
def read_source_tool(path: str, runtime: ToolRuntime[AgentContext]) -> dict:
    """Read UTF-8 source material from the current Workspace."""
    return read_source(
        _legacy_context(runtime.context), ReadTextInput(path=path)
    ).model_dump(mode="json")


@tool("read_active_knowledge", args_schema=ReadTextInput)
def read_active_knowledge_tool(
    path: str, runtime: ToolRuntime[AgentContext]
) -> dict:
    """Read an active Markdown page from the current knowledge Vault."""
    return read_active_knowledge(
        _legacy_context(runtime.context), ReadTextInput(path=path)
    ).model_dump(mode="json")


@tool("write_review_draft", args_schema=WriteDraftInput)
def write_review_draft_tool(
    path: str,
    content: str,
    runtime: ToolRuntime[AgentContext],
    expected_sha256: str | None = None,
) -> dict:
    """Atomically write a review draft inside the current Workspace."""
    return write_review_draft(
        _legacy_context(runtime.context),
        WriteDraftInput(
            path=path,
            content=content,
            expected_sha256=expected_sha256,
        ),
    ).model_dump(mode="json")


@tool("diagnostic_read", args_schema=ReadTextInput)
def diagnostic_read_tool(path: str, runtime: ToolRuntime[AgentContext]) -> dict:
    """Read the fixed security diagnostic probe for the current Workspace."""
    return diagnostic_read(
        _legacy_context(runtime.context), ReadTextInput(path=path)
    ).model_dump(mode="json")


def create_runtime_tools() -> tuple[BaseTool, ...]:
    return (
        read_source_tool,
        read_active_knowledge_tool,
        write_review_draft_tool,
        diagnostic_read_tool,
    )
