from dataclasses import dataclass
from typing import Protocol


class ToolInvokerProtocol(Protocol):
    async def __call__(
        self, name: str, raw_input: dict[str, object]
    ) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class GraphBuildContext:
    checkpointer: object
    invoke_tool: ToolInvokerProtocol


async def unavailable_tool_invoker(
    _name: str, _raw_input: dict[str, object]
) -> dict[str, object]:
    raise RuntimeError("Tool invocation is not configured")
