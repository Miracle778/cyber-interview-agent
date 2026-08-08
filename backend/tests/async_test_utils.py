from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar


T = TypeVar("T")

# These are deadlock guards, not performance requirements. Correctness tests
# must assert observable state or ordering instead of requiring a coroutine to
# finish within one or two wall-clock seconds on a particular CI runner.
ASYNC_SIGNAL_GUARD_SECONDS = 5.0
ASYNC_COMPLETION_GUARD_SECONDS = 15.0


async def wait_for_signal(
    signal: Awaitable[T],
    *,
    label: str,
    timeout: float = ASYNC_SIGNAL_GUARD_SECONDS,
) -> T:
    try:
        return await asyncio.wait_for(signal, timeout=timeout)
    except TimeoutError as exc:
        raise AssertionError(
            f"Timed out waiting for {label}; this guard detects a possible "
            "test deadlock and is not a performance assertion."
        ) from exc


async def wait_for_completion(
    operation: Awaitable[T],
    *,
    label: str,
    timeout: float = ASYNC_COMPLETION_GUARD_SECONDS,
) -> T:
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except TimeoutError as exc:
        raise AssertionError(
            f"Timed out waiting for {label}; the observable behavior was "
            "already asserted and the operation may be deadlocked."
        ) from exc
