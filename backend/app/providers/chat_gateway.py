from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode


SchemaT = TypeVar("SchemaT", bound=BaseModel)
ValueT = TypeVar("ValueT")


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ProviderModelResult(Generic[ValueT]):
    value: ValueT
    usage: ProviderUsage | None


@dataclass(frozen=True, slots=True)
class ProviderStreamChunk:
    text: str
    usage: ProviderUsage | None = None


def usage_from_message(message: Any) -> ProviderUsage | None:
    metadata = getattr(message, "usage_metadata", None)
    if not isinstance(metadata, dict):
        return None
    return ProviderUsage(
        input_tokens=int(metadata.get("input_tokens", 0)),
        output_tokens=int(metadata.get("output_tokens", 0)),
    )


@dataclass(frozen=True, slots=True)
class ResolvedModelBinding:
    role: str
    provider_id: str
    provider_model_id: str
    api_format: str
    base_url: str
    model_id: str
    api_key: str = field(repr=False)


class ProviderInvocationError(RuntimeError):
    """Sanitized provider failure safe for runtime records and events."""

    def __init__(
        self, code: ProviderErrorCode, _provider_detail: str | None = None
    ) -> None:
        self.code = ProviderErrorCode(code)
        message = ERROR_MESSAGES[self.code]
        if self.code is ProviderErrorCode.PROTOCOL_ERROR:
            message = "模型返回格式无效"
        super().__init__(message)


class ChatProviderAdapter(Protocol):
    async def invoke_structured(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        schema: type[BaseModel],
        messages: Sequence[Any],
    ) -> ProviderModelResult[object]: ...

    def stream_text(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        messages: Sequence[Any],
    ) -> AsyncIterator[ProviderStreamChunk]: ...


class ChatModelGateway:
    def __init__(self, adapters: Mapping[str, ChatProviderAdapter]) -> None:
        self._adapters = dict(adapters)

    def _adapter(self, binding: ResolvedModelBinding) -> ChatProviderAdapter:
        try:
            return self._adapters[binding.api_format]
        except KeyError as error:
            raise ProviderInvocationError(
                ProviderErrorCode.PROTOCOL_ERROR
            ) from error

    async def invoke_structured(
        self,
        *,
        binding: ResolvedModelBinding,
        schema: type[SchemaT],
        messages: Sequence[Any],
    ) -> ProviderModelResult[SchemaT]:
        raw = await self._adapter(binding).invoke_structured(
            base_url=binding.base_url,
            model_id=binding.model_id,
            api_key=binding.api_key,
            schema=schema,
            messages=messages,
        )
        envelope = raw if isinstance(raw, ProviderModelResult) else ProviderModelResult(raw, None)
        try:
            value = envelope.value if isinstance(envelope.value, schema) else schema.model_validate(envelope.value)
            return ProviderModelResult(value=value, usage=envelope.usage)
        except ValidationError as error:
            raise ProviderInvocationError(
                ProviderErrorCode.PROTOCOL_ERROR
            ) from error

    async def stream_text(
        self,
        *,
        binding: ResolvedModelBinding,
        messages: Sequence[Any],
    ) -> AsyncIterator[ProviderStreamChunk]:
        async for chunk in self._adapter(binding).stream_text(
            base_url=binding.base_url,
            model_id=binding.model_id,
            api_key=binding.api_key,
            messages=messages,
        ):
            envelope = chunk if isinstance(chunk, ProviderStreamChunk) else ProviderStreamChunk(str(chunk))
            if envelope.text or envelope.usage is not None:
                yield envelope
