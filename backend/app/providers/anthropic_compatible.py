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
            response = await chat.ainvoke([HumanMessage(content="ping")])
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
        return self._result(
            ProviderErrorCode.OK,
            start,
            resolved_model_id=_resolved_model_id(response),
            capabilities=_observed_capabilities(response),
        )

    @staticmethod
    def _result(
        code: ProviderErrorCode,
        start: float,
        *,
        resolved_model_id: str | None = None,
        capabilities: dict[str, object] | None = None,
    ) -> ProviderTestResult:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(
            status=code,
            latency_ms=latency_ms,
            message=ERROR_MESSAGES[code],
            resolved_model_id=resolved_model_id,
            capabilities=capabilities or {},
        )


def _resolved_model_id(response: object) -> str | None:
    metadata = getattr(response, "response_metadata", None)
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("model_name") or metadata.get("model")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _observed_capabilities(response: object) -> dict[str, object]:
    resolved = _resolved_model_id(response)
    normalized = (resolved or "").casefold().rsplit("/", 1)[-1]
    content = getattr(response, "content", None)
    observed_thinking = bool(
        isinstance(content, list)
        and any(
            isinstance(block, dict) and block.get("type") == "thinking"
            for block in content
        )
    )
    return {
        "probeVersion": 1,
        "reasoningControl": (
            "glm_thinking_switch" if normalized.startswith("glm-") else "unknown"
        ),
        "observedThinking": observed_thinking,
        "structuredOutput": "unknown",
    }
