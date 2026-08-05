from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.agents.context import AgentContext
from app.agents.definition_registry import (
    AgentDefinition,
    AgentDefinitionRegistry,
    AGENT_DEFINITION_REGISTRY,
)
from app.agents.agent_model_resolver import (
    ChatModelResolver,
    ModelInvocationPolicy,
    ModelResolutionError,
)
from app.agents.prompts.prompt_spec import PromptSpec
from app.diagnostics.agent_trace import AgentTraceWriter
from app.middleware.agent_trace_middleware import AgentTraceMiddleware
from app.middleware.tool_policy_middleware import ToolPolicyMiddleware
from app.providers.base import ProviderErrorCode


_MODEL_RESOLVER_MODULE = "app.agents.agent_model_resolver"
_MODEL_RESOLVER_IMPORT_ALLOWLIST = frozenset(
    {"agents/agent_factory.py", "main.py"}
)


def find_model_resolver_import_violations(
    app_root: Path,
    *,
    allowed_relative_paths: frozenset[str] = _MODEL_RESOLVER_IMPORT_ALLOWLIST,
) -> tuple[str, ...]:
    """Return product modules that can bypass the registered Agent boundary."""

    violations: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(app_root).as_posix()
        if relative in allowed_relative_paths:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bypass = any(
            (
                isinstance(node, ast.ImportFrom)
                and node.module == _MODEL_RESOLVER_MODULE
                and any(alias.name == "ChatModelResolver" for alias in node.names)
            )
            or (
                isinstance(node, ast.Import)
                and any(
                    alias.name == _MODEL_RESOLVER_MODULE for alias in node.names
                )
            )
            for node in ast.walk(tree)
        )
        if bypass:
            violations.append(relative)
    return tuple(violations)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    role: str
    execution_name: str
    prompt: PromptSpec
    tools: tuple[BaseTool, ...] = ()
    middleware: tuple[AgentMiddleware, ...] = ()
    response_format: type[BaseModel] | type[Any] | dict[str, Any] | None = None
    structured_output_handle_errors: bool = True
    invocation_policy: ModelInvocationPolicy | None = None

    def __post_init__(self) -> None:
        if not self.execution_name.strip():
            raise ValueError("execution_name must not be empty")


@dataclass(frozen=True, slots=True)
class ModelOverride:
    provider_model_id: str
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"

    def __post_init__(self) -> None:
        if not self.provider_model_id.strip():
            raise ValueError("provider_model_id must not be empty")


class AgentContractError(ValueError):
    """A registered Agent attempted to exceed its control-plane definition."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class RegisteredAgentFactory:
    """Definition-bound model and Tool boundary for one top-level Agent."""

    def __init__(self, factory: "AgentFactory", definition: AgentDefinition) -> None:
        self._factory = factory
        self.definition = definition

    @property
    def trace_writer(self) -> AgentTraceWriter:
        return self._factory.trace_writer

    def create(
        self,
        spec: AgentSpec,
        *,
        component_id: str,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
        checkpointer=None,
    ):
        self._require_component(component_id)
        self._require_role(spec.role)
        undeclared_tools = sorted(
            tool.name
            for tool in spec.tools
            if tool.name not in self.definition.allowed_tools
        )
        if undeclared_tools:
            raise AgentContractError(
                "tool_not_allowed",
                f"{self.definition.agent_id}: {','.join(undeclared_tools)}",
            )
        return self._factory._create_registered(
            spec,
            definition=self.definition,
            component_id=component_id,
            model_bindings=model_bindings,
            model_override=model_override,
            checkpointer=checkpointer,
        )

    def create_tool_policy(
        self,
        *,
        audit,
        required_scopes: Mapping[str, str],
        publish_event=None,
    ) -> ToolPolicyMiddleware:
        undeclared_tools = sorted(
            name
            for name in required_scopes
            if name not in self.definition.allowed_tools
        )
        if undeclared_tools:
            raise AgentContractError(
                "tool_not_allowed",
                f"{self.definition.agent_id}: {','.join(undeclared_tools)}",
            )
        undeclared_scopes = sorted(
            set(required_scopes.values()) - set(self.definition.allowed_scopes)
        )
        if undeclared_scopes:
            raise AgentContractError(
                "scope_not_allowed",
                f"{self.definition.agent_id}: {','.join(undeclared_scopes)}",
            )
        return ToolPolicyMiddleware(
            audit=audit,
            required_scopes=dict(required_scopes),
            publish_event=publish_event,
        )

    def resolve_model(
        self,
        role: str,
        *,
        component_id: str,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ):
        self._require_component(component_id)
        self._require_role(role)
        return self._factory._resolve_model(
            role,
            model_bindings=model_bindings,
            model_override=model_override,
        )

    def resolve_context_limit(
        self,
        role: str,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ) -> int:
        self._require_role(role)
        return self._factory._resolve_context_limit(
            role,
            model_bindings=model_bindings,
            model_override=model_override,
        )

    def _require_component(self, component_id: str) -> None:
        if component_id not in self.definition.child_components:
            raise AgentContractError(
                "component_not_allowed",
                f"{self.definition.agent_id}: {component_id}",
            )

    def _require_role(self, role: str) -> None:
        if role not in self.definition.model_roles:
            raise AgentContractError(
                "model_role_not_allowed",
                f"{self.definition.agent_id}: {role}",
            )


class AgentFactory:
    def __init__(
        self,
        models: ChatModelResolver,
        *,
        trace_writer: AgentTraceWriter | None = None,
        definitions: AgentDefinitionRegistry = AGENT_DEFINITION_REGISTRY,
    ) -> None:
        self._models = models
        self._trace_writer = trace_writer or AgentTraceWriter()
        self._definitions = definitions

    @property
    def trace_writer(self) -> AgentTraceWriter:
        return self._trace_writer

    def bind(self, agent_id: str) -> RegisteredAgentFactory:
        return RegisteredAgentFactory(self, self._definitions.require(agent_id))

    def _create_registered(
        self,
        spec: AgentSpec,
        *,
        definition: AgentDefinition,
        component_id: str,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
        checkpointer=None,
    ):
        return self._create(
            spec,
            model_bindings=model_bindings,
            model_override=model_override,
            checkpointer=checkpointer,
            definition=definition,
            component_id=component_id,
        )

    def create(
        self,
        spec: AgentSpec,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
        checkpointer=None,
    ):
        raise AgentContractError(
            "agent_definition_required",
            "call AgentFactory.bind(agent_id) before creating a component",
        )

    def _create(
        self,
        spec: AgentSpec,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
        checkpointer=None,
        definition: AgentDefinition | None = None,
        component_id: str | None = None,
    ):
        if model_override is None:
            try:
                provider_model_id = model_bindings[spec.role]
            except KeyError as error:
                raise ModelResolutionError(
                    ProviderErrorCode.MODEL_NOT_FOUND
                ) from error
            resolve_kwargs = {
                "role": spec.role,
                "provider_model_id": provider_model_id,
            }
            if spec.invocation_policy is not None:
                resolve_kwargs["invocation_policy"] = spec.invocation_policy
            model = self._models.resolve(**resolve_kwargs)
        else:
            provider_model_id = model_override.provider_model_id
            resolve_kwargs = {
                "role": spec.role,
                "provider_model_id": model_override.provider_model_id,
                "reasoning_effort": model_override.reasoning_effort,
            }
            if spec.invocation_policy is not None:
                resolve_kwargs["invocation_policy"] = spec.invocation_policy
            model = self._models.resolve(
                **resolve_kwargs,
            )
        trace_middleware = AgentTraceMiddleware(
            self._trace_writer,
            agent_role=spec.role,
            agent_name=spec.execution_name,
            provider_model_id=provider_model_id,
            agent_id=None if definition is None else definition.agent_id,
            agent_definition_version=(
                None if definition is None else definition.definition_version
            ),
            component_id=component_id,
        )
        return create_agent(
            model=model,
            tools=spec.tools,
            system_prompt=spec.prompt.system,
            middleware=(trace_middleware, *spec.middleware),
            response_format=(
                None
                if spec.response_format is None
                else ToolStrategy(
                    spec.response_format,
                    handle_errors=spec.structured_output_handle_errors,
                )
            ),
            context_schema=AgentContext,
            name=spec.execution_name,
            checkpointer=checkpointer,
        )

    def resolve_model(
        self,
        role: str,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ):
        raise AgentContractError(
            "agent_definition_required",
            "call AgentFactory.bind(agent_id) before resolving a model",
        )

    def _resolve_model(
        self,
        role: str,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ):
        if model_override is not None:
            return self._models.resolve(
                role=role,
                provider_model_id=model_override.provider_model_id,
                reasoning_effort=model_override.reasoning_effort,
            )
        try:
            provider_model_id = model_bindings[role]
        except KeyError as error:
            raise ModelResolutionError(
                ProviderErrorCode.MODEL_NOT_FOUND
            ) from error
        return self._models.resolve(
            role=role, provider_model_id=provider_model_id
        )

    def resolve_context_limit(
        self,
        role: str,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ) -> int:
        raise AgentContractError(
            "agent_definition_required",
            "call AgentFactory.bind(agent_id) before reading model policy",
        )

    def _resolve_context_limit(
        self,
        role: str,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
    ) -> int:
        if model_override is not None:
            provider_model_id = model_override.provider_model_id
        else:
            try:
                provider_model_id = model_bindings[role]
            except KeyError as error:
                raise ModelResolutionError(
                    ProviderErrorCode.MODEL_NOT_FOUND
                ) from error
        return self._models.context_limit(provider_model_id)
