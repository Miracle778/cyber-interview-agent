from collections.abc import AsyncIterator

from cyber_interview.config import ProviderConfig
from cyber_interview.harness.model_gateway import Message, ModelChunk


class OpenAIAdapter:
    """OpenAI Responses API stream."""

    def __init__(self, config: ProviderConfig, model: str):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self._model = model

    async def stream(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ModelChunk]:
        stream = await self._client.responses.create(
            model=model,
            input=[{"role": message.role, "content": message.content} for message in messages],
            stream=True,
        )
        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                yield ModelChunk(type="delta", text=event.delta)
            elif event_type == "response.completed":
                yield ModelChunk(type="done", finish_reason="stop", usage=None)


class AnthropicAdapter:
    """Anthropic messages stream."""

    def __init__(self, config: ProviderConfig, model: str):
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=config.api_key, base_url=config.base_url)
        self._model = model

    async def stream(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ModelChunk]:
        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens or 1024,
            messages=[{"role": message.role, "content": message.content} for message in messages],
        ) as stream:
            async for text in stream.text_stream:
                yield ModelChunk(type="delta", text=text)
            final = await stream.get_final_message()
            yield ModelChunk(
                type="done",
                finish_reason=final.stop_reason,
                usage={"in": final.usage.input_tokens, "out": final.usage.output_tokens},
            )
