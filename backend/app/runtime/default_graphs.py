from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime.approval_diagnostic_graph import create_approval_diagnostic_graph
from app.runtime.graph_build_context import GraphBuildContext
from app.runtime.graph_registry import GraphDefinition, GraphRegistry
from app.runtime.knowledge_publication_graph import (
    create_knowledge_publication_graph,
)
from app.runtime.security_diagnostic_graph import create_security_diagnostic_graph
from app.agents.review_definition import single_review_definition


class _EchoState(TypedDict, total=False):
    text: str
    response: str


def create_default_graph_registry() -> GraphRegistry:
    def echo_factory(context: GraphBuildContext):
        graph = StateGraph(_EchoState)
        graph.add_node(
            "echo", lambda state: {"response": f"Echo: {state['text']}"}
        )
        graph.add_edge(START, "echo")
        graph.add_edge("echo", END)
        return graph.compile(checkpointer=context.checkpointer)

    registry = GraphRegistry()
    registry.register(single_review_definition())
    registry.register(
        GraphDefinition(
            graph_id="knowledge.publish",
            graph_version=1,
            factory=create_knowledge_publication_graph,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    registry.register(
        GraphDefinition(
            graph_id="test.approval",
            graph_version=1,
            factory=create_approval_diagnostic_graph,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    registry.register(
        GraphDefinition(
            graph_id="test.echo",
            graph_version=1,
            factory=echo_factory,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(),
            allowed_scopes=frozenset(),
        )
    )
    registry.register(
        GraphDefinition(
            graph_id="test.tool-security",
            graph_version=1,
            factory=create_security_diagnostic_graph,
            required_model_roles=frozenset(),
            allowed_tools=frozenset(
                {"diagnostic_read", "read_active_knowledge"}
            ),
            allowed_scopes=frozenset({"diagnostics.security"}),
        )
    )
    return registry
