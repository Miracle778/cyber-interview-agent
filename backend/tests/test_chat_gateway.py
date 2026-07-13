from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel

from app.providers.base import ProviderErrorCode
from app.providers.chat_gateway import (
    ChatModelGateway,
    ProviderInvocationError,
    ProviderModelResult,
    ProviderStreamChunk,
    ProviderUsage,
    ResolvedModelBinding,
)


class Evaluation(BaseModel):
    score: str
    evidence: str


class FakeChatAdapter:
    def __init__(self) -> None:
        self.structured_result: object = ProviderModelResult(
            value={"score": "partial", "evidence": "只覆盖了原子性"},
            usage=ProviderUsage(50, 10),
        )
        self.text_chunks = [
            ProviderStreamChunk("报"),
            ProviderStreamChunk("告", ProviderUsage(40, 8)),
        ]
        self.error: ProviderInvocationError | None = None
        self.last_call: dict[str, object] | None = None

    async def invoke_structured(self, **kwargs: object) -> object:
        self.last_call = kwargs
        if self.error is not None:
            raise self.error
        return self.structured_result

    async def stream_text(self, **kwargs: object) -> AsyncIterator[str]:
        self.last_call = kwargs
        if self.error is not None:
            raise self.error
        for chunk in self.text_chunks:
            yield chunk


@pytest.fixture
def binding() -> ResolvedModelBinding:
    return ResolvedModelBinding(
        role="answer_evaluation",
        provider_id="provider-1",
        provider_model_id="model-pk-1",
        api_format="openai-compatible",
        base_url="https://example.test/v1",
        model_id="gpt-test",
        api_key="top-secret",
    )


@pytest.mark.asyncio
async def test_structured_invocation_uses_snapshot_model(binding) -> None:
    adapter = FakeChatAdapter()
    gateway = ChatModelGateway({"openai-compatible": adapter})

    result = await gateway.invoke_structured(
        binding=binding,
        schema=Evaluation,
        messages=[{"role": "user", "content": "answer"}],
    )

    assert result.value == Evaluation(score="partial", evidence="只覆盖了原子性")
    assert result.usage == ProviderUsage(50, 10)
    assert result.usage.total_tokens == 60
    assert adapter.last_call == {
        "base_url": binding.base_url,
        "model_id": binding.model_id,
        "api_key": binding.api_key,
        "schema": Evaluation,
        "messages": [{"role": "user", "content": "answer"}],
    }


@pytest.mark.asyncio
async def test_stream_text_emits_only_non_empty_text_chunks(binding) -> None:
    adapter = FakeChatAdapter()
    adapter.text_chunks = [
        ProviderStreamChunk("报"),
        ProviderStreamChunk(""),
        ProviderStreamChunk("告", ProviderUsage(40, 8)),
    ]
    gateway = ChatModelGateway({"openai-compatible": adapter})

    chunks = [
        chunk
        async for chunk in gateway.stream_text(
            binding=binding,
            messages=[{"role": "user", "content": "report"}],
        )
    ]

    assert [chunk.text for chunk in chunks] == ["报", "告"]
    assert [chunk.usage for chunk in chunks if chunk.usage] == [ProviderUsage(40, 8)]


@pytest.mark.asyncio
async def test_invalid_structured_output_maps_to_stable_protocol_error(binding) -> None:
    adapter = FakeChatAdapter()
    adapter.structured_result = ProviderModelResult(
        value={"provider_body": "must not escape"}, usage=None
    )
    gateway = ChatModelGateway({"openai-compatible": adapter})

    with pytest.raises(ProviderInvocationError) as caught:
        await gateway.invoke_structured(
            binding=binding,
            schema=Evaluation,
            messages=[],
        )

    assert caught.value.code is ProviderErrorCode.PROTOCOL_ERROR
    assert str(caught.value) == "模型返回格式无效"
    assert "provider_body" not in str(caught.value)


@pytest.mark.parametrize(
    "code",
    [
        ProviderErrorCode.SECRET_MISSING,
        ProviderErrorCode.AUTH_FAILED,
        ProviderErrorCode.MODEL_NOT_FOUND,
        ProviderErrorCode.RATE_LIMITED,
        ProviderErrorCode.TIMEOUT,
    ],
)
@pytest.mark.asyncio
async def test_provider_errors_keep_stable_code_without_raw_body(
    binding, code
) -> None:
    adapter = FakeChatAdapter()
    adapter.error = ProviderInvocationError(code, "raw provider body")
    gateway = ChatModelGateway({"openai-compatible": adapter})

    with pytest.raises(ProviderInvocationError) as caught:
        await gateway.invoke_structured(
            binding=binding,
            schema=Evaluation,
            messages=[],
        )

    assert caught.value.code is code
    assert "raw provider body" not in str(caught.value)
    assert binding.api_key not in repr(binding)
