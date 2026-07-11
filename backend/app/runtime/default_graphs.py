from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.runtime.graph_build_context import GraphBuildContext
from app.runtime.graph_registry import GraphDefinition, GraphRegistry


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
    return registry
