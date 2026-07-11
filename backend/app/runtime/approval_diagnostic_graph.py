from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.runtime.graph_build_context import GraphBuildContext


class ApprovalDiagnosticState(TypedDict, total=False):
    summary: str
    response: str
    decision: dict[str, Any]


def create_approval_diagnostic_graph(context: GraphBuildContext):
    async def request_approval(state: ApprovalDiagnosticState):
        summary = state.get("summary", "确认测试")
        action = await context.request_action(
            action_type="test.approval",
            payload={"summary": summary},
            preview={"summary": summary},
            editable_fields=("summary",),
            idempotency_key="test.approval",
        )
        decision = interrupt({"actionId": action.id})
        if decision.get("decision") == "approved":
            approved_summary = decision.get("payload", {}).get("summary", summary)
            response = f"确认测试已批准：{approved_summary}"
        else:
            response = f"确认测试已拒绝：{decision.get('reason', '未说明原因')}"
        return {"decision": decision, "response": response}

    graph = StateGraph(ApprovalDiagnosticState)
    graph.add_node("request_approval", request_approval)
    graph.add_edge(START, "request_approval")
    graph.add_edge("request_approval", END)
    return graph.compile(checkpointer=context.checkpointer)
