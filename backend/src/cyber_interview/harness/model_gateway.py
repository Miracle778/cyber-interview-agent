from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ModelChunk:
    type: str
    text: str | None = None
    finish_reason: str | None = None
    usage: dict | None = None


@runtime_checkable
class ModelGateway(Protocol):
    async def stream(
        self,
        provider: str,
        model: str,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ModelChunk]: ...
