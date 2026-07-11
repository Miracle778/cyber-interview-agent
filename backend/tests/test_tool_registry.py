from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from app.tools.context import ToolExecutionContext
from app.tools.registry import (
    DuplicateToolDefinitionError,
    ToolDefinition,
    ToolInputInvalidError,
    ToolNotAllowedError,
    ToolOutputInvalidError,
    ToolRegistry,
    ToolScopeDeniedError,
)


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class ReadOutput(BaseModel):
    path: str
    text: str


@pytest.fixture
def context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_id="w1",
        workspace_root=tmp_path,
        session_id="s1",
        run_id="r1",
        graph_id="test.graph",
        graph_version=1,
        allowed_tools=frozenset({"read_source"}),
        allowed_scopes=frozenset({"review.sources"}),
    )


@pytest.fixture
def called() -> list[bool]:
    return []


@pytest.fixture
def definition(called: list[bool]) -> ToolDefinition:
    def handler(_context: ToolExecutionContext, input_data: ReadInput) -> ReadOutput:
        called.append(True)
        return ReadOutput(path=input_data.path, text="safe")

    return ToolDefinition(
        name="read_source",
        input_model=ReadInput,
        output_model=ReadOutput,
        risk_level="low",
        required_scope="review.sources",
        audit_policy="metadata_only",
        handler=handler,
    )


@pytest.fixture
def registry(definition: ToolDefinition) -> ToolRegistry:
    result = ToolRegistry()
    result.register(definition)
    return result


def test_invokes_registered_allowed_tool(
    registry: ToolRegistry, context: ToolExecutionContext, called: list[bool]
) -> None:
    result = registry.invoke("read_source", context, {"path": "notes.md"})

    assert result == {"path": "notes.md", "text": "safe"}
    assert called == [True]


def test_unknown_tool_is_rejected_before_handler(
    registry: ToolRegistry, context: ToolExecutionContext, called: list[bool]
) -> None:
    with pytest.raises(ToolNotAllowedError) as caught:
        registry.invoke("shell", context, {})

    assert caught.value.code == "tool_not_allowed"
    assert called == []


def test_tool_allowlist_is_checked_before_handler(
    registry: ToolRegistry, context: ToolExecutionContext, called: list[bool]
) -> None:
    denied = replace(context, allowed_tools=frozenset())

    with pytest.raises(ToolNotAllowedError):
        registry.invoke("read_source", denied, {"path": "notes.md"})

    assert called == []


def test_scope_is_checked_before_handler(
    registry: ToolRegistry, context: ToolExecutionContext, called: list[bool]
) -> None:
    denied = replace(context, allowed_scopes=frozenset())

    with pytest.raises(ToolScopeDeniedError) as caught:
        registry.invoke("read_source", denied, {"path": "notes.md"})

    assert caught.value.code == "tool_scope_denied"
    assert called == []


@pytest.mark.parametrize(
    "raw_input",
    [
        {},
        {"path": 123},
        {"path": "notes.md", "workspace_root": "/tmp/other"},
        {"path": "notes.md", "allowed_scopes": ["knowledge.active"]},
    ],
)
def test_invalid_or_context_shaped_input_is_rejected_before_handler(
    registry: ToolRegistry,
    context: ToolExecutionContext,
    called: list[bool],
    raw_input: dict[str, object],
) -> None:
    with pytest.raises(ToolInputInvalidError) as caught:
        registry.invoke("read_source", context, raw_input)

    assert caught.value.code == "tool_input_invalid"
    assert called == []


def test_invalid_handler_output_is_rejected(
    context: ToolExecutionContext,
) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="read_source",
            input_model=ReadInput,
            output_model=ReadOutput,
            risk_level="low",
            required_scope="review.sources",
            audit_policy="metadata_only",
            handler=lambda _context, input_data: {"path": input_data.path},
        )
    )

    with pytest.raises(ToolOutputInvalidError) as caught:
        registry.invoke("read_source", context, {"path": "notes.md"})

    assert caught.value.code == "tool_output_invalid"


def test_rejects_duplicate_tool_name(definition: ToolDefinition) -> None:
    registry = ToolRegistry()
    registry.register(definition)

    with pytest.raises(DuplicateToolDefinitionError):
        registry.register(definition)


def test_context_is_immutable(context: ToolExecutionContext) -> None:
    with pytest.raises((AttributeError, TypeError)):
        context.run_id = "other"  # type: ignore[misc]
