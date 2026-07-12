import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.providers.base import ProviderErrorCode
from app.providers.openai_compatible import OpenAICompatibleAdapter


class _StructuredResult(BaseModel):
    score: str


def _response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.test/v1/chat/completions")


def _patch_ainvoke(monkeypatch, *, exc=None, capture=None):
    async def fake_ainvoke(self, messages, **kwargs):
        if capture is not None:
            capture["base_url"] = self.openai_api_base
            capture["model"] = self.model
            capture["api_key"] = getattr(self, "openai_api_key", None)
        if exc is not None:
            raise exc
        return AIMessage(content="ok")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)


@pytest.mark.asyncio
async def test_openai_adapter_uses_configured_base_url_and_model(monkeypatch):
    capture = {}
    _patch_ainvoke(monkeypatch, capture=capture)
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert capture["base_url"] == "https://example.test/v1"
    assert capture["model"] == "gpt-x"
    assert result.status == ProviderErrorCode.OK


@pytest.mark.asyncio
async def test_openai_adapter_maps_401_to_auth_failed(monkeypatch):
    _patch_ainvoke(
        monkeypatch,
        exc=openai.AuthenticationError("invalid key", response=_response(401), body=None),
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.AUTH_FAILED


@pytest.mark.asyncio
async def test_openai_adapter_maps_404_to_model_not_found(monkeypatch):
    _patch_ainvoke(
        monkeypatch,
        exc=openai.NotFoundError("no such model", response=_response(404), body=None),
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.MODEL_NOT_FOUND


@pytest.mark.asyncio
async def test_openai_adapter_maps_429_to_rate_limited(monkeypatch):
    _patch_ainvoke(
        monkeypatch,
        exc=openai.RateLimitError("slow down", response=_response(429), body=None),
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.RATE_LIMITED


@pytest.mark.asyncio
async def test_openai_adapter_maps_timeout(monkeypatch):
    _patch_ainvoke(monkeypatch, exc=openai.APITimeoutError(request=_request()))
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.TIMEOUT


@pytest.mark.asyncio
async def test_openai_adapter_maps_connection_error_to_network(monkeypatch):
    _patch_ainvoke(
        monkeypatch, exc=openai.APIConnectionError(message="conn refused", request=_request())
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.NETWORK_ERROR


@pytest.mark.asyncio
async def test_openai_adapter_maps_other_status_to_protocol_error(monkeypatch):
    _patch_ainvoke(
        monkeypatch,
        exc=openai.InternalServerError("boom", response=_response(500), body=None),
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert result.status == ProviderErrorCode.PROTOCOL_ERROR


@pytest.mark.asyncio
async def test_openai_adapter_message_does_not_leak_api_key_or_backend_text(monkeypatch):
    _patch_ainvoke(
        monkeypatch,
        exc=openai.AuthenticationError(
            "leaked sk-secret and https://example.test/v1", response=_response(401), body=None
        ),
    )
    result = await OpenAICompatibleAdapter().test_connection(
        base_url="https://example.test/v1", model_id="gpt-x", api_key="sk-secret"
    )
    assert "sk-secret" not in result.message
    assert "leaked" not in result.message


@pytest.mark.asyncio
async def test_structured_invocation_uses_function_calling_for_compatibility(
    monkeypatch,
):
    capture = {}

    class FakeRunnable:
        async def ainvoke(self, messages):
            capture["messages"] = messages
            return _StructuredResult(score="partial")

    def fake_with_structured_output(self, schema, **kwargs):
        capture["schema"] = schema
        capture["method"] = kwargs.get("method")
        return FakeRunnable()

    monkeypatch.setattr(
        ChatOpenAI, "with_structured_output", fake_with_structured_output
    )

    result = await OpenAICompatibleAdapter().invoke_structured(
        base_url="https://example.test/v1",
        model_id="gpt-x",
        api_key="sk-secret",
        schema=_StructuredResult,
        messages=[{"role": "user", "content": "answer"}],
    )

    assert result == _StructuredResult(score="partial")
    assert capture["schema"] is _StructuredResult
    assert capture["method"] == "function_calling"
