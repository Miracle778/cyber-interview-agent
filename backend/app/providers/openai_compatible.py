from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import openai
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode, ProviderTestResult
from app.providers.chat_gateway import ProviderInvocationError


class OpenAICompatibleAdapter:
    """ProviderAdapter for OpenAI-compatible chat completion APIs."""

    async def test_connection(
        self, *, base_url: str, model_id: str, api_key: str
    ) -> ProviderTestResult:
        start = time.monotonic()
        try:
            chat = ChatOpenAI(
                base_url=base_url,
                model=model_id,
                api_key=api_key,
                request_timeout=5,
                max_tokens=1,
            )
            await chat.ainvoke([HumanMessage(content="ping")])
        except openai.APITimeoutError:
            return self._result(ProviderErrorCode.TIMEOUT, start)
        except openai.AuthenticationError:
            return self._result(ProviderErrorCode.AUTH_FAILED, start)
        except openai.NotFoundError:
            return self._result(ProviderErrorCode.MODEL_NOT_FOUND, start)
        except openai.RateLimitError:
            return self._result(ProviderErrorCode.RATE_LIMITED, start)
        except openai.APIConnectionError:
            return self._result(ProviderErrorCode.NETWORK_ERROR, start)
        except openai.APIStatusError:
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
    ) -> object:
        try:
            chat = self._chat(base_url, model_id, api_key)
            return await chat.with_structured_output(
                schema, method="function_calling"
            ).ainvoke(messages)
        except Exception as error:
            raise self._invocation_error(error) from error

    async def stream_text(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str,
        messages: Sequence[Any],
    ) -> AsyncIterator[str]:
        try:
            chat = self._chat(base_url, model_id, api_key)
            async for chunk in chat.astream(messages):
                content = chunk.content
                if isinstance(content, str) and content:
                    yield content
        except Exception as error:
            raise self._invocation_error(error) from error

    @staticmethod
    def _chat(base_url: str, model_id: str, api_key: str) -> ChatOpenAI:
        return ChatOpenAI(
            base_url=base_url,
            model=model_id,
            api_key=api_key,
            request_timeout=30,
            max_tokens=2048,
        )

    @staticmethod
    def _invocation_error(error: Exception) -> ProviderInvocationError:
        if isinstance(error, openai.APITimeoutError):
            code = ProviderErrorCode.TIMEOUT
        elif isinstance(error, openai.AuthenticationError):
            code = ProviderErrorCode.AUTH_FAILED
        elif isinstance(error, openai.NotFoundError):
            code = ProviderErrorCode.MODEL_NOT_FOUND
        elif isinstance(error, openai.RateLimitError):
            code = ProviderErrorCode.RATE_LIMITED
        elif isinstance(error, openai.APIConnectionError):
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
