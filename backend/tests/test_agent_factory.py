from __future__ import annotations

import pytest
from langchain.agents.structured_output import (
    StructuredOutputValidationError,
    ToolStrategy,
)
from pathlib import Path
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from app.agents.context import AgentContext
from app.agents.agent_factory import AgentFactory, AgentSpec, ModelOverride
from app.agents.prompts.prompt_spec import PromptSpec
from app.agents.review_contracts import AnswerEvaluation
from app.agents.agent_model_resolver import ChatModelResolver, ModelResolutionError
from app.middleware.agent_trace_middleware import AgentTraceMiddleware
from app.db.app_database import connect_app_database
from app.providers.base import ProviderErrorCode
from app.repositories.provider_repository import ProviderRepository
from app.services.secrets import FakeSecretStore


@pytest.fixture
def model_setup(tmp_path):
    connection = connect_app_database(tmp_path)
    repository = ProviderRepository(connection)
    secrets = FakeSecretStore()
    try:
        yield repository, secrets
    finally:
        connection.close()


def _seed_model(
    repository,
    secrets,
    *,
    api_format: str,
    model_id: str = "model-real-id",
):
    provider = repository.create_provider(
        name="Test provider",
        api_format=api_format,
        base_url="https://models.example.test/v1",
        secret_source="keyring",
        secret_ref="provider:test",
    )
    model = repository.create_model(provider.id, model_id, "Model")
    secrets.set("provider:test", "test-secret")
    return model


@pytest.mark.parametrize(
    ("api_format", "expected_type"),
    [
        ("openai-compatible", ChatOpenAI),
        ("anthropic-compatible", ChatAnthropic),
    ],
)
def test_model_resolver_returns_standard_chat_model_without_exposing_secret(
    model_setup, api_format, expected_type
):
    repository, secrets = model_setup
    model_record = _seed_model(repository, secrets, api_format=api_format)
    resolver = ChatModelResolver(repository, {"keyring": secrets})

    resolved = resolver.resolve(
        role="answer_evaluation", provider_model_id=model_record.id
    )

    assert isinstance(resolved, BaseChatModel)
    assert isinstance(resolved, expected_type)
    assert "test-secret" not in repr(resolved)
    assert resolver.context_limit(model_record.id) == 128000


def test_model_resolver_maps_missing_secret_to_stable_error(model_setup):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository, secrets, api_format="openai-compatible"
    )
    secrets.delete("provider:test")
    resolver = ChatModelResolver(repository, {"keyring": secrets})

    with pytest.raises(ModelResolutionError) as raised:
        resolver.resolve(
            role="answer_evaluation", provider_model_id=model_record.id
        )

    assert raised.value.code is ProviderErrorCode.SECRET_MISSING


def test_model_resolver_rejects_disabled_model(model_setup):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository, secrets, api_format="openai-compatible"
    )
    repository.update_model(
        model_record.id,
        real_model_id=model_record.model_id,
        display_name=model_record.display_name,
        enabled=False,
        max_input_tokens=model_record.max_input_tokens,
    )
    resolver = ChatModelResolver(repository, {"keyring": secrets})

    with pytest.raises(ModelResolutionError) as raised:
        resolver.resolve(
            role="answer_evaluation", provider_model_id=model_record.id
        )

    assert raised.value.code is ProviderErrorCode.MODEL_NOT_FOUND


def test_agent_context_contains_only_safe_execution_identifiers():
    context = AgentContext(
        workspace_id="workspace-1",
        workspace_root=Path("/workspace"),
        session_id="session-1",
        run_id="run-1",
        allowed_tools=frozenset({"read_source"}),
        allowed_scopes=frozenset({"review.sources"}),
    )

    assert context.workspace_id == "workspace-1"
    assert not hasattr(context, "api_key")
    assert not hasattr(context, "provider")


def test_agent_factory_delegates_to_create_agent_without_invocation_wrapper(
    monkeypatch,
):
    captured = {}
    compiled = object()
    model = object()

    class StubResolver:
        def resolve(self, *, role, provider_model_id):
            captured["resolve"] = (role, provider_model_id)
            return model

    def fake_create_agent(**kwargs):
        captured["create"] = kwargs
        return compiled

    monkeypatch.setattr("app.agents.agent_factory.create_agent", fake_create_agent)
    factory = AgentFactory(StubResolver())
    spec = AgentSpec(
        role="question_generation",
        execution_name="curation_command_classifier",
        prompt=PromptSpec(
            id="test-answer-evaluation",
            version="1.0",
            system="Evaluate the answer",
        ),
        response_format=AnswerEvaluation,
    )

    result = factory.bind("question.curate").create(
        spec,
        component_id="curation_command_classifier",
        model_bindings={"question_generation": "provider-model-1"},
    )

    assert result is compiled
    assert captured["resolve"] == (
        "question_generation",
        "provider-model-1",
    )
    strategy = captured["create"].pop("response_format")
    assert isinstance(strategy, ToolStrategy)
    assert strategy.handle_errors is True
    middleware = captured["create"].pop("middleware")
    assert len(middleware) == 1
    assert isinstance(middleware[0], AgentTraceMiddleware)
    assert captured["create"] == {
        "model": model,
        "tools": (),
        "system_prompt": "Evaluate the answer",
        "context_schema": AgentContext,
        "name": "curation_command_classifier",
        "checkpointer": None,
    }


def test_agent_spec_requires_a_non_empty_concrete_execution_name():
    prompt = PromptSpec(id="test", version="1.0", system="Test")
    with pytest.raises(TypeError):
        AgentSpec(role="agent_chat", prompt=prompt)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="execution_name"):
        AgentSpec(role="agent_chat", execution_name="  ", prompt=prompt)


@pytest.mark.asyncio
async def test_agent_factory_returns_a_real_runnable_agent_graph():
    model = GenericFakeChatModel(
        messages=iter([AIMessage(content="Agent response")])
    )

    class StubResolver:
        def resolve(self, *, role, provider_model_id):
            assert (role, provider_model_id) == ("agent_chat", "model-1")
            return model

    agent = AgentFactory(StubResolver()).bind("review.discussion").create(
        AgentSpec(
            role="agent_chat",
            execution_name="review_discussion",
            prompt=PromptSpec(
                id="test-agent-chat", version="1.0", system="Be concise"
            ),
        ),
        component_id="review_discussion",
        model_bindings={"agent_chat": "model-1"},
    )
    context = AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="hello")]},
        context=context,
    )

    assert result["messages"][-1].text == "Agent response"


@pytest.mark.asyncio
async def test_agent_factory_can_disable_tool_strategy_schema_retries() -> None:
    class CountingStructuredFake(GenericFakeChatModel):
        calls: int = 0

        def bind_tools(self, _tools, **_kwargs):
            return self

        def _generate(self, *args, **kwargs) -> ChatResult:
            self.calls += 1
            return super()._generate(*args, **kwargs)

    model = CountingStructuredFake(messages=iter([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "AnswerEvaluation",
                "args": {"score": "good"},
                "id": "invalid-1",
                "type": "tool_call",
            }]),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "AnswerEvaluation",
                "args": {"score": "good"},
                "id": "invalid-2",
                "type": "tool_call",
            }]),
    ]))

    class StubResolver:
        def resolve(self, *, role, provider_model_id):
            return model

    agent = AgentFactory(StubResolver()).bind("question.curate").create(
        AgentSpec(
            role="question_generation",
            execution_name="question_discovery",
            prompt=PromptSpec(id="test", version="1.0", system="Discover"),
            response_format=AnswerEvaluation,
            structured_output_handle_errors=False,
        ),
        component_id="question_discovery",
        model_bindings={"question_generation": "model-1"},
    )
    context = AgentContext(
        workspace_id="w1",
        workspace_root=Path("/workspace"),
        session_id="s1",
        run_id="r1",
        allowed_tools=frozenset(),
        allowed_scopes=frozenset(),
    )

    with pytest.raises(StructuredOutputValidationError):
        await agent.ainvoke(
            {"messages": [HumanMessage(content="discover")]}, context=context
        )

    assert model.calls == 1


def test_agent_factory_uses_validated_session_model_override(monkeypatch):
    captured = {}

    class StubResolver:
        def resolve(self, *, role, provider_model_id, reasoning_effort="none"):
            captured["resolve"] = (
                role,
                provider_model_id,
                reasoning_effort,
            )
            return object()

    monkeypatch.setattr(
        "app.agents.agent_factory.create_agent", lambda **kwargs: kwargs
    )
    factory = AgentFactory(StubResolver())

    factory.bind("quality.evaluate").create(
        AgentSpec(
            role="answer_evaluation",
            execution_name="quality_evaluation_judge",
            prompt=PromptSpec(
                id="test-answer-evaluation",
                version="1.0",
                system="Evaluate",
            ),
        ),
        component_id="quality_evaluation_judge",
        model_bindings={"answer_evaluation": "workspace-default"},
        model_override=ModelOverride(
            provider_model_id="session-model",
            reasoning_effort="medium",
        ),
    )

    assert captured["resolve"] == (
        "answer_evaluation",
        "session-model",
        "medium",
    )


def test_model_resolver_maps_reasoning_effort_to_provider_options(
    model_setup, monkeypatch
):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository, secrets, api_format="openai-compatible"
    )
    captured = {}
    monkeypatch.setattr(
        "app.agents.agent_model_resolver.ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or GenericFakeChatModel(
            messages=iter([AIMessage(content="ok")])
        ),
    )

    ChatModelResolver(repository, {"keyring": secrets}).resolve(
        role="answer_evaluation",
        provider_model_id=model_record.id,
        reasoning_effort="high",
    )

    assert captured["reasoning_effort"] == "high"


def test_glm_question_generation_disables_default_thinking_without_global_budget(
    model_setup, monkeypatch
):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository,
        secrets,
        api_format="openai-compatible",
        model_id="GLM-5.2",
    )
    captured = {}
    monkeypatch.setattr(
        "app.agents.agent_model_resolver.ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or GenericFakeChatModel(
            messages=iter([AIMessage(content="ok")])
        ),
    )

    ChatModelResolver(repository, {"keyring": secrets}).resolve(
        role="question_generation",
        provider_model_id=model_record.id,
        reasoning_effort="none",
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "max_tokens" not in captured
    assert captured["request_timeout"] == 30
    assert "max_retries" not in captured
    assert "reasoning_effort" not in captured


def test_anthropic_alias_uses_observed_glm_capability_to_disable_thinking(
    model_setup, monkeypatch
):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository,
        secrets,
        api_format="anthropic-compatible",
        model_id="claude-opus-compatible-alias",
    )
    repository.update_model_status(
        model_record.id,
        connectivity_status="ok",
        latency_ms=10,
        error_code=None,
        resolved_model_id="glm-5.2",
        capability_profile={
            "probeVersion": 1,
            "reasoningControl": "glm_thinking_switch",
        },
    )
    captured = {}
    monkeypatch.setattr(
        "app.agents.agent_model_resolver.ChatAnthropic",
        lambda **kwargs: captured.update(kwargs) or GenericFakeChatModel(
            messages=iter([AIMessage(content="ok")])
        ),
    )

    ChatModelResolver(repository, {"keyring": secrets}).resolve(
        role="question_generation",
        provider_model_id=model_record.id,
        reasoning_effort="none",
    )

    assert captured["thinking"] == {"type": "disabled"}
    assert captured["model"] == "claude-opus-compatible-alias"


def test_glm_explicit_reasoning_enables_thinking(model_setup, monkeypatch):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository,
        secrets,
        api_format="openai-compatible",
        model_id="glm-5.2",
    )
    captured = {}
    monkeypatch.setattr(
        "app.agents.agent_model_resolver.ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or GenericFakeChatModel(
            messages=iter([AIMessage(content="ok")])
        ),
    )

    ChatModelResolver(repository, {"keyring": secrets}).resolve(
        role="answer_evaluation",
        provider_model_id=model_record.id,
        reasoning_effort="high",
    )

    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "high"
    assert "max_tokens" not in captured


def test_non_glm_openai_compatible_model_does_not_receive_glm_options(
    model_setup, monkeypatch
):
    repository, secrets = model_setup
    model_record = _seed_model(
        repository,
        secrets,
        api_format="openai-compatible",
        model_id="gpt-compatible-model",
    )
    captured = {}
    monkeypatch.setattr(
        "app.agents.agent_model_resolver.ChatOpenAI",
        lambda **kwargs: captured.update(kwargs) or GenericFakeChatModel(
            messages=iter([AIMessage(content="ok")])
        ),
    )

    ChatModelResolver(repository, {"keyring": secrets}).resolve(
        role="answer_evaluation",
        provider_model_id=model_record.id,
        reasoning_effort="none",
    )

    assert "extra_body" not in captured
    assert "reasoning_effort" not in captured
    assert "max_tokens" not in captured
    assert captured["request_timeout"] == 30
    assert "max_retries" not in captured
