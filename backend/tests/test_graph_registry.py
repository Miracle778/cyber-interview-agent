import pytest

from app.runtime.graph_registry import (
    DuplicateGraphDefinitionError,
    GraphDefinition,
    GraphRegistry,
    GraphVersionNotFoundError,
)


def definition(version: int) -> GraphDefinition:
    return GraphDefinition(
        graph_id="test.echo",
        graph_version=version,
        factory=lambda checkpointer: ("compiled", checkpointer),
        required_model_roles=frozenset(),
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )


def test_registry_resolves_exact_graph_version():
    registry = GraphRegistry()
    registered = definition(1)

    registry.register(registered)

    assert registry.get("test.echo", 1) is registered
    assert registry.get("test.echo", 1).factory("checkpoint") == (
        "compiled",
        "checkpoint",
    )


def test_registry_does_not_fall_forward_to_new_version():
    registry = GraphRegistry()
    registry.register(definition(2))

    with pytest.raises(GraphVersionNotFoundError):
        registry.get("test.echo", 1)


def test_registry_rejects_duplicate_graph_version():
    registry = GraphRegistry()
    registry.register(definition(1))

    with pytest.raises(DuplicateGraphDefinitionError):
        registry.register(definition(1))
