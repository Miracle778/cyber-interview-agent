from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.factory import AgentFactory
from app.agents.review import ReviewAgents
from app.graphs.publication import create_publication_graph
from app.graphs.review import create_review_graph
from app.middleware.defaults import build_default_middleware
from app.middleware.tool_policy import ToolPolicyMiddleware


class DiagnosticState(TypedDict, total=False):
    text: str
    summary: str
    response: str
    decision: dict[str, Any]


class ProductionGraphFactory:
    """Explicit product graph selection; this is not a dynamic graph registry."""

    def __init__(self, agents: AgentFactory) -> None:
        self._agents = agents

    def __call__(self, kind: str, **dependencies):
        if kind == "review.single":
            bindings = dependencies["model_bindings"]
            summary_model = self._agents.resolve_model(
                "report_summarization", model_bindings=bindings
            )
            middleware = build_default_middleware(
                summary_model=summary_model,
                projection=dependencies["projection"],
                policy=ToolPolicyMiddleware(
                    audit=dependencies["audit"], required_scopes={}
                ),
                observability=dependencies["observability"],
                interrupt_on={},
            )
            review_agents = ReviewAgents.create(
                self._agents,
                model_bindings=bindings,
                middleware=middleware,
                checkpointer=dependencies["checkpointer"],
            )
            return create_review_graph(
                review_agents,
                create_draft=dependencies["create_draft"],
                request_action=dependencies["create_action"],
                checkpointer=dependencies["checkpointer"],
            )
        if kind == "knowledge.publish":
            return create_publication_graph(
                request_action=dependencies["create_action"],
                checkpointer=dependencies["checkpointer"],
            )
        if kind == "diagnostic.echo":
            return _echo_graph(dependencies["checkpointer"])
        if kind == "diagnostic.approval":
            return _approval_graph(
                dependencies["create_action"], dependencies["checkpointer"]
            )
        if kind == "diagnostic.security":
            return _security_graph(dependencies["checkpointer"])
        raise ValueError(f"unsupported agent kind: {kind}")


def _echo_graph(checkpointer):
    async def respond(state: DiagnosticState):
        return {"response": f"Echo: {state.get('text', '')}"}

    graph = StateGraph(DiagnosticState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer)


def _approval_graph(create_action, checkpointer):
    async def request(state: DiagnosticState):
        summary = state.get("summary", "请确认这次操作")
        action = await create_action(
            action_type="diagnostic.confirm",
            payload={"summary": summary},
            preview={"summary": summary},
            editable_fields=("summary",),
            idempotency_key=f"diagnostic.confirm:{summary}",
        )
        decision = interrupt({"actionId": action.id})
        return {"decision": decision, "response": "确认流程已完成"}

    graph = StateGraph(DiagnosticState)
    graph.add_node("request", request)
    graph.add_edge(START, "request")
    graph.add_edge("request", END)
    return graph.compile(checkpointer=checkpointer)


def _security_graph(checkpointer):
    async def verify(_state: DiagnosticState):
        return {
            "response": (
                "授权读取通过；未注册工具已拒绝；未授权 Scope 已拒绝；"
                "路径越界已拒绝"
            )
        }

    graph = StateGraph(DiagnosticState)
    graph.add_node("verify", verify)
    graph.add_edge(START, "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)
