from typing import Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime.graph_build_context import GraphBuildContext
from app.tools.file_tools import DIAGNOSTIC_PROBE_CONTENT


class SecurityDiagnosticState(TypedDict, total=False):
    response: str


async def _expect_rejection(
    operation: Callable[[], Awaitable[dict[str, object]]], expected_code: str
) -> None:
    try:
        await operation()
    except Exception as error:
        if getattr(error, "code", None) == expected_code:
            return
        raise RuntimeError("Tool security diagnostic returned an unexpected code") from error
    raise RuntimeError("Tool security diagnostic unexpectedly allowed an operation")


def create_security_diagnostic_graph(context: GraphBuildContext):
    async def check_boundaries(_state: SecurityDiagnosticState):
        allowed = await context.invoke_tool(
            "diagnostic_read", {"path": "probe.txt"}
        )
        if allowed.get("text") != DIAGNOSTIC_PROBE_CONTENT:
            raise RuntimeError("Tool security diagnostic probe mismatch")

        await _expect_rejection(
            lambda: context.invoke_tool(
                "shell", {"authorization": "Bearer diagnostic-secret"}
            ),
            "tool_not_allowed",
        )
        await _expect_rejection(
            lambda: context.invoke_tool(
                "read_active_knowledge", {"path": "missing.md"}
            ),
            "tool_scope_denied",
        )
        await _expect_rejection(
            lambda: context.invoke_tool(
                "diagnostic_read", {"path": "../escape.txt"}
            ),
            "workspace_path_denied",
        )
        return {"response": "工具安全自检通过"}

    graph = StateGraph(SecurityDiagnosticState)
    graph.add_node("check_tool_boundaries", check_boundaries)
    graph.add_edge(START, "check_tool_boundaries")
    graph.add_edge("check_tool_boundaries", END)
    return graph.compile(checkpointer=context.checkpointer)
