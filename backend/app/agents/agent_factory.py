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
from app.agents.agent_model_resolver import ChatModelResolver, ModelResolutionError
from app.agents.prompts.prompt_spec import PromptSpec
from app.providers.base import ProviderErrorCode


@dataclass(frozen=True, slots=True)
class AgentSpec:
    role: str
    prompt: PromptSpec
    execution_name: str | None = None
    tools: tuple[BaseTool, ...] = ()
    middleware: tuple[AgentMiddleware, ...] = ()
    response_format: type[BaseModel] | type[Any] | dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ModelOverride:
    provider_model_id: str
    reasoning_effort: Literal["none", "low", "medium", "high"] = "none"

    def __post_init__(self) -> None:
        if not self.provider_model_id.strip():
            raise ValueError("provider_model_id must not be empty")


class AgentFactory:
    def __init__(self, models: ChatModelResolver) -> None:
        self._models = models

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
            model = self._models.resolve(
                role=spec.role,
                provider_model_id=provider_model_id,
            )
        else:
            model = self._models.resolve(
                role=spec.role,
                provider_model_id=model_override.provider_model_id,
                reasoning_effort=model_override.reasoning_effort,
            )
        return create_agent(
            model=model,
            tools=spec.tools,
            system_prompt=spec.prompt.system,
            middleware=spec.middleware,
            response_format=(
                None
                if spec.response_format is None
                else ToolStrategy(spec.response_format)
            ),
            context_schema=AgentContext,
            name=spec.execution_name or spec.role,
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
