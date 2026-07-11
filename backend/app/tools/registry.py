from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.tools.context import ToolExecutionContext


class ToolError(RuntimeError):
    code = "tool_error"


class ToolNotAllowedError(ToolError):
    code = "tool_not_allowed"


class ToolScopeDeniedError(ToolError):
    code = "tool_scope_denied"


class ToolInputInvalidError(ToolError):
    code = "tool_input_invalid"


class ToolOutputInvalidError(ToolError):
    code = "tool_output_invalid"


class DuplicateToolDefinitionError(ToolError):
    code = "duplicate_tool_definition"


ToolHandler = Callable[[ToolExecutionContext, BaseModel], BaseModel | dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: str
    required_scope: str
    audit_policy: str
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name must not be empty")
        if not self.required_scope.strip():
            raise ValueError("required_scope must not be empty")


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise DuplicateToolDefinitionError(
                f"tool {definition.name!r} is already registered"
            )
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as error:
            raise ToolNotAllowedError("Tool is not allowed") from error

    def invoke(
        self,
        name: str,
        context: ToolExecutionContext,
        raw_input: dict[str, object],
    ) -> dict[str, Any]:
        definition = self.get(name)
        if name not in context.allowed_tools:
            raise ToolNotAllowedError("Tool is not allowed")
        if definition.required_scope not in context.allowed_scopes:
            raise ToolScopeDeniedError("Tool scope is not allowed")

        try:
            input_data = definition.input_model.model_validate(raw_input)
        except ValidationError as error:
            raise ToolInputInvalidError("Tool input is invalid") from error

        raw_output = definition.handler(context, input_data)
        try:
            output_data = definition.output_model.model_validate(raw_output)
        except ValidationError as error:
            raise ToolOutputInvalidError("Tool output is invalid") from error
        return output_data.model_dump(mode="json")
