from collections.abc import AsyncIterator

from cyber_interview.harness.model_gateway import Message, ModelChunk


class FakeModelGateway:
    """Test ModelGateway that yields predefined chunks."""

    def __init__(self, chunks: list[ModelChunk], fail_on_call: int | None = None):
        self._chunks = chunks
        self._fail_on_call = fail_on_call
        self.call_count = 0

    async def stream(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ModelChunk]:
        self.call_count += 1
        if self._fail_on_call is not None and self.call_count == self._fail_on_call:
            raise RuntimeError("transient error")
        for chunk in self._chunks:
            yield chunk
