from __future__ import annotations

import time

import openai
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode, ProviderTestResult


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

    @staticmethod
    def _result(code: ProviderErrorCode, start: float) -> ProviderTestResult:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(
            status=code, latency_ms=latency_ms, message=ERROR_MESSAGES[code]
        )
