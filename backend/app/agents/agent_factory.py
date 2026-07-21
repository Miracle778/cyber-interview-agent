from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.agents.context import AgentContext
from app.agents.agent_model_resolver import (
    ChatModelResolver,
    ModelInvocationPolicy,
    ModelResolutionError,
)
from app.agents.prompts.prompt_spec import PromptSpec
from app.diagnostics.agent_trace import AgentTraceWriter
from app.middleware.agent_trace_middleware import AgentTraceMiddleware
from app.providers.base import ProviderErrorCode


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


class AgentFactory:
    def __init__(
        self,
        models: ChatModelResolver,
        *,
        trace_writer: AgentTraceWriter | None = None,
    ) -> None:
        self._models = models
        self._trace_writer = trace_writer or AgentTraceWriter()

    @property
    def trace_writer(self) -> AgentTraceWriter:
        return self._trace_writer

    def create(
        self,
        spec: AgentSpec,
        *,
        model_bindings: Mapping[str, str],
        model_override: ModelOverride | None = None,
        checkpointer=None,
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
