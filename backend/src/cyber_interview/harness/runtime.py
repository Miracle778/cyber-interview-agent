from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cyber_interview.harness.model_gateway import Message, ModelGateway
from cyber_interview.harness.output_parser import FinalOutputParser, FinalOutputResult


@dataclass(frozen=True)
class RunContext:
    run_id: str
    attempt_id: str
    provider: str
    model: str
    messages: list[Message]
    checkpoint_ref: str | None = None


class RuntimeOutput:
    """Harness internal union: Delta | Final."""

    @dataclass(frozen=True)
    class Delta:
        text: str

    @dataclass(frozen=True)
    class Final:
        result: FinalOutputResult


@runtime_checkable
class AgentRuntime(Protocol):
    def run(self, ctx: RunContext) -> AsyncIterator[RuntimeOutput.Delta | RuntimeOutput.Final]: ...


class LoopAgentRuntime:
    """DU01 lightweight loop: stream ModelGateway -> accumulate -> parse final output."""

    def __init__(self, model_gateway: ModelGateway, parser: FinalOutputParser | None = None):
        self._gw = model_gateway
        self._parser = parser or FinalOutputParser()

    async def run(
        self, ctx: RunContext
    ) -> AsyncIterator[RuntimeOutput.Delta | RuntimeOutput.Final]:
        full_text_parts: list[str] = []
        finish_reason: str | None = None
        async for chunk in self._gw.stream(ctx.provider, ctx.model, ctx.messages):
            if chunk.type == "delta" and chunk.text:
                full_text_parts.append(chunk.text)
                yield RuntimeOutput.Delta(text=chunk.text)
            elif chunk.type == "done":
                finish_reason = chunk.finish_reason
        result = self._parser.parse("".join(full_text_parts), finish_reason=finish_reason)
        yield RuntimeOutput.Final(result=result)
