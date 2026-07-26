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
            response = await chat.ainvoke([HumanMessage(content="ping")])
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
