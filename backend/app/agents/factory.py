from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.agents.context import AgentContext
from app.agents.model_resolver import ChatModelResolver, ModelResolutionError
from app.providers.base import ProviderErrorCode


@dataclass(frozen=True, slots=True)
class AgentSpec:
    role: str
    system_prompt: str
    tools: tuple[BaseTool, ...] = ()
    middleware: tuple[AgentMiddleware, ...] = ()
    response_format: type[BaseModel] | type[Any] | dict[str, Any] | None = None


class AgentFactory:
    def __init__(self, models: ChatModelResolver) -> None:
        self._models = models

    def create(
        self,
        spec: AgentSpec,
        *,
        model_bindings: Mapping[str, str],
    ):
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
        return create_agent(
            model=model,
            tools=spec.tools,
            system_prompt=spec.system_prompt,
            middleware=spec.middleware,
            response_format=spec.response_format,
            context_schema=AgentContext,
            name=spec.role,
        )
