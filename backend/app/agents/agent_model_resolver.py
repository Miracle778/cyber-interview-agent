from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode
from app.repositories.provider_repository import ProviderRepository
from app.services.secrets import SecretNotFoundError, SecretStore


_GLM_THINKING_MODEL_PREFIXES = (
    "glm-4.5",
    "glm-4.6",
    "glm-4.7",
    "glm-5",
)


@dataclass(frozen=True, slots=True)
class ModelInvocationPolicy:
    max_output_tokens: int
    request_timeout_seconds: int
    max_retries: int = 0

    def __post_init__(self) -> None:
        if self.max_output_tokens <= 0 or self.request_timeout_seconds <= 0:
            raise ValueError("model invocation limits must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")


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
        invocation_policy: ModelInvocationPolicy | None = None,
    ) -> BaseChatModel:
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
            normalized_model_id = model.model_id.lower().rsplit("/", 1)[-1]
            if normalized_model_id.startswith(_GLM_THINKING_MODEL_PREFIXES):
                options["extra_body"] = {
                    "thinking": {
                        "type": (
                            "disabled"
                            if reasoning_effort == "none"
                            else "enabled"
                        )
                    }
                }
            if reasoning_effort != "none":
                options["reasoning_effort"] = reasoning_effort
            if invocation_policy is not None:
                options["max_tokens"] = invocation_policy.max_output_tokens
                options["max_retries"] = invocation_policy.max_retries
            return ChatOpenAI(
                base_url=provider.base_url,
                model=model.model_id,
                api_key=api_key,
                request_timeout=(
                    invocation_policy.request_timeout_seconds
                    if invocation_policy is not None
                    else 30
                ),
                stream_usage=True,
                **options,
            )
        if provider.api_format == "anthropic-compatible":
            budgets = {"low": 1024, "medium": 4096, "high": 8192}
            options = {}
            visible_output_tokens = (
                invocation_policy.max_output_tokens
                if invocation_policy is not None
                else 8192
            )
            max_tokens = visible_output_tokens
            if reasoning_effort != "none":
                budget = budgets[reasoning_effort]
                options["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
                max_tokens = budget + visible_output_tokens
            if invocation_policy is not None:
                options["max_retries"] = invocation_policy.max_retries
            return ChatAnthropic(
                base_url=provider.base_url,
                model=model.model_id,
                api_key=api_key,
                default_request_timeout=(
                    invocation_policy.request_timeout_seconds
                    if invocation_policy is not None
                    else 30
                ),
                max_tokens=max_tokens,
                **options,
            )
        raise ModelResolutionError(ProviderErrorCode.PROTOCOL_ERROR)

    def context_limit(self, provider_model_id: str) -> int:
        model = self._providers.get_model(provider_model_id)
        if model is None or not model.enabled:
            raise ModelResolutionError(ProviderErrorCode.MODEL_NOT_FOUND)
        return model.max_input_tokens
