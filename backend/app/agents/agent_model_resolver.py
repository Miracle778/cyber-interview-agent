from __future__ import annotations

from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode
from app.repositories.provider_repository import ProviderRepository
from app.services.secrets import SecretNotFoundError, SecretStore


class ModelResolutionError(RuntimeError):
    def __init__(self, code: ProviderErrorCode) -> None:
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


class ChatModelResolver:
    def __init__(
        self,
        providers: ProviderRepository,
        secret_stores: dict[str, SecretStore],
    ) -> None:
        self._providers = providers
        self._secret_stores = secret_stores

    def resolve(
        self,
        *,
        role: str,
        provider_model_id: str,
        reasoning_effort: Literal["none", "low", "medium", "high"] = "none",
    ) -> BaseChatModel:
        del role
        model = self._providers.get_model(provider_model_id)
        if model is None or not model.enabled:
            raise ModelResolutionError(ProviderErrorCode.MODEL_NOT_FOUND)
        provider = self._providers.get_provider(model.provider_id)
        if provider is None or not provider.enabled:
            raise ModelResolutionError(ProviderErrorCode.MODEL_NOT_FOUND)
        try:
            store = self._secret_stores[provider.secret_source]
            api_key = store.get(provider.secret_ref)
        except (KeyError, SecretNotFoundError) as error:
            raise ModelResolutionError(
                ProviderErrorCode.SECRET_MISSING
            ) from error

        if provider.api_format == "openai-compatible":
            options = {}
            if reasoning_effort != "none":
                options["reasoning_effort"] = reasoning_effort
            return ChatOpenAI(
                base_url=provider.base_url,
                model=model.model_id,
                api_key=api_key,
                request_timeout=30,
                max_tokens=2048,
                stream_usage=True,
                **options,
            )
        if provider.api_format == "anthropic-compatible":
            budgets = {"low": 1024, "medium": 4096, "high": 8192}
            options = {}
            max_tokens = 2048
            if reasoning_effort != "none":
                budget = budgets[reasoning_effort]
                options["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
                max_tokens = budget + 2048
            return ChatAnthropic(
                base_url=provider.base_url,
                model=model.model_id,
                api_key=api_key,
                default_request_timeout=30,
                max_tokens=max_tokens,
                **options,
            )
        raise ModelResolutionError(ProviderErrorCode.PROTOCOL_ERROR)

    def context_limit(self, provider_model_id: str) -> int:
        model = self._providers.get_model(provider_model_id)
        if model is None or not model.enabled:
            raise ModelResolutionError(ProviderErrorCode.MODEL_NOT_FOUND)
        return model.max_input_tokens
