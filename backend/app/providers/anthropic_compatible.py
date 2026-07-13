from __future__ import annotations

import time

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from app.providers.base import ERROR_MESSAGES, ProviderErrorCode, ProviderTestResult


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

    @staticmethod
    def _result(code: ProviderErrorCode, start: float) -> ProviderTestResult:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(
            status=code, latency_ms=latency_ms, message=ERROR_MESSAGES[code]
        )
