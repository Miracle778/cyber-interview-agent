from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool

from app.agents.agent_factory import AgentFactory, AgentSpec
import app.agents.agent_factory as agent_factory_module
from app.agents.prompts.prompt_spec import PromptSpec
from app.diagnostics.agent_trace import read_trace_rows


class StubResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, role: str, provider_model_id: str):
        self.calls.append((role, provider_model_id))
        return object()


def _spec(
    *,
    role: str = "retrospective_chat",
    execution_name: str = "interview_retrospective_chat",
    tools=(),
) -> AgentSpec:
    return AgentSpec(
        role=role,
        execution_name=execution_name,
        prompt=PromptSpec(id="component-contract", version="1", system="test"),
        tools=tuple(tools),
    )


def test_registered_agent_factory_rejects_an_undeclared_component_before_model_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = StubResolver()
    monkeypatch.setattr("app.agents.agent_factory.create_agent", lambda **kwargs: kwargs)
    registered = AgentFactory(resolver).bind("interview.retrospective")

    with pytest.raises(ValueError, match="component_not_allowed"):
        registered.create(
            _spec(execution_name="undeclared_component"),
            component_id="undeclared_component",
            model_bindings={"retrospective_chat": "model-1"},
        )

    assert resolver.calls == []


def test_registered_agent_factory_rejects_an_undeclared_model_role_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = StubResolver()
    monkeypatch.setattr("app.agents.agent_factory.create_agent", lambda **kwargs: kwargs)
    registered = AgentFactory(resolver).bind("interview.retrospective")

    with pytest.raises(ValueError, match="model_role_not_allowed"):
        registered.create(
            _spec(role="profile_extraction"),
            component_id="interview_retrospective_chat",
            model_bindings={"profile_extraction": "model-1"},
        )

    assert resolver.calls == []


def test_registered_agent_factory_rejects_an_undeclared_tool_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = StubResolver()
    monkeypatch.setattr("app.agents.agent_factory.create_agent", lambda **kwargs: kwargs)
    forbidden = StructuredTool.from_function(
        lambda: "forbidden",
        name="write_workspace_secret",
        description="must not be available",
    )
    registered = AgentFactory(resolver).bind("interview.retrospective")

    with pytest.raises(ValueError, match="tool_not_allowed"):
        registered.create(
            _spec(tools=(forbidden,)),
            component_id="interview_retrospective_chat",
            model_bindings={"retrospective_chat": "model-1"},
        )

    assert resolver.calls == []


def test_registered_agent_factory_rejects_tool_policy_scope_outside_definition() -> None:
    registered = AgentFactory(StubResolver()).bind("interview.retrospective")

    with pytest.raises(ValueError, match="scope_not_allowed"):
        registered.create_tool_policy(
            audit=object(),
            required_scopes={"read_source_excerpt": "profile.materials"},
        )


def test_unbound_agent_factory_cannot_create_a_model_call_boundary() -> None:
    resolver = StubResolver()

    with pytest.raises(ValueError, match="agent_definition_required"):
        AgentFactory(resolver).create(
            _spec(),
            model_bindings={"retrospective_chat": "model-1"},
        )

    assert resolver.calls == []


@pytest.mark.asyncio
async def test_registered_component_identity_is_written_to_every_model_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.agents.agent_factory.create_agent", lambda **kwargs: kwargs)
    registered = AgentFactory(StubResolver()).bind("interview.retrospective")
    created = registered.create(
        _spec(),
        component_id="interview_retrospective_chat",
        model_bindings={"retrospective_chat": "model-1"},
    )
    middleware = created["middleware"][0]
    context = SimpleNamespace(
        workspace_id="workspace-1",
        workspace_root=tmp_path,
        session_id="session-1",
        run_id="run-1",
        progress_scope=(),
        trace_warning=None,
    )
    request = SimpleNamespace(
        messages=[HumanMessage(content="question")],
        system_message=SystemMessage(content="system"),
        tools=[],
        response_format=None,
        model_settings={},
        runtime=SimpleNamespace(context=context),
    )

    async def succeed(_request):
        return "answer"

    await middleware.awrap_model_call(request, succeed)

    rows = read_trace_rows(tmp_path, "session-1", "run-1")
    assert len(rows) == 2
    assert {
        (
            row["agent_id"],
            row["agent_definition_version"],
            row["component_id"],
        )
        for row in rows
    } == {("interview.retrospective", "1", "interview_retrospective_chat")}


def test_model_resolver_import_boundary_detects_a_product_bypass(
    tmp_path: Path,
) -> None:
    product = tmp_path / "app" / "feature.py"
    product.parent.mkdir()
    product.write_text(
        "from app.agents.agent_model_resolver import ChatModelResolver\n",
        encoding="utf-8",
    )

    violations = agent_factory_module.find_model_resolver_import_violations(
        tmp_path / "app",
        allowed_relative_paths=frozenset(),
    )

    assert violations == ("feature.py",)


def test_production_model_resolver_imports_stay_inside_control_plane() -> None:
    app_root = Path(__file__).parents[1] / "app"

    assert agent_factory_module.find_model_resolver_import_violations(app_root) == ()
