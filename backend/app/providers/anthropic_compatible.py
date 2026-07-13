from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode, ProviderTestResult
from app.providers.chat_gateway import (
    ProviderInvocationError,
    ProviderModelResult,
    ProviderStreamChunk,
    usage_from_message,
)


class AnthropicCompatibleAdapter:
    """ProviderAdapter for Anthropic-compatible message APIs."""

    async def test_connection(
        self, *, base_url: str, model_id: str, api_key: str
    ) -> ProviderTestResult:
        start = time.monotonic()
        try:
            chat = ChatAnthropic(
                base_url=base_url,
                model=model_id,
                api_key=api_key,
                default_request_timeout=5,
                max_tokens=1,
            )
            await chat.ainvoke([HumanMessage(content="ping")])
        except anthropic.APITimeoutError:
            return self._result(ProviderErrorCode.TIMEOUT, start)
        except anthropic.AuthenticationError:
            return self._result(ProviderErrorCode.AUTH_FAILED, start)
        except anthropic.NotFoundError:
            return self._result(ProviderErrorCode.MODEL_NOT_FOUND, start)
        except anthropic.RateLimitError:
            return self._result(ProviderErrorCode.RATE_LIMITED, start)
        except anthropic.APIConnectionError:
            return self._result(ProviderErrorCode.NETWORK_ERROR, start)
        except anthropic.APIStatusError:
            return self._result(ProviderErrorCode.PROTOCOL_ERROR, start)
        except Exception:
            return self._result(ProviderErrorCode.PROTOCOL_ERROR, start)
        return self._result(ProviderErrorCode.OK, start)

    async def invoke_structured(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        schema: type,
        messages: Sequence[Any],
    ) -> ProviderModelResult[object]:
        try:
            chat = self._chat(base_url, model_id, api_key)
            envelope = await chat.with_structured_output(
                schema, include_raw=True
            ).ainvoke(messages)
            return ProviderModelResult(
                value=envelope["parsed"], usage=usage_from_message(envelope["raw"])
            )
        except Exception as error:
            raise self._invocation_error(error) from error

    async def stream_text(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        messages: Sequence[Any],
    ) -> AsyncIterator[ProviderStreamChunk]:
        try:
            chat = self._chat(base_url, model_id, api_key)
            async for chunk in chat.astream(messages):
                content = chunk.content
                text = content if isinstance(content, str) else ""
                usage = usage_from_message(chunk)
                if text or usage is not None:
                    yield ProviderStreamChunk(text=text, usage=usage)
        except Exception as error:
            raise self._invocation_error(error) from error

    @staticmethod
    def _chat(base_url: str, model_id: str, api_key: str) -> ChatAnthropic:
        return ChatAnthropic(
            base_url=base_url,
            model=model_id,
            api_key=api_key,
            default_request_timeout=30,
            max_tokens=2048,
        )

    @staticmethod
    def _invocation_error(error: Exception) -> ProviderInvocationError:
        if isinstance(error, anthropic.APITimeoutError):
            code = ProviderErrorCode.TIMEOUT
        elif isinstance(error, anthropic.AuthenticationError):
            code = ProviderErrorCode.AUTH_FAILED
        elif isinstance(error, anthropic.NotFoundError):
            code = ProviderErrorCode.MODEL_NOT_FOUND
        elif isinstance(error, anthropic.RateLimitError):
            code = ProviderErrorCode.RATE_LIMITED
        elif isinstance(error, anthropic.APIConnectionError):
            code = ProviderErrorCode.NETWORK_ERROR
        else:
            code = ProviderErrorCode.PROTOCOL_ERROR
        return ProviderInvocationError(code)

    @staticmethod
    def _result(code: ProviderErrorCode, start: float) -> ProviderTestResult:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(
            status=code, latency_ms=latency_ms, message=ERROR_MESSAGES[code]
        )
