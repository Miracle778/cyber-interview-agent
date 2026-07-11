from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class GraphRegistryError(RuntimeError):
    pass


class DuplicateGraphDefinitionError(GraphRegistryError):
    pass


class GraphVersionNotFoundError(GraphRegistryError):
    pass


@dataclass(frozen=True, slots=True)
class GraphDefinition:
    graph_id: str
    graph_version: int
    factory: Callable[[Any], Any]
    required_model_roles: frozenset[str]
    allowed_tools: frozenset[str]
    allowed_scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.graph_id.strip():
            raise ValueError("graph_id must not be empty")
        if self.graph_version < 1:
            raise ValueError("graph_version must be positive")


class GraphRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], GraphDefinition] = {}

    def register(self, definition: GraphDefinition) -> None:
        key = (definition.graph_id, definition.graph_version)
        if key in self._definitions:
            raise DuplicateGraphDefinitionError(
                f"graph {definition.graph_id!r} version "
                f"{definition.graph_version} is already registered"
            )
        self._definitions[key] = definition

    def get(self, graph_id: str, graph_version: int) -> GraphDefinition:
        try:
            return self._definitions[(graph_id, graph_version)]
        except KeyError as error:
            raise GraphVersionNotFoundError(
                f"graph {graph_id!r} version {graph_version} is not registered"
            ) from error
